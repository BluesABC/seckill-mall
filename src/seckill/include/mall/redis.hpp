#pragma once
#include "mall/config.hpp"
#include <hiredis/hiredis.h>
#include <memory>
#include <string>
#include <vector>

namespace mall {
struct RedisFailure : std::runtime_error {
  using std::runtime_error::runtime_error;
};
struct ReplyDeleter {
  void operator()(redisReply *r) const { freeReplyObject(r); }
};
using Reply = std::unique_ptr<redisReply, ReplyDeleter>;
std::string sha256(const std::string &input);
std::string random_hex(size_t bytes);
std::string random_uuid();
class Redis {
public:
  explicit Redis(const Config &config) : config_(config) {}
  ~Redis() {
    if (context_)
      redisFree(context_);
  }
  Redis(const Redis &) = delete;
  Redis &operator=(const Redis &) = delete;
  Reply command(const std::vector<std::string> &args);
  // Only this read-only connectivity probe may retry after a broken socket.
  void probe();
  Reply eval(const std::string &script, const std::vector<std::string> &keys,
             const std::vector<std::string> &args);

private:
  Config config_;
  redisContext *context_ = nullptr;
  void ensure_connected();
};
std::string text(const redisReply *reply);
std::string read_script(const Config &config, const std::string &name);
} // namespace mall
