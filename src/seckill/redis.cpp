#include "mall/redis.hpp"
#include <fstream>
#include <openssl/evp.h>
#include <openssl/rand.h>
#include <sstream>

namespace mall {
namespace {
std::string hex(const unsigned char *data, size_t size) {
  constexpr char alphabet[] = "0123456789abcdef";
  std::string out;
  out.reserve(size * 2);
  for (size_t i = 0; i < size; ++i) {
    out += alphabet[data[i] >> 4];
    out += alphabet[data[i] & 15];
  }
  return out;
}
std::string digest(const std::string &input, const EVP_MD *algorithm) {
  unsigned char buffer[EVP_MAX_MD_SIZE];
  unsigned int size = 0;
  if (EVP_Digest(input.data(), input.size(), buffer, &size, algorithm,
                 nullptr) != 1)
    throw std::runtime_error("Digest failed");
  return hex(buffer, size);
}
} // namespace
std::string sha256(const std::string &input) {
  return digest(input, EVP_sha256());
}
std::string random_hex(size_t bytes) {
  std::vector<unsigned char> data(bytes);
  if (RAND_bytes(data.data(), static_cast<int>(bytes)) != 1)
    throw std::runtime_error("Entropy unavailable");
  return hex(data.data(), bytes);
}
std::string random_uuid() {
  auto value = random_hex(16);
  value[12] = '4';
  value[16] = "89ab"[std::string_view("0123456789abcdef").find(value[16]) & 3];
  return value.substr(0, 8) + "-" + value.substr(8, 4) + "-" +
         value.substr(12, 4) + "-" + value.substr(16, 4) + "-" +
         value.substr(20);
}
void Redis::ensure_connected() {
  if (context_)
    return;
  timeval connect_timeout{0, 500000};
  context_ = redisConnectWithTimeout(config_.redis_host.c_str(),
                                     config_.redis_port, connect_timeout);
  if (!context_ || context_->err) {
    if (context_)
      redisFree(context_);
    context_ = nullptr;
    throw RedisFailure("Redis connection failed");
  }
  timeval timeout{config_.redis_timeout_ms / 1000,
                  (config_.redis_timeout_ms % 1000) * 1000};
  if (redisSetTimeout(context_, timeout) != REDIS_OK) {
    redisFree(context_);
    context_ = nullptr;
    throw RedisFailure("Redis timeout configuration failed");
  }
}
void Redis::probe() {
  for (int attempt = 0; attempt < 2; ++attempt) {
    try {
      auto reply = command({"PING"});
      if (reply->type == REDIS_REPLY_STATUS && text(reply.get()) == "PONG")
        return;
      throw RedisFailure("Redis not ready");
    } catch (const RedisFailure &) {
      if (attempt == 1) throw;
    }
  }
}
Reply Redis::command(const std::vector<std::string> &args) {
  ensure_connected();
  std::vector<const char *> argv;
  std::vector<size_t> sizes;
  for (auto &arg : args) {
    argv.push_back(arg.data());
    sizes.push_back(arg.size());
  }
  Reply reply(static_cast<redisReply *>(redisCommandArgv(
      context_, static_cast<int>(argv.size()), argv.data(), sizes.data())));
  if (!reply) {
    redisFree(context_);
    context_ = nullptr;
    throw RedisFailure("Redis command outcome unknown");
  }
  return reply;
}
Reply Redis::eval(const std::string &script,
                  const std::vector<std::string> &keys,
                  const std::vector<std::string> &args) {
  auto script_sha = digest(script, EVP_sha1());
  std::vector<std::string> command_args{"EVALSHA", script_sha,
                                        std::to_string(keys.size())};
  command_args.insert(command_args.end(), keys.begin(), keys.end());
  command_args.insert(command_args.end(), args.begin(), args.end());
  auto result = command(command_args);
  if (result->type == REDIS_REPLY_ERROR &&
      text(result.get()).starts_with("NOSCRIPT")) {
    auto loaded = command({"SCRIPT", "LOAD", script});
    if (loaded->type == REDIS_REPLY_ERROR)
      throw RedisFailure("Lua load failed");
    result = command(command_args);
  }
  if (result->type == REDIS_REPLY_ERROR)
    throw RedisFailure("Lua execution failed");
  return result;
}
std::string text(const redisReply *reply) {
  if (!reply || reply->type == REDIS_REPLY_NIL)
    return {};
  if (reply->type == REDIS_REPLY_ERROR)
    return reply->str ? std::string(reply->str, reply->len) : "Redis error";
  if (reply->type == REDIS_REPLY_INTEGER)
    return std::to_string(reply->integer);
  if (!reply->str)
    throw RedisFailure("Unexpected Redis reply");
  return std::string(reply->str, reply->len);
}
std::string read_script(const Config &config, const std::string &name) {
  std::ifstream file(config.lua_dir + "/" + name + ".lua");
  if (!file)
    throw std::runtime_error("Lua file missing: " + name);
  std::ostringstream out;
  out << file.rdbuf();
  if (out.str().empty())
    throw std::runtime_error("Empty Lua file");
  return out.str();
}
} // namespace mall
