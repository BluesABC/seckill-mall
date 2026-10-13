#include "mall/relay.hpp"
#include <iostream>

// Test-only publisher: this binary is never launched by the HTTP service.
class ProbePublisher : public mall::mq::Publisher {
public:
  explicit ProbePublisher(mall::mq::PublishOutcome value) : outcome(value) {}
  mall::mq::PublishResult publish(const mall::mq::Message &message) override {
    if (message.event_id.empty() || message.topic != "seckill_reserved_v1" ||
        message.payload_utf8.empty())
      throw std::runtime_error("Invalid message mapping");
    return {outcome, "test-only-receipt", "probe"};
  }
  std::string_view backend() const noexcept override { return "test-probe"; }

private:
  mall::mq::PublishOutcome outcome;
};
int main(int argc, char **argv) {
  try {
    if (argc != 3)
      return 2;
    auto outcome = std::string(argv[2]);
    if (outcome != "confirmed" && outcome != "unknown" && outcome != "rejected")
      return 2;
    mall::Config config;
    if (!config.prefix.starts_with("s2_test_") ||
        !std::string(argv[1]).starts_with(config.prefix + ":{"))
      throw std::runtime_error("Probe is restricted to its S2 test namespace");
    mall::Redis redis(config);
    mall::PendingRelay relay(config);
    ProbePublisher publisher(
        outcome == "confirmed" ? mall::mq::PublishOutcome::confirmed
        : outcome == "unknown" ? mall::mq::PublishOutcome::unknown
                               : mall::mq::PublishOutcome::rejected);
    std::string cursor = "0";
    int scanned = 0;
    do {
      auto result = relay.drain(redis, publisher, argv[1], cursor);
      cursor = result.cursor;
      scanned += result.scanned;
    } while (cursor != "0");
    std::cout << "scanned=" << scanned << '\n';
    return 0;
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
