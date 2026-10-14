package com.seckillmall.order.business;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.*;

public final class Catalog {
  private final Store store;
  private final Cache cache;
  Catalog(Store store, Cache cache) {
    this.store = store;
    this.cache = cache;
  }
  public List<Map<String, Object>> products() {
    return store.db
        .queryForList(
            "SELECT g.id AS goodsId,g.title,g.description,g.image_url AS imageUrl,s.id AS "
            + "skuId,s.size_eu AS sizeEu,s.category,s.colorway,s.price_fen AS priceFen,s.unallocated_stock AS unallocatedStock FROM goods g "
            + "JOIN skus s ON s.goods_id=g.id WHERE g.enabled=1 ORDER BY g.id DESC,s.id ASC LIMIT 100")
        .stream()
        .map(Store::wire)
        .toList();
  }
  public Map<String, Object> productPage(
      String query, String category, String maxPriceFen, String sort, String pageText,
      String sizeText) {
    if (query.length() > 80 || !Set.of("", "跑步", "篮球", "休闲", "训练").contains(category)
        || !Set.of("featured", "low", "high").contains(sort))
      throw new Fault(400, "INVALID_ARGUMENT");
    long page = pageText == null ? 0 : pageIndex(pageText);
    long size = sizeText == null ? 12 : Input.id(sizeText);
    if (page > 1_000_000 || size > 48)
      throw new Fault(400, "INVALID_ARGUMENT");
    long maxPrice = maxPriceFen == null || maxPriceFen.isEmpty()
        ? 0 : Input.id(maxPriceFen);
    long offset = page * size;
    StringBuilder filters = new StringBuilder("WHERE g.enabled=1");
    List<Object> args = new ArrayList<>();
    if (!category.isEmpty()) {
      filters.append(" AND s.category=?");
      args.add(category);
    }
    if (maxPrice > 0) {
      filters.append(" AND s.price_fen<=?");
      args.add(maxPrice);
    }
    if (!query.isEmpty()) {
      String pattern = "%" + query.replace("\\", "\\\\")
                             .replace("%", "\\%")
                             .replace("_", "\\_") + "%";
      filters.append(" AND (g.title LIKE ? OR g.description LIKE ?)");
      args.add(pattern);
      args.add(pattern);
    }
    Object[] params = args.toArray();
    long total = store.db.queryForObject(
        "SELECT COUNT(*) FROM goods g JOIN skus s ON s.id=(SELECT MIN(s2.id) FROM skus s2 "
        + "WHERE s2.goods_id=g.id) " + filters, Long.class, params);
    String ordering = switch (sort) {
      case "low" -> "ORDER BY s.price_fen ASC,g.id DESC";
      case "high" -> "ORDER BY s.price_fen DESC,g.id DESC";
      default -> "ORDER BY g.id DESC";
    };
    var items = store.db.queryForList(
            "SELECT g.id AS goodsId,g.title,g.description,g.image_url AS imageUrl,s.id AS skuId,"
            + "s.size_eu AS sizeEu,s.category,s.colorway,s.price_fen AS priceFen,s.unallocated_stock "
            + "AS unallocatedStock FROM goods g JOIN skus s ON s.id=(SELECT MIN(s2.id) FROM "
            + "skus s2 WHERE s2.goods_id=g.id) " + filters + " " + ordering + " LIMIT ? OFFSET ?",
            concat(params, size, offset))
        .stream().map(Store::wire).toList();
    return Map.of("items", items, "page", page, "size", size, "total", total,
        "hasMore", offset + items.size() < total);
  }
  private static Object[] concat(Object[] values, Object... extra) {
    Object[] all = Arrays.copyOf(values, values.length + extra.length);
    System.arraycopy(extra, 0, all, values.length, extra.length);
    return all;
  }
  private static long pageIndex(String value) {
    if (value == null || !value.matches("0|[1-9][0-9]{0,6}"))
      throw new Fault(400, "INVALID_ARGUMENT");
    return Long.parseLong(value);
  }
  public Map<String, Object> product(long id) {
    var rows =
        store.db.queryForList("SELECT g.id AS goodsId,g.title,g.description,g.image_url AS "
                              + "imageUrl,s.id AS skuId,s.size_eu AS sizeEu,s.category,s.colorway,s.price_fen AS priceFen FROM goods g JOIN "
                              + "skus s ON s.goods_id=g.id WHERE g.id=? AND g.enabled=1 ORDER BY s.id",
            id);
    if (rows.isEmpty())
      throw new Fault(404, "NOT_FOUND");
    return Map.of("items", rows.stream().map(Store::wire).toList());
  }
  public List<Map<String, Object>> activities() {
    return store.db
        .queryForList(
            "SELECT a.id AS activityId,a.name,a.status,a.starts_at_ms AS startsAtMs,a.ends_at_ms "
            + "AS endsAtMs,s.sku_id AS skuId,s.price_fen AS priceFen,s.available_stock AS "
            + "availableStock,s.initial_stock AS initialStock,g.title,g.image_url AS imageUrl FROM activities a JOIN "
            + "activity_stock s ON s.activity_id=a.id JOIN skus k ON k.id=s.sku_id JOIN goods g ON "
            + "g.id=k.goods_id WHERE a.status IN ('READY','ACTIVE','ENDED') AND g.enabled=1 ORDER "
            + "BY a.starts_at_ms DESC LIMIT 100")
        .stream()
        .map(Store::wire)
        .toList();
  }
  public Map<String, Object> createProduct(JsonNode b) {
    Input.fields(b, "title", "description", "imageUrl", "priceFen", "stock");
    String title = Input.text(b, "title", 1, 200),
           description = Input.text(b, "description", 0, 10000),
           image = Input.text(b, "imageUrl", 0, 512);
    image(image);
    long price = Input.id(b, "priceFen");
    int stock = Input.stock(b, "stock");
    return store.transaction(() -> {
      long goods = store.insert("INSERT INTO goods(title,description,image_url) VALUES(?,?,?)",
          title, description, image);
      long sku =
          store.insert("INSERT INTO skus(goods_id,price_fen,unallocated_stock) VALUES(?,?,?)",
              goods, price, stock);
      return Map.of("goodsId", Long.toString(goods), "skuId", Long.toString(sku));
    });
  }
  public Map<String, Object> createSku(long goodsId, JsonNode b) {
    Input.fields(b, "sizeEu", "stock");
    String size = Input.text(b, "sizeEu", 1, 8);
    if (!size.matches("(?:3[5-9]|4[0-9]|50)(?:\\.5)?"))
      throw new Fault(400, "INVALID_ARGUMENT");
    int stock = Input.stock(b, "stock");
    return store.transaction(() -> {
      if (store.one("SELECT id FROM goods WHERE id=? FOR UPDATE", goodsId) == null)
        throw new Fault(404, "NOT_FOUND");
      if (store.db.queryForObject(
              "SELECT COUNT(*) FROM skus WHERE goods_id=? AND size_eu=?", Long.class,
              goodsId, size) > 0)
        throw new Fault(409, "SKU_SIZE_EXISTS");
      var base = store.one(
          "SELECT price_fen,category,colorway FROM skus WHERE goods_id=? ORDER BY id LIMIT 1",
          goodsId);
      if (base == null)
        throw new Fault(404, "NOT_FOUND");
      long sku = store.insert(
          "INSERT INTO skus(goods_id,price_fen,unallocated_stock,size_eu,category,colorway) "
          + "VALUES(?,?,?,?,?,?)", goodsId, base.get("price_fen"), stock, size,
          base.get("category"), base.get("colorway"));
      return Map.of("goodsId", Long.toString(goodsId), "skuId", Long.toString(sku),
          "sizeEu", size, "unallocatedStock", Integer.toString(stock));
    });
  }
  public void updateProduct(long id, JsonNode b) {
    Input.fields(b, "title", "description", "imageUrl", "enabled");
    if (!b.get("enabled").isBoolean())
      throw new Fault(400, "INVALID_ARGUMENT");
    String image = Input.text(b, "imageUrl", 0, 512);
    image(image);
    if (store.db.update("UPDATE goods SET title=?,description=?,image_url=?,enabled=? WHERE id=?",
            Input.text(b, "title", 1, 200), Input.text(b, "description", 0, 10000), image,
            b.get("enabled").booleanValue(), id)
        != 1)
      throw new Fault(404, "NOT_FOUND");
  }
  public Map<String, Object> createActivity(JsonNode b) {
    Input.fields(b, "name", "skuId", "stock", "priceFen", "startsAtMs", "endsAtMs");
    long sku = Input.id(b, "skuId"), price = Input.id(b, "priceFen"),
         starts = Input.id(b, "startsAtMs"), ends = Input.id(b, "endsAtMs");
    int stock = Input.stock(b, "stock");
    if (ends <= starts)
      throw new Fault(400, "INVALID_ARGUMENT");
    return store.transaction(() -> {
      var s = store.one("SELECT s.*,g.enabled FROM skus s JOIN goods g ON g.id=s.goods_id WHERE "
                        + "s.id=? FOR UPDATE",
          sku);
      if (s == null || !Store.flag(s, "enabled"))
        throw new Fault(404, "NOT_FOUND");
      if (price > Store.number(s, "price_fen") || ends <= store.now())
        throw new Fault(400, "INVALID_ARGUMENT");
      if (store.db.update("UPDATE skus SET unallocated_stock=unallocated_stock-?,version=version+1 "
                          + "WHERE id=? AND unallocated_stock>=?",
              stock, sku, stock)
          != 1)
        throw new Fault(409, "INSUFFICIENT_STOCK");
      long activity = store.insert(
          "INSERT INTO activities(name,starts_at_ms,ends_at_ms,status) VALUES(?,?,?,'READY')",
          Input.text(b, "name", 1, 200), starts, ends);
      store.db.update(
          "INSERT INTO activity_stock VALUES(?,?,?,?,?,1,0)", activity, sku, stock, stock, price);
      return Map.of(
          "activityId", Long.toString(activity), "skuId", Long.toString(sku), "status", "READY");
    });
  }
  public void activate(long activity, long sku) {
    store.transaction(() -> {
      var row = store.one(
          "SELECT s.*,a.status,a.starts_at_ms,a.ends_at_ms FROM activity_stock s JOIN activities a "
          + "ON a.id=s.activity_id WHERE s.activity_id=? AND s.sku_id=? FOR UPDATE",
          activity, sku);
      if (row == null)
        throw new Fault(404, "NOT_FOUND");
      String status = row.get("status").toString();
      if (!Set.of("READY", "ACTIVE").contains(status)
          || Store.number(row, "ends_at_ms") <= store.now())
        throw new Fault(409, "ACTIVITY_CONFLICT");
      String key = cache.ledger(activity, sku);
      if ("READY".equals(status)) {
        if (Store.number(row, "available_stock") != Store.number(row, "initial_stock")
            || store.db.queryForObject(
                   "SELECT COUNT(*) FROM seckill_requests WHERE activity_id=? AND sku_id=?",
                   Long.class, activity, sku)
                > 0)
          throw new Fault(409, "ACTIVITY_CONFLICT");
        cache.lua("preload", key, row.get("initial_stock").toString(),
            row.get("starts_at_ms").toString(), row.get("ends_at_ms").toString(), "READY",
            row.get("epoch").toString(), row.get("price_fen").toString(), Long.toString(activity),
            Long.toString(sku));
      }
      for (String[] pair :
          List.of(new String[] {"epoch", "epoch"}, new String[] {"initialStock", "initial_stock"},
              new String[] {"priceFen", "price_fen"}, new String[] {"startsAtMs", "starts_at_ms"},
              new String[] {"endsAtMs", "ends_at_ms"})) {
        if (!Objects.equals(
                cache.redis.opsForHash().get(key, pair[0]), row.get(pair[1]).toString()))
          throw new Fault(409, "CACHE_CONFLICT");
      }
      cache.redis.opsForSet().add(cache.prefix + ":ledgers", key);
      store.db.update(
          "UPDATE activities SET status='ACTIVE' WHERE id=? AND status='READY'", activity);
      return null;
    });
    // DB commit precedes exposure to buyers. Retry repairs a crash between these steps.
    var row = store.one("SELECT s.epoch,a.status FROM activity_stock s JOIN activities a ON "
                        + "a.id=s.activity_id WHERE activity_id=? AND sku_id=?",
        activity, sku);
    if (!"ACTIVE".equals(row.get("status")))
      throw new Fault(409, "ACTIVITY_CONFLICT");
    var result = cache.eval(
        "if redis.call('HGET',KEYS[1],'epoch')~=ARGV[1] then return {'STALE_EPOCH'} end;local "
        + "s=redis.call('HGET',KEYS[1],'status');if s~='READY' and s~='ACTIVE' then return "
        + "{'STATE_CONFLICT'} end;redis.call('HSET',KEYS[1],'status','ACTIVE');return {'ACTIVE'}",
        cache.ledger(activity, sku), row.get("epoch").toString());
    if (!result.get(0).equals("ACTIVE"))
      throw new Fault(409, "CACHE_CONFLICT");
  }
  public void end(long activity, long sku) {
    store.transaction(() -> {
      var row = store.one(
          "SELECT s.epoch FROM activity_stock s WHERE activity_id=? AND sku_id=? FOR UPDATE",
          activity, sku);
      if (row == null)
        throw new Fault(404, "NOT_FOUND");
      store.db.update(
          "UPDATE activities SET status='ENDED' WHERE id=? AND status IN ('ACTIVE','READY')",
          activity);
      return null;
    });
    cache.eval("if redis.call('EXISTS',KEYS[1])==0 then return {'NOT_FOUND'} "
               + "end;redis.call('HSET',KEYS[1],'status','ENDED');return {'ENDED'}",
        cache.ledger(activity, sku));
  }
  private static void image(String s) {
    if (!s.isEmpty() && !s.matches("/assets/[A-Za-z0-9_./-]+"))
      throw new Fault(400, "INVALID_ARGUMENT");
    if (s.contains(".."))
      throw new Fault(400, "INVALID_ARGUMENT");
  }
}
