-- 模拟全额退款凭证：不改变订单履约状态，也不自动退货/回补库存。
CREATE TABLE mock_refunds (
 id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
 payment_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
 idempotency_key CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 amount_fen BIGINT UNSIGNED NOT NULL,
 created_at_ms BIGINT UNSIGNED NOT NULL,
 FOREIGN KEY (payment_id) REFERENCES payments(id),
 CHECK (amount_fen > 0)
) ENGINE=InnoDB;
