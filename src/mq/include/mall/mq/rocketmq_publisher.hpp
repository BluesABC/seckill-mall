#pragma once
#include "mall/mq/publisher.hpp"
#include <memory>
#include <string>

namespace mall::mq {
class RocketMqPublisher final : public Publisher {
public:
  RocketMqPublisher(std::string endpoint, std::string topic);
  ~RocketMqPublisher() override;
  PublishResult publish(const Message &message) override;
  std::string_view backend() const noexcept override { return "RocketMQ"; }

private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
  std::string topic_;
};
} // namespace mall::mq
