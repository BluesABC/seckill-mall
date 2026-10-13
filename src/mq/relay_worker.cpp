#include "mall/mq/rocketmq_publisher.hpp"
#include "mall/relay.hpp"
#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <string_view>
#include <thread>

namespace {
volatile sig_atomic_t stop_requested = 0;
void stop(int) { stop_requested = 1; }
std::string setting(const char *name, const char *fallback) {
  auto value = std::getenv(name);
  return value ? value : fallback;
}
class CrashAfterConfirmation : public mall::mq::Publisher {
 public:
  explicit CrashAfterConfirmation(mall::mq::Publisher &base) : base_(base) {}
  mall::mq::PublishResult publish(const mall::mq::Message &message) override {
    auto result = base_.publish(message);
    if (result.outcome == mall::mq::PublishOutcome::confirmed) std::_Exit(93);
    return result;
  }
  std::string_view backend() const noexcept override { return "test-crash-hook"; }
 private:
  mall::mq::Publisher &base_;
};
}
int main(int argc, char **argv) {
  try {
    if (argc != 2 || (std::string_view(argv[1]) != "--once" &&
                      std::string_view(argv[1]) != "--loop")) return 2;
    mall::Config config;
    auto endpoint = setting("MALL_MQ_ENDPOINT", "127.0.0.1:8081");
    auto topic = setting("MALL_MQ_TOPIC", "seckill_reserved_v1");
    mall::mq::RocketMqPublisher producer(endpoint, topic);
    mall::mq::Publisher *publisher = &producer;
    const auto crash = setting("MALL_TEST_CRASH_AFTER_SEND", "0");
    std::unique_ptr<CrashAfterConfirmation> test_hook;
    if (crash == "1") {
#ifdef MALL_TEST_HOOKS
      if (!config.prefix.starts_with("s3_test_")) return 2;
      test_hook = std::make_unique<CrashAfterConfirmation>(producer);
      publisher = test_hook.get();
#else
      return 2;
#endif
    }
    std::signal(SIGINT, stop);
    std::signal(SIGTERM, stop);
    mall::Redis redis(config);
    mall::PendingRelay relay(config);
    unsigned backoff_ms = 1000;
    do {
      int confirmed = 0, pending = 0;
      try {
        auto list = redis.command({"SSCAN", config.prefix + ":ledgers", "0", "COUNT", "100"});
        if (list->type != REDIS_REPLY_ARRAY || list->elements != 2 ||
            list->element[1]->type != REDIS_REPLY_ARRAY) throw mall::RedisFailure("Invalid ledger registry");
        std::string ledger_cursor = "0";
        do {
          for (size_t i = 0; i < list->element[1]->elements; ++i) {
            auto ledger_key = mall::text(list->element[1]->element[i]);
            if (!ledger_key.starts_with(config.prefix + ":{")) continue;
            std::string cursor = "0";
            do {
              auto result = relay.drain(redis, *publisher, ledger_key, cursor, 100);
              cursor = result.cursor;
              confirmed += result.confirmed;
              pending += result.unknown + result.rejected;
            } while (cursor != "0" && !stop_requested);
          }
          ledger_cursor = mall::text(list->element[0]);
          if (ledger_cursor != "0") {
            list = redis.command({"SSCAN", config.prefix + ":ledgers", ledger_cursor, "COUNT", "100"});
            if (list->type != REDIS_REPLY_ARRAY || list->elements != 2 ||
                list->element[1]->type != REDIS_REPLY_ARRAY) throw mall::RedisFailure("Invalid registry page");
          }
        } while (ledger_cursor != "0" && !stop_requested);
        backoff_ms = pending ? std::min(30000u, backoff_ms * 2) : 1000;
      } catch (const std::exception &) {
        pending = 1;
        backoff_ms = std::min(30000u, backoff_ms * 2);
      }
      std::cout << "confirmed=" << confirmed << " pendingRetry=" << pending << '\n' << std::flush;
      if (std::string_view(argv[1]) == "--once") return pending ? 3 : 0;
      for (unsigned waited = 0; waited < backoff_ms && !stop_requested; waited += 100)
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    } while (!stop_requested);
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "MQ relay unavailable: " << error.what() << '\n';
    return 3;
  }
}
