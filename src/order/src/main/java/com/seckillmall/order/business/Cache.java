package com.seckillmall.order.business;

import com.fasterxml.jackson.databind.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import org.springframework.data.redis.connection.ReturnType;
import org.springframework.data.redis.core.*;

public final class Cache {
  public final StringRedisTemplate redis;
  public final ObjectMapper mapper;
  public final String prefix;
  private final Map<String, byte[]> scripts = new HashMap<>();
  Cache(StringRedisTemplate redis, ObjectMapper mapper, String prefix, String directory) {
    if (!prefix.matches("[A-Za-z0-9_-]{1,64}"))
      throw new IllegalArgumentException("Invalid prefix");
    this.redis = redis;
    this.mapper = mapper;
    this.prefix = prefix;
    for (String name : List.of("preload", "mark_request", "mark_order", "release")) {
      try {
        scripts.put(name, Files.readAllBytes(Path.of(directory, name + ".lua")));
      } catch (Exception e) {
        throw new IllegalStateException("Missing Lua " + name, e);
      }
    }
  }
  public String ledger(long a, long sku) {
    return prefix + ":{" + a + ":" + sku + "}:ledger";
  }
  public JsonNode json(String value) {
    try {
      return mapper.readTree(value);
    } catch (Exception e) {
      throw new Fault(400, "INVALID_ARGUMENT");
    }
  }
  public String encode(Object value) {
    try {
      return mapper.writeValueAsString(value);
    } catch (Exception e) {
      throw new IllegalStateException(e);
    }
  }
  public static String hash(String value) {
    try {
      return HexFormat.of().formatHex(
          MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
    } catch (Exception e) {
      throw new IllegalStateException(e);
    }
  }
  public List<String> lua(String name, String key, String... args) {
    return eval(scripts.get(name), List.of(key), args);
  }
  public List<String> lua(String name, List<String> keys, String... args) {
    return eval(scripts.get(name), keys, args);
  }
  public List<String> eval(String script, String key, String... args) {
    return eval(script.getBytes(StandardCharsets.UTF_8), List.of(key), args);
  }
  private List<String> eval(byte[] script, List<String> keys, String... args) {
    return redis.execute((RedisCallback<List<String>>) connection -> {
      byte[][] values = new byte[args.length + keys.size()][];
      for (int i = 0; i < keys.size(); i++)
        values[i] = keys.get(i).getBytes(StandardCharsets.UTF_8);
      for (int i = 0; i < args.length; i++)
        values[keys.size() + i] = args[i].getBytes(StandardCharsets.UTF_8);
      List<?> result = connection.scriptingCommands().eval(
          script, ReturnType.MULTI, keys.size(), values);
      // Same connection causal fence: a successful EVAL may be a read-only replay.
      connection.hashCommands().hSet((prefix + ":durability").getBytes(StandardCharsets.UTF_8),
          "fence".getBytes(StandardCharsets.UTF_8),
          UUID.randomUUID().toString().getBytes(StandardCharsets.UTF_8));
      org.springframework.data.redis.connection.RedisConnection raw = connection;
      if (raw
          instanceof org.springframework.data.redis.connection.DefaultStringRedisConnection strings)
        raw = strings.getDelegate();
      if (!(raw
              instanceof org.springframework.data.redis.connection.lettuce
                             .LettuceConnection lettuce))
        throw new IllegalStateException("Lettuce connection required");
      Object barrier = lettuce.execute("WAITAOF",
          new io.lettuce.core.output.ArrayOutput<>(io.lettuce.core.codec.ByteArrayCodec.INSTANCE),
          "1".getBytes(), "0".getBytes(), "2000".getBytes());
      if (!(barrier instanceof List<?> list) || list.isEmpty()
          || ((Number) list.get(0)).longValue() < 1)
        throw new Fault(503, "DEPENDENCY_UNAVAILABLE");
      return result.stream()
          .map(v
              -> v instanceof byte[] b ? new String(b, StandardCharsets.UTF_8) : String.valueOf(v))
          .toList();
    }, true);
  }
  public JsonNode request(long a, long sku, long user, String request) {
    Object raw = redis.opsForHash().get(ledger(a, sku), "req:" + user + ":" + request);
    return raw == null ? null : json(raw.toString());
  }
}
