/**
 * @file redis.hpp
 * @brief Redis连接和回复对象的资源所有权接口。
 *
 * Redis不可复制且不负责跨线程共享；Service为各线程持有独立连接，Reply以RAII释放hiredis回复。
 */
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
  /**
   * @brief 执行一条二进制安全的Redis命令。
   *
   * @param args 按独立参数传入，避免拼接命令造成空格/转义歧义。
   * @throws RedisFailure 无回复时结果可能未知，调用方不能盲目重放写命令。
   */
  Reply command(const std::vector<std::string> &args);
  // Only this read-only connectivity probe may retry after a broken socket.
  void probe();
  /**
   * @brief 优先EVALSHA，只有明确NOSCRIPT时加载脚本并再次执行。
   *
   * @param keys Lua的KEYS，须符合对应脚本契约。
   * @param args Lua的ARGV，不包含脚本文本和KEY数量。
   */
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
