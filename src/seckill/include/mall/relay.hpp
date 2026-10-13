#pragma once
#include "mall/mq/publisher.hpp"
#include "mall/redis.hpp"
namespace mall {
struct RelayResult {
  std::string cursor;
  int scanned = 0, confirmed = 0, unknown = 0, rejected = 0;
};
class PendingRelay {
public:
  explicit PendingRelay(const Config &config)
      : mark_(read_script(config, "mark_request")), topic_(config.mq_topic) {}
  RelayResult drain(Redis &redis, mq::Publisher &publisher,
                    const std::string &ledger, const std::string &cursor = "0",
                    int count = 100);

private:
  std::string mark_;
  std::string topic_;
};
} // namespace mall
