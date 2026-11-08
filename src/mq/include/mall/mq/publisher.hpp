/**
 * @file publisher.hpp
 * @brief 不绑定消息中间件的发布契约。
 *
 * event_id是稳定业务身份，receipt是中间件回执；unknown必须按原业务身份重试。
 */
#pragma once
#include <string>
#include <string_view>

namespace mall::mq {
struct Message {
  std::string event_id; // Business identity; retained across retries.
  std::string topic;
  std::string
      partition_key; // activityId:skuId; indexed as a key on normal RocketMQ topics.
  std::string payload_utf8; // Validated reserved-event JSON; SDK-independent.
};
enum class PublishOutcome { confirmed, unknown, rejected };
struct PublishResult {
  PublishOutcome outcome;
  std::string receipt; // Opaque backend receipt, never the business id.
  std::string diagnostic_code;
};
class Publisher {
public:
  virtual ~Publisher() = default;
  /**
   * @brief 发布一次消息，不在该接口内承诺端到端exactly-once。
   *
   * @param message 重试时保留event_id及业务payload。
   * @return confirmed仅代表适配器获得发送回执，unknown不代表发送失败。
   */
  virtual PublishResult publish(const Message &message) = 0;
  virtual std::string_view backend() const noexcept = 0;
};
// S3 implements RocketMQ adapter. Unknown is retried with the original
// event_id; it is never proof that Redis stock can be released. No broker
// implementation here.
} // namespace mall::mq
