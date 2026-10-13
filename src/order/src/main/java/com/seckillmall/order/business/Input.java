package com.seckillmall.order.business;
import com.fasterxml.jackson.databind.JsonNode;
import java.util.*;
public final class Input {
  private Input() {}
  public static void fields(JsonNode n, String... fields) {
    if (n == null || !n.isObject())
      throw new Fault(400, "INVALID_ARGUMENT");
    Set<String> expected = Set.of(fields);
    n.fieldNames().forEachRemaining(k -> {
      if (!expected.contains(k))
        throw new Fault(400, "INVALID_ARGUMENT");
    });
    for (String k : fields)
      if (!n.hasNonNull(k))
        throw new Fault(400, "INVALID_ARGUMENT");
  }
  public static String text(JsonNode n, String k, int min, int max) {
    if (!n.path(k).isTextual())
      throw new Fault(400, "INVALID_ARGUMENT");
    String v = n.get(k).textValue();
    if (v.length() < min || v.length() > max)
      throw new Fault(400, "INVALID_ARGUMENT");
    return v;
  }
  public static long id(String value) {
    if (value == null || !value.matches("[1-9][0-9]{0,18}"))
      throw new Fault(400, "INVALID_ARGUMENT");
    try {
      return Long.parseLong(value);
    } catch (NumberFormatException e) {
      throw new Fault(400, "INVALID_ARGUMENT");
    }
  }
  public static long id(JsonNode n, String k) {
    return id(text(n, k, 1, 19));
  }
  public static String uuid(String v) {
    if (v == null || !v.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"))
      throw new Fault(400, "INVALID_ARGUMENT");
    return v;
  }
  public static int stock(JsonNode n, String k) {
    long v = id(n, k);
    if (v > 100000000)
      throw new Fault(400, "INVALID_ARGUMENT");
    return (int) v;
  }
}
