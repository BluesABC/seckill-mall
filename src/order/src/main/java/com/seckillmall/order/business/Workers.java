package com.seckillmall.order.business;

import com.fasterxml.jackson.databind.JsonNode;
import com.seckillmall.order.messaging.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;
import org.apache.rocketmq.client.apis.consumer.ConsumeResult;
import org.apache.rocketmq.client.apis.message.MessageView;
import org.springframework.data.redis.core.Cursor;
import org.springframework.data.redis.core.ScanOptions;

/**
 * 消费、过期关闭、恢复与outbox后台调度；消费者成功确认晚于数据库事务提交。
 *
 * <p>业务链路与阅读顺序见 docs/CODE-READING.md。
 */
public final class Workers implements AutoCloseable {
  private final Store store;
  private final Cache cache;
  private final Orders orders;
  private final String endpoint, topic, group;
  private final long recoveryAge;
  private final boolean jobs;
  private final int threads;
  private final ScheduledExecutorService executor =
      Executors.newSingleThreadScheduledExecutor(r -> {
        Thread t = new Thread(r, "order-recovery");
        t.setDaemon(true);
        return t;
      });
  // Dispatch must not wait behind a batch of expired-order transactions or a
  // recovery scan. One dedicated worker preserves bounded per-event commits.
  private final ScheduledExecutorService outboxExecutor =
      Executors.newSingleThreadScheduledExecutor(r -> {
        Thread t = new Thread(r, "order-outbox");
        t.setDaemon(true);
        return t;
      });
  private volatile RocketPushReceiver consumer;
  private volatile boolean closing;
  private volatile String lastError = "STARTING";
  private volatile String lastOutboxError = "NOT_STARTED";
  private final AtomicLong outboxCycles = new AtomicLong();
  private Cursor<String> ledgerScan;
  private final Map<String, Cursor<Map.Entry<Object, Object>>> requests = new LinkedHashMap<>();
  private final AtomicLong received = new AtomicLong(), confirmed = new AtomicLong(),
                           failed = new AtomicLong();
  private static final long CONSUMER_CLOSE_WAIT_SECONDS = 20;
  Workers(Store s, Cache c, Orders o, String endpoint, String topic, String group, long recoveryAge,
      boolean jobs) {
    if (recoveryAge < 1000)
      throw new IllegalArgumentException("Recovery age must be >=1000ms");
    this.store = s;
    cache = c;
    orders = o;
    this.endpoint = endpoint;
    this.topic = topic;
    this.group = group;
    this.recoveryAge = recoveryAge;
    this.jobs = jobs;
    threads = consumerThreads();
  }
  /**
   * 启动消费维护与独立outbox调度；过期订单锁等待不应阻塞新订单状态派发。
   */
  public void start() {
    executor.scheduleWithFixedDelay(() -> {
      if (closing)
        return;
      try {
        if (consumer == null)
          consumer = new RocketPushReceiver(endpoint, topic, group, this::consume, threads);
        if (jobs)
          maintenance();
        lastError = "NONE";
      } catch (Exception e) {
        lastError = e instanceof Fault f ? f.code : e.getClass().getSimpleName();
        System.err.println("order-worker error=" + lastError);
      }
    }, 0, 1, TimeUnit.SECONDS);
    if (jobs)
      outboxExecutor.scheduleWithFixedDelay(() -> {
        if (closing)
          return;
        try {
          orders.dispatch();
          outboxCycles.incrementAndGet();
          lastOutboxError = "NONE";
        } catch (Exception e) {
          lastOutboxError = e instanceof Fault f ? f.code : e.getClass().getSimpleName();
          System.err.println("order-outbox error=" + lastOutboxError);
        }
      }, 0, 100, TimeUnit.MILLISECONDS);
  }
  private static int consumerThreads() {
    String configured = System.getenv("MALL_MQ_CONSUMER_THREADS");
    int count = configured == null ? 4 : Integer.parseInt(configured);
    if (count < 1 || count > 64)
      throw new IllegalArgumentException("MALL_MQ_CONSUMER_THREADS must be 1..64");
    return count;
  }
  /**
   * 解析→事务落单→记录恢复结果→确认；任何失败返回FAILURE，允许安全重投。
   */
  private ConsumeResult consume(MessageView message) {
    received.incrementAndGet();
    String body = null;
    String reservation = "unknown", trace = "unknown";
    long receivedAtMs = System.currentTimeMillis();
    long transactionStartedNanos = 0;
    try {
      body = RocketMessageReceiver.body(message);
      if (body.length() > 16384)
        throw new Fault(400, "INVALID_EVENT");
      ReservedEvent event = ReservedEvent.parse(cache.json(body));
      reservation = event.reservationId();
      trace = event.traceId();
      long relaySendStartedAtMs = propertyLong(message, "mallRelaySendStartedAtMs");
      long brokerBornAtMs = message.getBornTimestamp();
      System.out.printf("event=seckill_stage stage=consumer_received reservationId=%s traceId=%s "
              + "receivedAtMs=%d reservationAgeMs=%d relayToConsumerMs=%d brokerQueueMs=%d "
              + "relaySendToBrokerMs=%d deliveryAttempt=%d%n",
          reservation, trace, receivedAtMs, Math.max(0, receivedAtMs - event.createdAtMs()),
          relaySendStartedAtMs < 0 ? -1 : Math.max(0, receivedAtMs - relaySendStartedAtMs),
          Math.max(0, receivedAtMs - brokerBornAtMs),
          relaySendStartedAtMs < 0 ? -1 : Math.max(0, brokerBornAtMs - relaySendStartedAtMs),
          message.getDeliveryAttempt());
      transactionStartedNanos = System.nanoTime();
      orders.accept(event);
      long transactionMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - transactionStartedNanos);
      long committedAtMs = System.currentTimeMillis();
      System.out.printf("event=seckill_stage stage=order_transaction_committed reservationId=%s "
              + "traceId=%s committedAtMs=%d mysqlTransactionMs=%d%n",
          reservation, trace, committedAtMs, transactionMs);
      resolve(body);
      confirmed.incrementAndGet();
      return ConsumeResult.SUCCESS;
    } catch (Exception e) {
      failed.incrementAndGet();
      String reason = e instanceof Fault f ? f.code : e.getClass().getSimpleName();
      if (transactionStartedNanos != 0)
        System.err.printf("event=seckill_stage stage=order_transaction_failed reservationId=%s "
                + "traceId=%s failedAtMs=%d mysqlTransactionMs=%d reason=%s%n",
            reservation, trace, System.currentTimeMillis(),
            TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - transactionStartedNanos), reason);
      if (body != null && body.length() <= 16384)
        try {
          journal(body, reason, e instanceof Fault);
        } catch (Exception ignored) { /* Broker retains message when DB cannot store audit. */
        }
      return ConsumeResult.FAILURE;
    }
  }
  private static long propertyLong(MessageView message, String name) {
    try {
      String value = message.getProperties().get(name);
      if (value == null) return -1;
      return Long.parseLong(value);
    } catch (RuntimeException ignored) {
      return -1;
    }
  }
  /**
   * 以消息体摘要记录失败；业务冲突进入隔离，暂态失败保持可恢复RETRY。
   */
  private void journal(String body, String reason, boolean quarantine) {
    store.db.update("INSERT INTO mq_failures(message_hash,payload,status,reason,updated_at_ms) "
            + "VALUES(?,?,?,?,?) ON DUPLICATE KEY UPDATE "
            + "attempts=attempts+1,reason=VALUES(reason),updated_at_ms=VALUES(updated_at_"
            + "ms),status=IF(status='RESOLVED',status,VALUES(status))",
        Cache.hash(body), body, quarantine ? "QUARANTINED" : "RETRY", reason, store.now());
  }
  private void resolve(String body) {
    store.db.update("UPDATE mq_failures SET status='RESOLVED',updated_at_ms=? WHERE message_hash=?",
        store.now(), Cache.hash(body));
  }
  /**
   * 管理员显式恢复入口；与后台派发可能并发，重复生效由事件行锁防护。
   */
  public synchronized void tick() {
    // Explicit ADMIN recovery remains synchronous, including jobs-disabled
    // fixtures. Concurrent dispatchers serialize on the event row and recheck
    // PENDING under its lock, so the same event is not applied twice.
    orders.dispatch();
    maintenance();
    orders.dispatch();
  }
  /**
   * 有界关闭过期单、重试失败消息并扫描老预留；不承担outbox主派发循环。
   */
  private synchronized void maintenance() {
    orders.closeExpired();
    for (var row : store.db.queryForList("SELECT message_hash,payload FROM mq_failures WHERE "
             + "status='RETRY' ORDER BY updated_at_ms LIMIT 20")) {
      String body = row.get("payload").toString();
      try {
        orders.accept(ReservedEvent.parse(cache.json(body)));
        resolve(body);
      } catch (Fault f) {
        journal(body, f.code, true);
      } catch (Exception ignored) {
      }
    }
    recover();
  }
  // A durable DB termination fence is required before releasing an aged reservation.
  // This also finds reservations stranded in Broker DLQ while MySQL was unavailable.
  /**
   * 跨轮保留SCAN游标，每轮限制账本/请求工作量；先建DB终止事实再由outbox回补。
   */
  private void recover() {
    if (ledgerScan == null)
      ledgerScan = cache.redis.opsForSet().scan(
          cache.prefix + ":ledgers", ScanOptions.scanOptions().count(20).build());
    while (requests.size() < 10 && ledgerScan.hasNext()) {
      String key = ledgerScan.next();
      if (!key.startsWith(cache.prefix + ":{"))
        continue;
      requests.computeIfAbsent(key,
          k
          -> cache.redis.opsForHash().scan(
              k, ScanOptions.scanOptions().match("req:*").count(100).build()));
    }
    if (!ledgerScan.hasNext()) {
      ledgerScan.close();
      ledgerScan = null;
    }
    int examined = 0;
    long now = store.now();
    var entries = requests.entrySet().iterator();
    while (entries.hasNext() && examined < 500) {
      var entry = entries.next();
      var cursor = entry.getValue();
      while (cursor.hasNext() && examined++ < 500) {
        var item = cursor.next();
        JsonNode req = cache.json(item.getValue().toString());
        if (!Set.of("RESERVED", "QUEUED").contains(req.path("state").asText()))
          continue;
        long created = Input.id(req.path("createdAtMs").asText());
        if (now - created < recoveryAge)
          continue;
        String[] parts = item.getKey().toString().split(":", 3);
        var metadata = cache.redis.opsForHash().multiGet(
            entry.getKey(), List.of("activityId", "skuId", "epoch", "priceFen"));
        ReservedEvent event = new ReservedEvent(Input.uuid(req.path("reservationId").asText()),
            Input.uuid(parts[2]), Input.id(parts[1]), Input.id(metadata.get(0).toString()),
            Input.id(metadata.get(1).toString()), Input.id(metadata.get(2).toString()),
            Input.id(metadata.get(3).toString()), created, "recovery");
        orders.terminate(event, "RESERVATION_TIMEOUT");
      }
      if (!cursor.hasNext()) {
        cursor.close();
        entries.remove();
      }
    }
  }
  /**
   * 按失败消息摘要执行受控重放，保留原事件身份和所有业务校验。
   */
  public Map<String, Object> replay(String hash) {
    if (hash == null || !hash.matches("[0-9a-f]{64}"))
      throw new Fault(400, "INVALID_ARGUMENT");
    var row = store.one("SELECT payload FROM mq_failures WHERE message_hash=?", hash);
    if (row == null)
      throw new Fault(404, "NOT_FOUND");
    String body = row.get("payload").toString();
    orders.accept(ReservedEvent.parse(cache.json(body)));
    resolve(body);
    return Map.of("status", "RESOLVED", "messageHash", hash);
  }
  public Map<String, Object> metrics() {
    return Map.of("received", received.get(), "confirmed", confirmed.get(), "failed", failed.get(),
        "outboxPending",
        store.db.queryForObject(
            "SELECT COUNT(*) FROM outbox_events WHERE status='PENDING'", Long.class),
        "compensating",
        store.db.queryForObject(
            "SELECT COUNT(*) FROM seckill_requests WHERE status='COMPENSATING'", Long.class),
        "quarantined",
        store.db.queryForObject(
            "SELECT COUNT(*) FROM mq_failures WHERE status='QUARANTINED'", Long.class),
        "lastWorkerError", lastError, "lastOutboxError", lastOutboxError,
        "outboxDispatchCycles", outboxCycles.get());
  }
  /**
   * 检查迁移、DB、Redis持久化策略、Proxy端口和消费者实例；不等同于HA或容量证明。
   */
  public boolean ready() {
    try (var connection = cache.redis.getConnectionFactory().getConnection();
         var socket = new java.net.Socket()) {
      int colon = endpoint.lastIndexOf(':');
      socket.connect(new java.net.InetSocketAddress(endpoint.substring(0, colon),
                         Integer.parseInt(endpoint.substring(colon + 1))),
          250);
      return !closing
          && store.db.queryForObject(
                 "SELECT COUNT(*) FROM schema_migrations WHERE version IN ('002_order_runtime','003_sneaker_attributes')",
                 Long.class)
          == 2
          && consumer != null && "PONG".equals(connection.ping())
          && "yes".equals(
              connection.serverCommands().getConfig("appendonly").getProperty("appendonly"))
          && "always".equals(
              connection.serverCommands().getConfig("appendfsync").getProperty("appendfsync"))
          && "noeviction".equals(connection.serverCommands()
                                       .getConfig("maxmemory-policy")
                                       .getProperty("maxmemory-policy"));
    } catch (Exception e) {
      return false;
    }
  }
  @Override
  public void close() throws Exception {
    closing = true;
    executor.shutdownNow();
    outboxExecutor.shutdownNow();
    outboxExecutor.awaitTermination(3, TimeUnit.SECONDS);
    if (executor.awaitTermination(3, TimeUnit.SECONDS)) {
      if (ledgerScan != null)
        ledgerScan.close();
      for (var c : requests.values()) c.close();
      requests.clear();
    }
    // SDK shutdown can wait on background RPCs. Bound the JVM shutdown hook.
    if (consumer != null)
      try {
        CompletableFuture
            .runAsync(() -> {
              try {
                consumer.close();
              } catch (Exception e) {
                throw new CompletionException(e);
              }
            })
            // SDK close timed out at five seconds in S7; delivery resumed about
            // 74 seconds after restart. Give it 20 seconds to unregister within
            // Compose's 30-second stop grace period, then verify the effect.
            .get(CONSUMER_CLOSE_WAIT_SECONDS, TimeUnit.SECONDS);
      } catch (ExecutionException | TimeoutException e) {
        System.err.println(
            "order-consumer shutdown pending; committed transactions remain replay-safe");
      }
  }
}
