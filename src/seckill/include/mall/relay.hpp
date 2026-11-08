/**
 * @file relay.hpp
 * @brief 有界批量投递接口及逐批统计。
 *
 * cursor是SSCAN游标而非可靠消息位点；重复扫描由业务幂等与状态校验兜底。
 */
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
      : mark_(read_script(config, "mark_request")), topic_(config.mq_topic),
        active_ledgers_(config.prefix + ":relay_ledgers") {}
  /**
   * @brief 扫描一批待发送预留并在确认发送后推进状态。
   *
   * @param count 本批实际处理上限，范围1–1000；不是吞吐目标。
   * @return 下一扫描游标及confirmed/unknown/rejected数量；unknown保留待重试。
   */
  RelayResult drain(Redis &redis, mq::Publisher &publisher,
                    const std::string &ledger, const std::string &cursor = "0",
                    int count = 100);

private:
  std::string mark_;
  std::string topic_;
  std::string active_ledgers_;
};
} // namespace mall
