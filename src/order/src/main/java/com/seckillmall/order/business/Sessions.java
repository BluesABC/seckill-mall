package com.seckillmall.order.business;

import com.fasterxml.jackson.databind.JsonNode;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.*;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;

public final class Sessions {
  public record Identity(long userId, String role) {
    public void admin() {
      if (!role.equals("ADMIN"))
        throw new Fault(403, "FORBIDDEN");
    }
  }
  private final Store store;
  private final Cache cache;
  private final BCryptPasswordEncoder passwords = new BCryptPasswordEncoder(10);
  private final SecureRandom random = new SecureRandom();
  private final String dummy = passwords.encode("not-an-account-password");
  Sessions(Store store, Cache cache) {
    this.store = store;
    this.cache = cache;
  }
  public Map<String, Object> register(JsonNode body, String ip) {
    Input.fields(body, "username", "password");
    String name = name(body), password = password(body);
    limit("register:" + Cache.hash(ip), 15);
    String encoded = passwords.encode(password);
    long id = store.insert("INSERT INTO users(username,password_hash,created_at_ms) VALUES(?,?,?)",
        name, encoded, store.now());
    return Map.of("userId", Long.toString(id), "username", name, "role", "USER");
  }
  public Map<String, Object> login(JsonNode body, String ip) {
    Input.fields(body, "username", "password");
    String name = name(body), password = password(body);
    limit("login-ip:" + Cache.hash(ip), 80);
    limit("login-user:" + Cache.hash(name.toLowerCase(Locale.ROOT)), 30);
    return store.transaction(() -> {
      Map<String, Object> user = store.one("SELECT * FROM users WHERE username=? FOR UPDATE", name);
      boolean valid =
          passwords.matches(password, user == null ? dummy : user.get("password_hash").toString());
      if (user == null || !valid || !Store.flag(user, "enabled"))
        throw new Fault(401, "UNAUTHENTICATED");
      long id = Store.number(user, "id"), expires = store.now() + 7200000;
      byte[] bytes = new byte[32];
      random.nextBytes(bytes);
      String token = HexFormat.of().formatHex(bytes), digest = Cache.hash(token);
      String script = "redis.call('HSET',KEYS[1],'userId',ARGV[1],'role',ARGV[2],'expiresAtMs',"
                      + "ARGV[3]);redis.call('PEXPIREAT',KEYS[1],ARGV[3]);redis.call('SADD',ARGV[4]"
                      + ",ARGV[5]);redis.call('PEXPIREAT',ARGV[4],ARGV[3]);return {'CREATED'}";
      cache.eval(script, cache.prefix + ":session:" + digest, Long.toString(id),
          user.get("role").toString(), Long.toString(expires),
          cache.prefix + ":user-sessions:" + id, digest);
      return Map.of("token", token, "expiresAtMs", Long.toString(expires), "userId",
          Long.toString(id), "role", user.get("role"));
    });
  }
  public Identity auth(String authorization) {
    String token = token(authorization);
    Map<Object, Object> session =
        cache.redis.opsForHash().entries(cache.prefix + ":session:" + Cache.hash(token));
    if (session.isEmpty())
      throw new Fault(401, "UNAUTHENTICATED");
    try {
      long id = Input.id(session.get("userId").toString()),
           expires = Long.parseLong(session.get("expiresAtMs").toString());
      Map<String, Object> user = store.one("SELECT role,enabled FROM users WHERE id=?", id);
      if (expires <= store.now() || user == null || !Store.flag(user, "enabled")
          || !user.get("role").equals(session.get("role")))
        throw new Fault(401, "UNAUTHENTICATED");
      return new Identity(id, user.get("role").toString());
    } catch (NullPointerException | NumberFormatException e) {
      throw new Fault(401, "UNAUTHENTICATED");
    }
  }
  public void logout(String authorization) {
    cache.redis.delete(cache.prefix + ":session:" + Cache.hash(token(authorization)));
  }
  public void enable(Identity admin, long user, boolean enabled) {
    admin.admin();
    if (user == admin.userId() && !enabled)
      throw new Fault(409, "SELF_DISABLE_FORBIDDEN");
    store.transaction(() -> {
      if (store.one("SELECT id FROM users WHERE id=? FOR UPDATE", user) == null)
        throw new Fault(404, "NOT_FOUND");
      if (!enabled) {
        String index = cache.prefix + ":user-sessions:" + user;
        cache.eval(
            "local hashes=redis.call('SMEMBERS',KEYS[1]);for _,h in ipairs(hashes) do "
            + "redis.call('DEL',ARGV[1]..h) end;redis.call('DEL',KEYS[1]);return {'REVOKED'}",
            index, cache.prefix + ":session:");
      }
      store.db.update("UPDATE users SET enabled=? WHERE id=?", enabled, user);
      return null;
    });
  }
  public void bootstrap() {
    String name = System.getenv("MALL_ADMIN_USERNAME"),
           password = System.getenv("MALL_ADMIN_PASSWORD");
    if (name == null && password == null)
      return;
    if (name == null || !name.matches("[A-Za-z0-9_-]{3,64}") || password == null
        || password.length() < 12 || password.getBytes(StandardCharsets.UTF_8).length > 72)
      throw new IllegalArgumentException("Invalid admin bootstrap configuration");
    store.transaction(() -> {
      var existing = store.one("SELECT role FROM users WHERE username=? FOR UPDATE", name);
      if (existing != null) {
        if (!existing.get("role").equals("ADMIN"))
          throw new IllegalStateException("Admin username already used");
        return null;
      }
      store.db.update(
          "INSERT INTO users(username,password_hash,role,created_at_ms) VALUES(?,?,'ADMIN',?)",
          name, passwords.encode(password), store.now());
      return null;
    });
  }
  private void limit(String key, int maximum) {
    var reply = cache.eval("local n=redis.call('INCR',KEYS[1]);if n==1 then "
                           + "redis.call('PEXPIRE',KEYS[1],600000) end;return {tostring(n)}",
        cache.prefix + ":auth-limit:" + key);
    if (Integer.parseInt(reply.get(0)) > maximum)
      throw new Fault(429, "RATE_LIMITED");
  }
  private static String token(String header) {
    if (header == null || !header.matches("Bearer [0-9a-f]{64}"))
      throw new Fault(401, "UNAUTHENTICATED");
    return header.substring(7);
  }
  private static String name(JsonNode b) {
    String n = Input.text(b, "username", 3, 64);
    if (!n.matches("[A-Za-z0-9_-]+"))
      throw new Fault(400, "INVALID_ARGUMENT");
    return n;
  }
  private static String password(JsonNode b) {
    String p = Input.text(b, "password", 12, 72);
    if (p.getBytes(StandardCharsets.UTF_8).length > 72)
      throw new Fault(400, "INVALID_ARGUMENT");
    return p;
  }
}
