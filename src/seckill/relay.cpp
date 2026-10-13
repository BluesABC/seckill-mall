#include "mall/relay.hpp"
#include <nlohmann/json.hpp>
namespace mall {
RelayResult PendingRelay::drain(Redis &redis, mq::Publisher &publisher,
                                const std::string &ledger,
                                const std::string &cursor, int count) {
  if (count < 1 || count > 1000)
    throw std::invalid_argument("Relay batch out of range");
  auto scan = redis.command({"HSCAN", ledger, cursor, "MATCH", "pending:*",
                             "COUNT", std::to_string(count)});
  if (scan->type != REDIS_REPLY_ARRAY || scan->elements != 2 ||
      scan->element[1]->type != REDIS_REPLY_ARRAY)
    throw RedisFailure("Pending scan failed");
  RelayResult result;
  result.cursor = text(scan->element[0]);
  auto fields = scan->element[1];
  for (size_t i = 0; i + 1 < fields->elements; i += 2) {
    auto field = text(fields->element[i]), raw = text(fields->element[i + 1]);
    if (raw.empty())
      continue;
    if (result.scanned >= count)
      break;
    ++result.scanned;
    auto event = nlohmann::json::parse(raw);
    auto reservation = event.at("reservationId").get<std::string>();
    if (event.at("schemaVersion") != 1 ||
        event.at("eventType") != "SECKILL_RESERVED" ||
        event.at("eventId") != reservation || event.at("quantity") != 1 ||
        field != "pending:" + reservation)
      throw RedisFailure("Invalid pending event; retained for investigation");
    mq::Message message{reservation, topic_,
                        event.at("activityId").get<std::string>() + ":" +
                            event.at("skuId").get<std::string>(),
                        raw};
    auto sent = publisher.publish(message);
    if (sent.outcome == mq::PublishOutcome::unknown) {
      ++result.unknown;
      continue;
    }
    if (sent.outcome == mq::PublishOutcome::rejected) {
      ++result.rejected;
      continue;
    }
    auto update = redis.eval(mark_, {ledger},
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
