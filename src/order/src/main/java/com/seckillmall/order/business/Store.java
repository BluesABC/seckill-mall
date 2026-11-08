package com.seckillmall.order.business;

import java.util.*;
import java.util.function.Supplier;
import org.springframework.dao.TransientDataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * 参数化SQL与事务辅助；将瞬态数据库失败以整个事务为单位有界重试。
 *
 * <p>业务链路与阅读顺序见 docs/CODE-READING.md。
 */
public final class Store {
  public final JdbcTemplate db;
  private final TransactionTemplate tx;
  Store(JdbcTemplate db, TransactionTemplate tx) {
    this.db = db;
    this.tx = tx;
  }
  /**
   * 瞬态数据库异常最多重试整个事务3次；闭包必须能安全重入，外部副作用不能假定随DB回滚。
   */
  public <T> T transaction(Supplier<T> action) {
    for (int attempt = 0;; attempt++) {
      try {
        return tx.execute(status -> action.get());
      } catch (TransientDataAccessException e) {
        if (attempt >= 2)
          throw e;
        try {
          Thread.sleep(25L * (attempt + 1));
        } catch (InterruptedException interrupted) {
          Thread.currentThread().interrupt();
          throw e;
        }
      }
    }
  }
  public Map<String, Object> one(String sql, Object... args) {
    List<Map<String, Object>> rows = db.queryForList(sql, args);
    return rows.isEmpty() ? null : rows.get(0);
  }
  public long insert(String sql, Object... args) {
    GeneratedKeyHolder keys = new GeneratedKeyHolder();
    db.update(connection -> {
      var statement = connection.prepareStatement(sql, java.sql.Statement.RETURN_GENERATED_KEYS);
      for (int i = 0; i < args.length; i++) statement.setObject(i + 1, args[i]);
      return statement;
    }, keys);
    return Objects.requireNonNull(keys.getKey()).longValue();
  }
  /**
   * 以MySQL时钟返回Unix毫秒，统一支付期限与关闭任务的时间依据。
   */
  public long now() {
    return db.queryForObject(
        "SELECT CAST(UNIX_TIMESTAMP(CURRENT_TIMESTAMP(3))*1000 AS UNSIGNED)", Long.class);
  }
  public static long number(Map<String, Object> row, String key) {
    return ((Number) row.get(key)).longValue();
  }
  public static boolean flag(Map<String, Object> row, String key) {
    Object v = row.get(key);
    return Boolean.TRUE.equals(v) || (v instanceof Number n && n.intValue() != 0);
  }
  /**
   * 将数据库数字转为十进制字符串；JSON中的布尔/文本等其他值原样保留。
   */
  public static Map<String, Object> wire(Map<String, Object> row) {
    Map<String, Object> out = new LinkedHashMap<>();
    row.forEach((k, v) -> out.put(k, v instanceof Number ? v.toString() : v));
    return out;
  }
}
