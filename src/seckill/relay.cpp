#include "mall/relay.hpp"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <iostream>
namespace mall {
RelayResult PendingRelay::drain(Redis &redis, mq::Publisher &publisher,
                                const std::string &ledger,
                                const std::string &cursor, int count) {
  if (count < 1 || count > 1000)
    throw std::invalid_argument("Relay batch out of range");
  const auto pending_set = ledger + ":relay_pending";
  auto scan = redis.command({"SSCAN", pending_set, cursor, "COUNT",
                             std::to_string(count)});
  if (scan->type != REDIS_REPLY_ARRAY || scan->elements != 2 ||
      scan->element[1]->type != REDIS_REPLY_ARRAY)
    throw RedisFailure("Pending scan failed");
  RelayResult result;
  result.cursor = text(scan->element[0]);
  auto reservations = scan->element[1];
  for (size_t i = 0; i < reservations->elements; ++i) {
    if (result.scanned >= count)
      break;
    ++result.scanned;
    auto reservation = text(reservations->element[i]);
    auto raw_reply = redis.command({"HGET", ledger, "pending:" + reservation});
    if (raw_reply->type == REDIS_REPLY_NIL ||
        (raw_reply->type == REDIS_REPLY_STRING && text(raw_reply.get()).empty())) {
      redis.command({"SREM", pending_set, reservation});
      continue;
    }
    auto raw = text(raw_reply.get());
    auto event = nlohmann::json::parse(raw);
    if (event.at("schemaVersion") != 1 ||
        event.at("eventType") != "SECKILL_RESERVED" ||
        event.at("eventId") != reservation || event.at("reservationId") != reservation ||
        event.at("quantity") != 1)
      throw RedisFailure("Invalid pending event; retained for investigation");
    mq::Message message{reservation, topic_,
                        event.at("activityId").get<std::string>() + ":" +
                            event.at("skuId").get<std::string>(),
                        raw};
    const auto relay_seen_at_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    const auto reservation_created_ms = std::stoll(event.at("createdAtMs").get<std::string>());
    auto sent = publisher.publish(message);
    const auto publish_returned_at_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    std::clog << "event=seckill_stage stage=relay_publish reservationId=" << reservation
              << " traceId=" << event.at("traceId").get<std::string>()
              << " reservationCreatedAtMs=" << reservation_created_ms
              << " relayObservedAtMs=" << relay_seen_at_ms
              << " relayPendingAgeMs=" << std::max<int64_t>(0, relay_seen_at_ms - reservation_created_ms)
              << " publishCallMs=" << std::max<int64_t>(0, publish_returned_at_ms - relay_seen_at_ms)
              << " publishReturnedAtMs=" << publish_returned_at_ms
              << " outcome=" << (sent.outcome == mq::PublishOutcome::confirmed ? "confirmed" :
                                  sent.outcome == mq::PublishOutcome::rejected ? "rejected" : "unknown")
              << '\n';
    if (sent.outcome == mq::PublishOutcome::unknown) {
      ++result.unknown;
      continue;
    }
    if (sent.outcome == mq::PublishOutcome::rejected) {
      ++result.rejected;
      continue;
    }
    auto update = redis.eval(mark_, {ledger, active_ledgers_, pending_set},
                             {event.at("userId").get<std::string>(),
                              event.at("requestId").get<std::string>(),
                              reservation, event.at("epoch").get<std::string>(),
                              "RESERVED", "QUEUED"});
    if (update->type != REDIS_REPLY_ARRAY || update->elements < 1)
      throw RedisFailure("Relay state update failed");
    auto code = text(update->element[0]);
    if (code == "STATE_CONFLICT") {
      ++result.rejected;
      continue;
    }
    if (code != "UPDATED" && code != "REPLAY" && code != "ALREADY_ADVANCED")
      throw RedisFailure("Relay confirmation not applied");
    // A terminal consumer may already have advanced the request; never regress
    // it.
    ++result.confirmed;
  }
  return result;
}
} // namespace mall
