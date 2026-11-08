-- 微信APIv3支付意图先落库再出网；非终态支付禁止本地先关单释放库存。
ALTER TABLE shop_orders ADD COLUMN provider VARCHAR(32) NOT NULL DEFAULT 'MOCK';
CREATE TABLE wx_payments (
 id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
 order_kind ENUM('SHOP','SECKILL') NOT NULL, order_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 user_id BIGINT UNSIGNED NOT NULL, amount_fen BIGINT UNSIGNED NOT NULL,
 mchid VARCHAR(32) NOT NULL, appid VARCHAR(64) NOT NULL,
 out_trade_no VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
 state ENUM('CREATING','PREPAY','SUCCESS','CLOSED','REFUNDING','REFUNDED','REVIEW') NOT NULL,
 code_url VARCHAR(2048), transaction_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin UNIQUE,
 expires_at_ms BIGINT UNSIGNED NOT NULL, created_at_ms BIGINT UNSIGNED NOT NULL,
 next_check_at_ms BIGINT UNSIGNED NOT NULL DEFAULT 0,
 refund_key CHAR(36) CHARACTER SET ascii COLLATE ascii_bin UNIQUE,
 out_refund_no VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin UNIQUE,
 refund_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin,
 last_error VARCHAR(64),
 UNIQUE KEY uq_wx_order(order_kind,order_id), KEY ix_wx_pending(state,next_check_at_ms),
 FOREIGN KEY(user_id) REFERENCES users(id), CHECK(amount_fen>0)
) ENGINE=InnoDB;
