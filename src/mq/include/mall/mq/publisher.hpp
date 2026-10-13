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
  virtual PublishResult publish(const Message &message) = 0;
  virtual std::string_view backend() const noexcept = 0;
};
// S3 implements RocketMQ adapter. Unknown is retried with the original
// event_id; it is never proof that Redis stock can be released. No broker
// implementation here.
} // namespace mall::mq
