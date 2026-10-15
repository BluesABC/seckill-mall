#include "mall/service.hpp"
#include "mall/captcha.hpp"
#include "mall/redis.hpp"
#include <atomic>
#include <arpa/inet.h>
#include <chrono>
#include <csignal>
#include <functional>
#include <httplib.h>
#include <iostream>
#include <map>
#include <mutex>
#include <nlohmann/json.hpp>
#include <pthread.h>
#include <regex>
#include <set>
#include <thread>

namespace mall {
using Json = nlohmann::json;
struct ApiError : std::runtime_error {
  int status;
  int retry_after;
  ApiError(int s, std::string code, int retry = 1)
      : std::runtime_error(std::move(code)), status(s), retry_after(retry) {}
};
namespace {
void checked(const redisReply *r) {
  if (!r || r->type == REDIS_REPLY_ERROR)
    throw RedisFailure("Redis rejected command");
}
std::map<std::string, std::string> hash(Redis &redis, const std::string &key) {
  auto reply = redis.command({"HGETALL", key});
  checked(reply.get());
  if (reply->type != REDIS_REPLY_ARRAY || reply->elements % 2)
    throw RedisFailure("Malformed hash reply");
  std::map<std::string, std::string> values;
  for (size_t i = 0; i < reply->elements; i += 2)
    values[text(reply->element[i])] = text(reply->element[i + 1]);
  return values;
}
long long server_time(Redis &redis) {
  auto r = redis.command({"TIME"});
  checked(r.get());
  if (r->type != REDIS_REPLY_ARRAY || r->elements != 2)
    throw RedisFailure("Malformed time");
  return std::stoll(text(r->element[0])) * 1000 +
         std::stoll(text(r->element[1])) / 1000;
}
bool uuid(const std::string &v) {
  static const std::regex pattern(
      "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$");
  return std::regex_match(v, pattern);
}
bool hex64(const std::string &v) {
  return v.size() == 64 &&
         v.find_first_not_of("0123456789abcdef") == std::string::npos;
}
void identifier(const std::string &v) {
  if (v.empty() || v[0] == '0' || v.size() > 19 ||
      v.find_first_not_of("0123456789") != std::string::npos ||
      (v.size() == 19 && v > "9223372036854775807"))
    throw ApiError(400, "INVALID_ARGUMENT");
}
std::string query(const httplib::Request &r, const std::string &key) {
  if (r.get_param_value_count(key) != 1)
    throw ApiError(400, "INVALID_ARGUMENT");
  return r.get_param_value(key);
}
void query_keys(const httplib::Request &r,
                const std::set<std::string> &allowed) {
  // cpp-httplib deduplicates identical raw pairs. Validate the original target
  // so parameter pollution is rejected even when the parsed map looks unique.
  auto position = r.target.find('?');
  std::set<std::string> seen;
  if (position != std::string::npos) {
    auto raw = r.target.substr(position + 1);
    size_t start = 0;
    while (start <= raw.size()) {
      auto end = raw.find('&', start);
      auto part =
          raw.substr(start, end == std::string::npos ? end : end - start);
      auto name = part.substr(0, part.find('='));
      if (!allowed.contains(name) || !seen.insert(name).second)
        throw ApiError(400, "INVALID_ARGUMENT");
      if (end == std::string::npos)
        break;
      start = end + 1;
    }
  }
  for (auto &[key, value] : r.params)
    if (!allowed.contains(key))
      throw ApiError(400, "INVALID_ARGUMENT");
}
Json body(const httplib::Request &r, const std::set<std::string> &expected) {
  auto type = r.get_header_value("Content-Type");
  if (type != "application/json" && !type.starts_with("application/json;"))
    throw ApiError(400, "INVALID_ARGUMENT");
  std::set<std::string> seen;
  auto result =
      Json::parse(r.body, [&](int, Json::parse_event_t event, Json &value) {
        if (event == Json::parse_event_t::key &&
            !seen.insert(value.get<std::string>()).second)
          throw ApiError(400, "INVALID_ARGUMENT");
        return true;
      });
  if (!result.is_object() || result.size() != expected.size())
    throw ApiError(400, "INVALID_ARGUMENT");
  for (auto &key : expected)
    if (!result.contains(key) || !result[key].is_string())
      throw ApiError(400, "INVALID_ARGUMENT");
  return result;
}
void json(httplib::Response &r, int status, const Json &value) {
  r.status = status;
  r.set_content(value.dump(), "application/json; charset=utf-8");
}
struct Counters {
  std::atomic<unsigned long long> requests{0}, errors{0}, reserved{0},
      accepted{0}, unknown{0}, replayed{0}, limited{0}, duration_us{0};
};
struct Session {
  std::string user, role;
};
class Service {
public:
  Config config;
  Counters counters;
  std::string reserve_script, proof_script, limit_script;
  explicit Service(Config c)
      : config(std::move(c)), reserve_script(read_script(config, "reserve")),
        proof_script(read_script(config, "issue_proof")),
        limit_script(read_script(config, "rate_limit")) {}
  Redis &redis() {
    thread_local std::unique_ptr<Redis> client;
    if (!client)
      client = std::make_unique<Redis>(config);
    return *client;
  }
  std::string ledger(const std::string &a, const std::string &s) const {
    return config.prefix + ":{" + a + ":" + s + "}:ledger";
  }
  std::string challenge(const std::string &a, const std::string &s,
                        const std::string &id) const {
    return config.prefix + ":{" + a + ":" + s + "}:challenge:" + id;
  }
  bool member(const std::string &key, const std::string &value) {
    auto r = redis().command({"SISMEMBER", key, value});
    checked(r.get());
    if (r->type != REDIS_REPLY_INTEGER)
      throw RedisFailure("Invalid membership");
    return r->integer != 0;
  }
  void limit(const std::string &kind, const std::string &id, int maximum,
             int ttl = 1000) {
    auto reply = redis().eval(
        limit_script, {config.prefix + ":limit:" + kind + ":" + sha256(id)},
        {std::to_string(maximum), std::to_string(ttl)});
    if (reply->type != REDIS_REPLY_INTEGER || reply->integer != 1) {
      ++counters.limited;
      throw ApiError(429, "RATE_LIMITED", (ttl + 999) / 1000);
    }
  }
  Session auth(const httplib::Request &r) {
    if (r.get_header_value_count("Authorization") != 1)
      throw ApiError(401, "UNAUTHENTICATED");
    auto header = r.get_header_value("Authorization");
    if (!header.starts_with("Bearer ") || !hex64(header.substr(7)))
      throw ApiError(401, "UNAUTHENTICATED");
    auto values =
        hash(redis(), config.prefix + ":session:" + sha256(header.substr(7)));
    if (!values.contains("userId") || !values.contains("role") ||
        !values.contains("expiresAtMs"))
      throw ApiError(401, "UNAUTHENTICATED");
    long long expires = 0;
    try {
      identifier(values["userId"]);
      identifier(values["expiresAtMs"]);
      if (values["role"] != "USER" && values["role"] != "ADMIN")
        throw ApiError(401, "UNAUTHENTICATED");
      expires = std::stoll(values["expiresAtMs"]);
    } catch (const std::exception &) {
      throw ApiError(401, "UNAUTHENTICATED");
    }
    if (expires <= server_time(redis()))
      throw ApiError(401, "UNAUTHENTICATED");
    if (member(config.prefix + ":blacklist:user", values["userId"]))
      throw ApiError(403, "FORBIDDEN");
    limit("user", values["userId"], config.user_limit);
    return {values["userId"], values["role"]};
  }
  auto wrap(std::function<void(const httplib::Request &, httplib::Response &,
                               const std::string &)>
                handler,
            bool guarded = true) {
    return [this, handler = std::move(handler),
            guarded](const httplib::Request &req, httplib::Response &response) {
      auto begin = std::chrono::steady_clock::now();
      auto trace = random_uuid();
      ++counters.requests;
      response.set_header("Cache-Control", "no-store");
      response.set_header("X-Trace-Id", trace);
      try {
        if (guarded) {
          // Refresh each worker's socket before any rate-limit/proof/reservation write.
          // A mutation's unknown result is never retried here.
          redis().probe();
          auto client_ip=req.remote_addr;
          if(!config.trusted_proxy.empty()&&req.remote_addr==config.trusted_proxy){
            if(req.get_header_value_count("X-Real-IP")!=1)throw ApiError(400,"INVALID_ARGUMENT");
            client_ip=req.get_header_value("X-Real-IP");
            unsigned char addr[16];
            if(inet_pton(AF_INET,client_ip.c_str(),addr)!=1&&inet_pton(AF_INET6,client_ip.c_str(),addr)!=1)throw ApiError(400,"INVALID_ARGUMENT");
          }
          if (member(config.prefix + ":blacklist:ip", sha256(client_ip)))
            throw ApiError(403, "FORBIDDEN");
          limit("ip", client_ip, config.ip_limit);
        }
        handler(req, response, trace);
      } catch (const ApiError &error) {
        json(response, error.status,
             {{"code", error.what()},
              {"message", error.what()},
              {"traceId", trace},
              {"retryable", error.status >= 500 || error.status == 429}});
        if (error.status == 429)
          response.set_header("Retry-After", std::to_string(error.retry_after));
      } catch (const RedisFailure &) {
        json(response, 503,
             {{"code", "DEPENDENCY_UNAVAILABLE"},
              {"message", "Redis unavailable"},
              {"traceId", trace},
              {"retryable", true}});
      } catch (const Json::exception &) {
        json(response, 400,
             {{"code", "INVALID_ARGUMENT"},
              {"message", "Invalid JSON request"},
              {"traceId", trace},
              {"retryable", false}});
      } catch (const std::exception &) {
        json(response, 500,
             {{"code", "INTERNAL_ERROR"},
              {"message", "Internal service error"},
              {"traceId", trace},
              {"retryable", true}});
      }
      if (response.status >= 400)
        ++counters.errors;
      auto elapsed = std::chrono::duration_cast<std::chrono::microseconds>(
                         std::chrono::steady_clock::now() - begin)
                         .count();
      counters.duration_us += elapsed;
      if (req.path != "/health/live" && req.path != "/health/ready") {
        static std::mutex output;
        std::lock_guard lock(output);
        std::clog << Json({{"traceId", trace},
                           {"path", req.path},
                           {"status", response.status},
                           {"rtUs", elapsed}})
                         .dump()
                  << '\n';
      }
    };
  }
  std::map<std::string, std::string> activity(const std::string &a,
                                              const std::string &s) {
    identifier(a);
    identifier(s);
    auto values = hash(redis(), ledger(a, s));
    if (values.empty())
      throw ApiError(404, "NOT_FOUND");
    for (auto &key : {"stock", "startsAtMs", "endsAtMs", "status", "epoch",
                      "priceFen", "activityId", "skuId"})
      if (!values.contains(key))
        throw ApiError(503, "NOT_READY");
    if (values["activityId"] != a || values["skuId"] != s)
      throw ApiError(503, "NOT_READY");
    return values;
  }
  Json status(const std::string &raw, const std::string &request) {
    auto value = Json::parse(raw);
    if (value.value("state", "") == "ORDER_CREATED")
      throw ApiError(503, "ORDER_SERVICE_UNAVAILABLE");
    return {{"requestId", request},
            {"reservationId", value.at("reservationId")},
            {"requestState", value.at("state")},
            {"orderId", nullptr},
            {"orderState", nullptr},
            {"amountFen", nullptr},
            {"expiresAtMs", nullptr},
            {"failureCode", value.value("state", "") == "FAILED"
                                ? Json("RESERVATION_TERMINATED")
                                : Json(nullptr)}};
  }
  void durability_fence(const std::string &key) {
    // A causal write on this same connection fences read-only replays too.
    auto fence =
        redis().command({"HSET", key, "durabilityFence", random_uuid()});
    checked(fence.get());
    auto confirmed = redis().command({"WAITAOF", "1", "0", "1000"});
    checked(confirmed.get());
    if (confirmed->type != REDIS_REPLY_ARRAY || confirmed->elements != 2 ||
        confirmed->element[0]->integer != 1)
      throw RedisFailure("AOF confirmation unknown");
  }
  void bind(httplib::Server &server) {
    server.Get(
        "/health/live",
        wrap(
            [](auto &, auto &out, auto &) {
              json(out, 200,
                   {{"service", "seckill"}, {"status", "UP"}, {"stage", "S2"}});
            },
            false));
    server.Get(
        "/health/ready",
        wrap(
            [this](auto &, auto &out, auto &) {
              auto r = redis().command({"CONFIG", "GET", "appendonly",
                                        "appendfsync", "maxmemory-policy"});
              checked(r.get());
              std::map<std::string, std::string> c;
              for (size_t i = 0; i + 1 < r->elements; i += 2)
                c[text(r->element[i])] = text(r->element[i + 1]);
              if (c["appendonly"] != "yes" || c["appendfsync"] != "always" ||
                  c["maxmemory-policy"] != "noeviction")
                throw ApiError(503, "NOT_READY");
              json(out, 200,
                   {{"ready", true},
                    {"scope", "seckill-and-Redis"},
                    {"mqIntegrated", false}});
            },
            false));
    server.Get("/api/seckill/info", wrap([this](auto &req, auto &out, auto &) {
                 query_keys(req, {"activityId", "skuId"});
                 auto a = query(req, "activityId"), s = query(req, "skuId");
                 auto v = activity(a, s);
                 auto now = server_time(redis());
                 auto state = v["status"];
                 if (now >= std::stoll(v["endsAtMs"]))
                   state = "ENDED";
                 json(out, 200,
                      {{"activityId", a},
                       {"skuId", s},
                       {"title", v.contains("title") ? v["title"] : "SKU " + s},
                       {"priceFen", v["priceFen"]},
                       {"startsAtMs", v["startsAtMs"]},
                       {"endsAtMs", v["endsAtMs"]},
                       {"serverTimeMs", std::to_string(now)},
                       {"state", state},
                       {"stockAvailable", std::stoll(v["stock"]) > 0}});
               }));
    server.Get("/api/seckill/captcha",
               wrap([this](auto &req, auto &out, auto &) {
                 auto session = auth(req);
                 query_keys(req, {"activityId", "skuId", "mode"});
                 auto a = query(req, "activityId"), s = query(req, "skuId");
                 auto mode = req.has_param("mode") ? query(req, "mode") : "image";
                 if (mode != "image" && mode != "accessible")
                   throw ApiError(400, "INVALID_ARGUMENT");
                 auto values = activity(a, s);
                 limit("proof", session.user, config.proof_limit, 60000);
                 auto image = mode == "accessible" ? create_accessible_captcha()
                                                    : create_captcha();
                 auto id = random_uuid();
                 auto expires = server_time(redis()) + 60000;
                 Json proof = {{"userId", session.user},
                               {"activityId", a},
                               {"skuId", s},
                               {"epoch", values["epoch"]},
                               {"answerDigest", sha256(image.answer)},
                               {"attempts", 0},
                               {"used", false},
                               {"expiresAtMs", expires}};
                 auto stored = redis().command(
                     {"SET", challenge(a, s, id), proof.dump(), "EX", "60"});
                 checked(stored.get());
                 Json response = {{"captchaId", id},
                                  {"mode", mode},
                                  {"expiresAtMs", std::to_string(expires)}};
                 if (mode == "image")
                   response["imageDataUrl"] = image.image_data_url;
                 else
                   response["challengeText"] = image.accessible_prompt;
                 json(out, 200, response);
               }));
    server.Post(
        "/api/seckill/token", wrap([this](auto &req, auto &out, auto &) {
          auto session = auth(req);
          auto input = body(req, {"activityId", "skuId", "requestId",
                                  "captchaId", "captchaAnswer"});
          std::string a = input["activityId"], s = input["skuId"],
                      request = input["requestId"], id = input["captchaId"],
                      answer = input["captchaAnswer"];
          if (!uuid(request) || !uuid(id) || answer.empty() || answer.size() > 6 ||
              answer.find_first_not_of("0123456789") != std::string::npos)
            throw ApiError(400, "INVALID_ARGUMENT");
          auto values = activity(a, s);
          auto activity_token = id + "." + random_hex(32),
               captcha_token = random_hex(32);
          auto reply = redis().eval(proof_script, {challenge(a, s, id)},
                                    {session.user, request, sha256(answer),
                                     sha256(captcha_token),
                                     sha256(activity_token), values["epoch"]});
          if (reply->type != REDIS_REPLY_ARRAY || reply->elements < 1)
            throw RedisFailure("Invalid proof response");
          if (text(reply->element[0]) != "ISSUED")
            throw ApiError(403, "INVALID_PROOF");
          json(out, 200,
               {{"activityToken", activity_token},
                {"captchaToken", captcha_token},
                {"requestId", request},
                {"expiresAtMs", text(reply->element[1])}});
        }));
    server.Post(
        "/api/seckill/buy", wrap([this](auto &req, auto &out, auto &trace) {
          auto session = auth(req);
          auto input = body(req, {"activityId", "skuId", "requestId",
                                  "captchaToken", "activityToken"});
          std::string a = input["activityId"], s = input["skuId"],
                      request = input["requestId"],
                      captcha_token = input["captchaToken"],
                      activity_token = input["activityToken"];
          identifier(a);
          identifier(s);
          if (!uuid(request))
            throw ApiError(400, "INVALID_ARGUMENT");
          auto key = ledger(a, s);
          auto prior = redis().command(
              {"HGET", key, "req:" + session.user + ":" + request});
          checked(prior.get());
          try {
            if (prior->type != REDIS_REPLY_NIL) {
              durability_fence(key);
              ++counters.replayed;
              json(out, 200, status(text(prior.get()), request));
              return;
            }
            if (activity_token.size() != 101 || activity_token[36] != '.' ||
                !uuid(activity_token.substr(0, 36)) ||
                !hex64(activity_token.substr(37)) || !hex64(captcha_token))
              throw ApiError(403, "INVALID_PROOF");
            auto values = activity(a, s);
            auto registered =
                redis().command({"SADD", config.prefix + ":ledgers", key});
            checked(registered.get());
            auto reply = redis().eval(
                reserve_script,
                {key, challenge(a, s, activity_token.substr(0, 36)),
                 config.prefix + ":relay_ledgers", key + ":relay_pending"},
                {session.user, request, random_uuid(), values["epoch"], trace,
                 sha256(captcha_token), sha256(activity_token),
                 std::to_string(config.max_pending)});
            if (reply->type != REDIS_REPLY_ARRAY || reply->elements < 1)
              throw RedisFailure("Invalid reservation reply");
            auto code = text(reply->element[0]);
            if (code == "RESERVED" || code == "REPLAY") {
              if (code == "RESERVED")
                ++counters.reserved;
              durability_fence(key);
              auto output = status(text(reply->element[1]), request);
              output["statusUrl"] = "/api/order/status?activityId=" + a +
                                    "&skuId=" + s + "&requestId=" + request;
              if (code == "RESERVED")
                ++counters.accepted;
              else
                ++counters.replayed;
              json(out, code == "RESERVED" ? 202 : 200, output);
              return;
            }
            if (code == "INVALID_PROOF")
              throw ApiError(403, code);
            if (code == "BACKPRESSURE")
              throw ApiError(503, code);
            if (code == "NOT_READY")
              throw ApiError(503, code);
            if (code == "INVALID_ARGUMENT")
              throw ApiError(400, code);
            throw ApiError(409, code);
          } catch (const RedisFailure &) {
            ++counters.unknown;
            throw ApiError(503, "ACCEPTANCE_UNKNOWN");
          }
        }));
    server.Get(
        "/api/order/status", wrap([this](auto &req, auto &out, auto &) {
          auto session = auth(req);
          query_keys(req, {"activityId", "skuId", "requestId", "orderId"});
          if (req.has_param("orderId")) {
            if (req.params.size() != 1 || !uuid(query(req, "orderId")))
              throw ApiError(400, "INVALID_ARGUMENT");
            throw ApiError(503, "ORDER_SERVICE_UNAVAILABLE");
          }
          auto a = query(req, "activityId"), s = query(req, "skuId"),
               request = query(req, "requestId");
          identifier(a);
          identifier(s);
          if (!uuid(request))
            throw ApiError(400, "INVALID_ARGUMENT");
          auto r = redis().command(
              {"HGET", ledger(a, s), "req:" + session.user + ":" + request});
          checked(r.get());
          if (r->type == REDIS_REPLY_NIL)
            throw ApiError(404, "NOT_FOUND");
          json(out, 200, status(text(r.get()), request));
        }));
    server.Get(
        "/metrics", wrap([this](auto &req, auto &out, auto &) {
          if (auth(req).role != "ADMIN")
            throw ApiError(403, "FORBIDDEN");
          auto counter = [](const std::string &n, auto v) {
            return "# TYPE " + n + " counter\n" + n + " " + std::to_string(v) +
                   "\n";
          };
          out.set_content(
              counter("seckill_http_requests_total", counters.requests.load()) +
                  counter("seckill_http_errors_total", counters.errors.load()) +
                  counter("seckill_reserved_total", counters.reserved.load()) +
                  counter("seckill_accepted_total", counters.accepted.load()) +
                  counter("seckill_acceptance_unknown_total",
                          counters.unknown.load()) +
                  counter("seckill_replay_total", counters.replayed.load()) +
                  counter("seckill_rate_limited_total",
                          counters.limited.load()) +
                  counter("seckill_http_duration_microseconds_total",
                          counters.duration_us.load()),
              "text/plain; version=0.0.4");
        }));
  }
};
} // namespace
int serve(const Config &config) {
  sigset_t signals;
  sigemptyset(&signals);
  sigaddset(&signals, SIGINT);
  sigaddset(&signals, SIGTERM);
  pthread_sigmask(SIG_BLOCK, &signals, nullptr);
  httplib::Server server;
  Service service(config);
  server.new_task_queue = [&] {
    return new httplib::ThreadPool(config.workers, config.queue_limit);
  };
  server.set_payload_max_length(16 * 1024);
  server.set_read_timeout(3, 0);
  server.set_write_timeout(3, 0);
  server.set_keep_alive_max_count(16);
  server.set_keep_alive_timeout(2);
  server.set_error_handler([](const auto &, auto &out) {
    if (out.body.empty())
      json(out, out.status,
           {{"code", out.status == 413 ? "PAYLOAD_TOO_LARGE" : "HTTP_ERROR"},
            {"retryable", out.status >= 500}});
  });
  service.bind(server);
  if (!server.bind_to_port(config.host, config.port)) {
    std::cerr << "HTTP bind failed\n";
    return 2;
  }
  std::thread shutdown([&] {
    int signal = 0;
    sigwait(&signals, &signal);
    server.stop();
  });
  std::cout << "seckill HTTP listening " << config.host << ":" << config.port
            << "; RocketMQ adapter pending S3\n"
            << std::flush;
  auto ok = server.listen_after_bind();
  pthread_kill(shutdown.native_handle(), SIGTERM);
  shutdown.join();
  return ok ? 0 : 1;
}
} // namespace mall
