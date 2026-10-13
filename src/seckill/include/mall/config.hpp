#pragma once
#include <cstdlib>
#include <stdexcept>
#include <string>

namespace mall {
inline std::string env(const char *name, std::string fallback) {
  auto value = std::getenv(name);
  return value ? std::string(value) : fallback;
}
inline int env_int(const char *name, int fallback, int maximum = 1000000) {
  auto value = env(name, std::to_string(fallback));
  size_t used = 0;
  int parsed = std::stoi(value, &used);
  if (used != value.size() || parsed < 1 || parsed > maximum)
    throw std::runtime_error(std::string("Invalid ") + name);
  return parsed;
}
struct Config {
  std::string host = env("MALL_HTTP_HOST", "127.0.0.1");
  std::string trusted_proxy = env("MALL_TRUSTED_PROXY", "");
  int port = env_int("MALL_HTTP_PORT", 8083, 65535);
  std::string redis_host = env("MALL_REDIS_HOST", "127.0.0.1");
  int redis_port = env_int("MALL_REDIS_PORT", 16379, 65535);
  int workers = env_int("MALL_HTTP_WORKERS", 8, 128);
  int queue_limit = env_int("MALL_HTTP_QUEUE", 128, 10000);
  int redis_timeout_ms = env_int("MALL_REDIS_TIMEOUT_MS", 1500, 10000);
  int ip_limit = env_int("MALL_IP_LIMIT", 100);
  int user_limit = env_int("MALL_USER_LIMIT", 20);
  int proof_limit = env_int("MALL_PROOF_LIMIT", 5);
  int max_pending = env_int("MALL_MAX_PENDING", 10000);
  std::string prefix = env("MALL_KEY_PREFIX", "seckill");
  std::string mq_topic = env("MALL_MQ_TOPIC", "seckill_reserved_v1");
  std::string lua_dir = env("MALL_LUA_DIR", MALL_DEFAULT_LUA_DIR);
  Config() {
    if (prefix.empty() || prefix.size() > 64 ||
        prefix.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRS"
                                 "TUVWXYZ0123456789_-") != std::string::npos)
      throw std::runtime_error("Invalid MALL_KEY_PREFIX");
    if (host.empty() || redis_host.empty())
      throw std::runtime_error("Empty host configuration");
    if (mq_topic.empty() || mq_topic.size() > 127 ||
        mq_topic.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-") != std::string::npos)
      throw std::runtime_error("Invalid MALL_MQ_TOPIC");
  }
};
} // namespace mall
