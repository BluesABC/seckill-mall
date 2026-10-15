#include "mall/mq/rocketmq_publisher.hpp"
#include <exception>
#include <fcntl.h>
#include <chrono>
#include <netdb.h>
#include <poll.h>
#include <rocketmq/Configuration.h>
#include <rocketmq/Message.h>
#include <rocketmq/Producer.h>
#include <stdexcept>
#include <sys/socket.h>
#include <unistd.h>

namespace mall::mq {
namespace sdk = ROCKETMQ_NAMESPACE;
namespace {
bool endpoint_reachable(const std::string &endpoint) {
  auto colon = endpoint.rfind(':');
  if (colon == std::string::npos || colon == 0 || colon + 1 == endpoint.size())
    return false;
  auto host = endpoint.substr(0, colon);
  if (host.size() > 2 && host.front() == '[' && host.back() == ']')
    host = host.substr(1, host.size() - 2);
  auto port = endpoint.substr(colon + 1);
  addrinfo hints{};
  hints.ai_family = AF_UNSPEC;
  hints.ai_socktype = SOCK_STREAM;
  addrinfo *addresses = nullptr;
  if (getaddrinfo(host.c_str(), port.c_str(), &hints, &addresses) != 0)
    return false;
  bool connected = false;
  for (auto *address = addresses; address && !connected;
       address = address->ai_next) {
    int fd =
        socket(address->ai_family, address->ai_socktype, address->ai_protocol);
    if (fd < 0)
      continue;
    int flags = fcntl(fd, F_GETFL, 0);
    if (flags >= 0 && fcntl(fd, F_SETFL, flags | O_NONBLOCK) == 0) {
      int status = connect(fd, address->ai_addr, address->ai_addrlen);
      if (status == 0)
        connected = true;
      else if (errno == EINPROGRESS) {
        pollfd descriptor{fd, POLLOUT, 0};
        if (poll(&descriptor, 1, 750) > 0) {
          int error = 0;
          socklen_t length = sizeof(error);
          connected =
              getsockopt(fd, SOL_SOCKET, SO_ERROR, &error, &length) == 0 &&
              error == 0;
        }
      }
    }
    close(fd);
  }
  freeaddrinfo(addresses);
  return connected;
}
} // namespace
struct RocketMqPublisher::Impl {
  sdk::Producer producer;
  Impl(const std::string &endpoint, const std::string &topic)
      : producer(sdk::Producer::newBuilder()
                     .withConfiguration(
                         sdk::Configuration::newBuilder()
                             .withEndpoints(endpoint)
                             .withSsl(false)
                             .withRequestTimeout(std::chrono::seconds(5))
                             .build())
                     .withTopics({topic})
                     .build()) {}
};
RocketMqPublisher::RocketMqPublisher(std::string endpoint, std::string topic)
    : topic_(std::move(topic)) {
  // The pinned upstream SDK retries session establishment without a deadline
  // when the proxy socket is absent. Fail before constructing that client.
  if (!endpoint_reachable(endpoint))
    throw std::runtime_error("RocketMQ proxy endpoint unreachable");
  impl_ = std::make_unique<Impl>(endpoint, topic_);
}
RocketMqPublisher::~RocketMqPublisher() = default;

PublishResult RocketMqPublisher::publish(const Message &message) {
  if (message.topic != topic_ || message.event_id.empty() ||
      message.partition_key.empty() || message.payload_utf8.empty() ||
      message.payload_utf8.size() > 1048576)
    return {PublishOutcome::rejected, "", "INVALID_LOCAL_MESSAGE"};
  try {
    const auto relay_send_started_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    auto packet =
        sdk::Message::newBuilder()
            .withTopic(message.topic)
            .withTag("SECKILL_RESERVED")
            .withKeys({message.event_id, message.partition_key})
            .withProperties({{"mallActivitySku", message.partition_key},
                             {"mallEventId", message.event_id},
                             {"mallRelaySendStartedAtMs", std::to_string(relay_send_started_ms)}})
            .withBody(message.payload_utf8)
            .build();
    std::error_code error;
    auto receipt = impl_->producer.send(std::move(packet), error);
    if (error)
      return {PublishOutcome::unknown, "", "SEND_OUTCOME_UNKNOWN"};
    if (receipt.message_id.empty())
      return {PublishOutcome::unknown, "", "EMPTY_BROKER_RECEIPT"};
    return {PublishOutcome::confirmed, receipt.message_id, "OK"};
  } catch (const std::exception &) {
    return {PublishOutcome::unknown, "", "SDK_EXCEPTION"};
  }
}
} // namespace mall::mq
