package com.seckillmall.order.business;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.*;

public final class Orders {
  private final Store store;
  private final Cache cache;
  private final long ttl;
  Orders(Store store, Cache cache, long ttl) {
    if (ttl < 100 || ttl > 86400000)
      throw new IllegalArgumentException("Payment TTL out of range");
    this.store = store;
    this.cache = cache;
    this.ttl = ttl;
  }
  public void accept(ReservedEvent event) {
    store.transaction(() -> {
      consumeLocked(event, false, "ORDER_FAILED");
      return null;
    });
  }
  public void terminate(ReservedEvent event, String reason) {
    store.transaction(() -> {
      consumeLocked(event, true, reason);
      return null;
    });
  }
  private void consumeLocked(ReservedEvent e, boolean terminate, String failure) {
    // Read immutable campaign facts without taking the hot inventory-row lock.
    // The conditional UPDATE below is the serialization point: it rechecks both
    // epoch and available_stock after acquiring InnoDB's row lock. This keeps
    // Redis and idempotency reads out of the per-SKU critical section.
    var stock = stockSnapshot(e.activityId(), e.skuId());
    if (stock == null)
      throw new Fault(404, "UNKNOWN_ACTIVITY");
    // This row is usually absent on first delivery. FOR UPDATE would take a
    // next-key/gap lock for the missing random primary key and make unrelated
    // reservations contend or deadlock under REPEATABLE READ. The unique key
    // remains the serialization point for concurrent redelivery of this event.
    var existing = store.one(
        "SELECT * FROM seckill_requests WHERE reservation_id=?", e.reservationId());
    if (existing != null) {
      same(existing, e);
      return;
    }
    var conflict = store.one("SELECT reservation_id FROM seckill_requests WHERE activity_id=? AND "
                             + "sku_id=? AND user_id=? AND request_id=?",
        e.activityId(), e.skuId(), e.userId(), e.requestId());
    if (conflict != null)
      throw new Fault(409, "REQUEST_CONFLICT");
    origin(e);
    if (store.one("SELECT id FROM users WHERE id=?", e.userId()) == null)
      throw new Fault(404, "UNKNOWN_USER");
    String reason = terminate ? failure : null;
    if (e.epoch() != Store.number(stock, "epoch"))
      reason = "STALE_EPOCH";
    if (e.priceFen() != Store.number(stock, "price_fen"))
      reason = "PRICE_CONFLICT";
    if (e.createdAtMs() < Store.number(stock, "starts_at_ms")
        || e.createdAtMs() >= Store.number(stock, "ends_at_ms"))
      reason = "INVALID_RESERVATION_TIME";
    if (store.one("SELECT id FROM orders WHERE activity_id=? AND sku_id=? AND user_id=?",
            e.activityId(), e.skuId(), e.userId())
        != null)
      reason = "ALREADY_PURCHASED";
    if (Store.number(stock, "available_stock") < 1)
      reason = "SOLD_OUT";
    // Acquire the inventory row's exclusive lock before inserting the request
    // row whose FK references it. Otherwise concurrent transactions can each
    // hold the FK's shared parent lock and deadlock while upgrading to UPDATE.
    // This remains in the same transaction, so any later failure rolls the
    // stock decrement back with the request/order writes.
    if (reason == null
        && store.db.update(
                "UPDATE activity_stock SET available_stock=available_stock-1,version=version+1 "
                + "WHERE activity_id=? AND sku_id=? AND epoch=? AND available_stock>0",
                e.activityId(), e.skuId(), e.epoch())
            != 1)
      throw new IllegalStateException("Stock conditional update failed");
    store.db.update("INSERT INTO "
                    + "seckill_requests(reservation_id,request_id,activity_id,sku_id,user_id,epoch,"
                    + "price_fen,status,created_at_ms,failure_code) VALUES(?,?,?,?,?,?,?, ?,?,?)",
        e.reservationId(), e.requestId(), e.activityId(), e.skuId(), e.userId(), e.epoch(),
        e.priceFen(), reason == null ? "QUEUED" : "COMPENSATING", e.createdAtMs(), reason);
    if (reason != null) {
      outbox(e.reservationId(), "RESERVATION_RELEASE");
      return;
    }
    long now = store.now();
    store.db.update("INSERT INTO "
                    + "orders(id,reservation_id,activity_id,sku_id,user_id,amount_fen,status,"
                    + "created_at_ms,expires_at_ms) VALUES(?,?,?,?,?,?,'PENDING_PAYMENT',?,?)",
        UUID.randomUUID().toString(), e.reservationId(), e.activityId(), e.skuId(), e.userId(),
        e.priceFen(), now, Math.addExact(now, ttl));
    store.db.update("UPDATE seckill_requests SET status='ORDER_CREATED' WHERE reservation_id=?",
        e.reservationId());
    outbox(e.reservationId(), "ORDER_CREATED");
  }
  private void origin(ReservedEvent e) {
    String key = cache.ledger(e.activityId(), e.skuId());
    // All origin facts belong to one ledger. Read them atomically in one
    // bounded HMGET instead of four network round trips inside the DB txn.
    var facts = cache.redis.opsForHash().multiGet(key,
        List.of("req:" + e.userId() + ":" + e.requestId(), "user:" + e.userId(),
            "epoch", "priceFen"));
    JsonNode req = facts.get(0) == null ? null : cache.json(facts.get(0).toString());
    if (req == null || !e.reservationId().equals(req.path("reservationId").asText())
        || !Long.toString(e.createdAtMs()).equals(req.path("createdAtMs").asText())
        || !e.reservationId().equals(facts.get(1))
        || !Long.toString(e.epoch()).equals(facts.get(2))
        || !Long.toString(e.priceFen()).equals(facts.get(3)))
      throw new Fault(409, "RESERVATION_CONFLICT");
    if (!Set.of("RESERVED", "QUEUED").contains(req.path("state").asText())
        || req.path("released").asBoolean())
      throw new Fault(409, "STATE_CONFLICT");
  }
  private static void same(Map<String, Object> row, ReservedEvent e) {
    if (!row.get("request_id").equals(e.requestId())
        || Store.number(row, "activity_id") != e.activityId()
        || Store.number(row, "sku_id") != e.skuId() || Store.number(row, "user_id") != e.userId()
        || Store.number(row, "epoch") != e.epoch() || Store.number(row, "price_fen") != e.priceFen()
        || Store.number(row, "created_at_ms") != e.createdAtMs())
      throw new Fault(409, "REQUEST_CONFLICT");
  }
  Map<String, Object> stock(long activity, long sku) {
    return store.one(
        "SELECT s.*,a.starts_at_ms,a.ends_at_ms,a.status AS activity_status FROM activity_stock s "
        + "JOIN activities a ON a.id=s.activity_id WHERE s.activity_id=? AND s.sku_id=? FOR UPDATE",
        activity, sku);
  }
  private Map<String, Object> stockSnapshot(long activity, long sku) {
    return store.one(
        "SELECT s.*,a.starts_at_ms,a.ends_at_ms,a.status AS activity_status FROM activity_stock s "
        + "JOIN activities a ON a.id=s.activity_id WHERE s.activity_id=? AND s.sku_id=?",
        activity, sku);
  }
  private void outbox(String reservation, String kind) {
    store.db.update("INSERT INTO "
                    + "outbox_events(event_id,reservation_id,kind,payload,next_attempt_at_ms,"
                    + "created_at_ms) VALUES(?,?,?,JSON_OBJECT('reservationId',?,'kind',?),?,?) ON "
                    + "DUPLICATE KEY UPDATE event_id=event_id",
        UUID.randomUUID().toString(), reservation, kind, reservation, kind, store.now(),
        store.now());
  }
  public Map<String, Object> query(
      long user, String orderId, Long activity, Long sku, String request) {
    String where;
    Object[] args;
    if (orderId != null) {
      Input.uuid(orderId);
      if (activity != null || sku != null || request != null)
        throw new Fault(400, "INVALID_ARGUMENT");
      where = "o.id=? AND r.user_id=?";
      args = new Object[] {orderId, user};
    } else {
      if (activity == null || sku == null || request == null)
        throw new Fault(400, "INVALID_ARGUMENT");
      Input.uuid(request);
      where = "r.activity_id=? AND r.sku_id=? AND r.request_id=? AND r.user_id=?";
      args = new Object[] {activity, sku, request, user};
    }
    var row = store.one(
        "SELECT r.request_id AS requestId,r.reservation_id AS reservationId,r.status AS "
        + "requestState,r.failure_code AS failureCode,o.id AS orderId,o.status AS "
        + "orderState,o.amount_fen AS amountFen,o.expires_at_ms AS expiresAtMs FROM "
        + "seckill_requests r LEFT JOIN orders o ON o.reservation_id=r.reservation_id WHERE "
            + where,
        args);
    if (row != null)
      return Store.wire(row);
    if (orderId == null) {
      JsonNode req = cache.request(activity, sku, user, request);
      if (req != null) {
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("requestId", request);
        response.put("reservationId", req.path("reservationId").asText());
        response.put("requestState", req.path("state").asText());
        for (String k : List.of("orderId", "orderState", "amountFen", "expiresAtMs", "failureCode"))
          response.put(k, null);
        return response;
      }
    }
    throw new Fault(404, "NOT_FOUND");
  }
  public List<Map<String, Object>> list(long user) {
    return store.db
        .queryForList(
            "SELECT id AS orderId,status AS orderState,amount_fen AS amountFen,expires_at_ms AS "
            + "expiresAtMs,created_at_ms AS createdAtMs,sku_id AS skuId FROM orders WHERE "
            + "user_id=? ORDER BY created_at_ms DESC LIMIT 100",
            user)
        .stream()
        .map(Store::wire)
        .toList();
  }
  public Map<String, Object> pay(long user, JsonNode b) {
    Input.fields(b, "orderId", "idempotencyKey");
    String id = Input.uuid(Input.text(b, "orderId", 36, 36)),
           retry = Input.uuid(Input.text(b, "idempotencyKey", 36, 36));
    var seed =
        store.one("SELECT activity_id,sku_id FROM orders WHERE id=? AND user_id=?", id, user);
    if (seed == null)
      throw new Fault(404, "NOT_FOUND");
    return store.transaction(() -> {
      stock(Store.number(seed, "activity_id"), Store.number(seed, "sku_id"));
      var order = store.one("SELECT * FROM orders WHERE id=? AND user_id=? FOR UPDATE", id, user);
      var prior = store.one("SELECT id FROM payments WHERE order_id=?", id);
      if ("PAID".equals(order.get("status")) && prior != null)
        return payment(id, prior.get("id").toString());
      long now = store.now();
      if (!"PENDING_PAYMENT".equals(order.get("status"))
          || Store.number(order, "expires_at_ms") <= now)
        throw new Fault(409, "ORDER_CLOSED");
      if (store.db.update("UPDATE orders SET status='PAID',version=version+1 WHERE id=? AND "
                          + "status='PENDING_PAYMENT' AND expires_at_ms>?",
              id, now)
          != 1)
        throw new Fault(409, "ORDER_CLOSED");
      String payment = UUID.randomUUID().toString();
      store.db.update("INSERT INTO "
                      + "payments(id,order_id,idempotency_key,amount_fen,status,provider,provider_"
                      + "transaction_id,created_at_ms) VALUES(?,?,?,?,'SUCCEEDED','MOCK',?,?)",
          payment, id, retry, order.get("amount_fen"), payment, now);
      outbox(order.get("reservation_id").toString(), "ORDER_PAID");
      return payment(id, payment);
    });
  }
  private static Map<String, Object> payment(String order, String payment) {
    return Map.of("orderId", order, "paymentId", payment, "orderState", "PAID", "provider", "MOCK");
  }
  public void closeExpired() {
    var due = store.db.queryForList(
        "SELECT id,activity_id,sku_id FROM orders WHERE status='PENDING_PAYMENT' AND "
        + "expires_at_ms<=? ORDER BY expires_at_ms LIMIT 100",
        store.now());
    for (var candidate : due)
      store.transaction(() -> {
        stock(Store.number(candidate, "activity_id"), Store.number(candidate, "sku_id"));
        var order = store.one("SELECT * FROM orders WHERE id=? FOR UPDATE", candidate.get("id"));
        if (!"PENDING_PAYMENT".equals(order.get("status"))
            || Store.number(order, "expires_at_ms") > store.now())
          return null;
        if (store.db.update("UPDATE orders SET status='CLOSED',version=version+1 WHERE id=? AND "
                            + "status='PENDING_PAYMENT' AND expires_at_ms<=?",
                order.get("id"), store.now())
            != 1)
          return null;
        if (store.db.update(
                "UPDATE activity_stock SET available_stock=available_stock+1,version=version+1 "
                + "WHERE activity_id=? AND sku_id=? AND available_stock<initial_stock",
                order.get("activity_id"), order.get("sku_id"))
            != 1)
          throw new IllegalStateException("Close stock conflict");
        outbox(order.get("reservation_id").toString(), "RESERVATION_RELEASE");
        return null;
      });
  }
  public void dispatch() {
    var due = store.db.queryForList(
        "SELECT event_id,reservation_id FROM outbox_events WHERE status='PENDING' AND "
        + "next_attempt_at_ms<=? ORDER BY created_at_ms LIMIT 100",
        store.now());
    for (var candidate : due) {
      try {
        store.transaction(() -> {
          mirror(candidate);
          return null;
        });
      } catch (Exception e) {
        System.err.printf("event=outbox_retry eventId=%s reservationId=%s reason=%s%n",
            candidate.get("event_id"), candidate.get("reservation_id"),
            e.getClass().getSimpleName());
        store.db.update("UPDATE outbox_events SET attempts=attempts+1,next_attempt_at_ms=? WHERE "
                        + "event_id=? AND status='PENDING'",
            store.now() + 2000, candidate.get("event_id"));
      }
    }
  }
  private void mirror(Map<String, Object> candidate) {
    // Lock the outbox event and its request in one indexed join. The request's
    // FK already guarantees its inventory parent exists; mirroring neither
    // reads nor changes that parent's stock. Keep per-event DB commit/Redis
    // durability and replay behavior unchanged.
    var out = store.one(
        "SELECT r.*,o.event_id,o.kind,o.status AS outbox_status FROM outbox_events o "
        + "JOIN seckill_requests r ON r.reservation_id=o.reservation_id "
        + "WHERE o.event_id=? FOR UPDATE", candidate.get("event_id"));
    if (out == null)
      throw new IllegalStateException("Outbox request missing");
    if (!"PENDING".equals(out.get("outbox_status")))
      return;
    var req = out;
    var order = store.one(
        "SELECT * FROM orders WHERE reservation_id=? FOR UPDATE", req.get("reservation_id"));
    String key = cache.ledger(Store.number(req, "activity_id"), Store.number(req, "sku_id")),
           user = req.get("user_id").toString(), request = req.get("request_id").toString(),
           reservation = req.get("reservation_id").toString(), epoch = req.get("epoch").toString();
    JsonNode current = cache.request(Store.number(req, "activity_id"), Store.number(req, "sku_id"),
        Store.number(req, "user_id"), request);
    if (current == null)
      throw new IllegalStateException("Redis request missing");
    String state = current.path("state").asText();
    if (order != null) {
      if (state.equals("RESERVED")) {
        ok(cache.lua("mark_request", relayKeys(key), user, request, reservation, epoch,
            "RESERVED", "QUEUED"));
        state = "QUEUED";
      }
      if (state.equals("QUEUED"))
        ok(cache.lua(
            "mark_request", relayKeys(key), user, request, reservation, epoch,
            "QUEUED", "ORDER_CREATED"));
      String status = order.get("status").toString();
      if (!status.equals("PENDING_PAYMENT"))
        ok(cache.lua("mark_order", key, user, request, reservation, epoch, status));
      if (status.equals("CLOSED") && out.get("kind").equals("RESERVATION_RELEASE"))
        ok(cache.lua("release", relayKeys(key), user, request, reservation, epoch,
            out.get("event_id").toString(), "CLOSED"));
    } else {
      if (!Set.of("COMPENSATING", "FAILED").contains(req.get("status")))
        throw new IllegalStateException("Release without termination");
      if (Set.of("RESERVED", "QUEUED").contains(state))
        ok(cache.lua(
            "mark_request", relayKeys(key), user, request, reservation, epoch, state,
            "COMPENSATING"));
      ok(cache.lua("release", relayKeys(key), user, request, reservation, epoch,
          out.get("event_id").toString(), "FAILED"));
      store.db.update("UPDATE seckill_requests SET status='FAILED' WHERE reservation_id=? AND "
                      + "status='COMPENSATING'",
          reservation);
    }
    store.db.update(
        "UPDATE outbox_events SET status='PUBLISHED',attempts=attempts+1 WHERE event_id=?",
        out.get("event_id"));
  }
  private static void ok(List<String> reply) {
    if (reply.isEmpty()
        || !Set.of("UPDATED", "REPLAY", "ALREADY_ADVANCED", "RELEASED", "ALREADY_RELEASED")
                .contains(reply.get(0)))
      throw new IllegalStateException("Redis mirror conflict: " + reply.get(0));
  }
  private List<String> relayKeys(String ledger) {
    return List.of(ledger, cache.prefix + ":relay_ledgers", ledger + ":relay_pending");
  }
}
