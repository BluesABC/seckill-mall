-- 普通商城独立订单账本；只消费skus.unallocated_stock，不触碰秒杀划拨库存。
CREATE TABLE shop_addresses (
 id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT, user_id BIGINT UNSIGNED NOT NULL,
 recipient VARCHAR(60) NOT NULL, phone VARCHAR(30) NOT NULL, address VARCHAR(400) NOT NULL,
 FOREIGN KEY(user_id) REFERENCES users(id)
) ENGINE=InnoDB;
CREATE TABLE shop_cart (
 user_id BIGINT UNSIGNED NOT NULL, sku_id BIGINT UNSIGNED NOT NULL, quantity INT UNSIGNED NOT NULL,
 PRIMARY KEY(user_id,sku_id), FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(sku_id) REFERENCES skus(id),
 CHECK(quantity BETWEEN 1 AND 10)
) ENGINE=InnoDB;
CREATE TABLE shop_orders (
 id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
 user_id BIGINT UNSIGNED NOT NULL, retry_key CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 fingerprint VARCHAR(64) NOT NULL, recipient VARCHAR(60) NOT NULL, phone VARCHAR(30) NOT NULL, address VARCHAR(400) NOT NULL,
 amount_fen BIGINT UNSIGNED NOT NULL, status ENUM('PENDING_PAYMENT','PAID','SHIPPED','DELIVERED','CLOSED','REFUNDED') NOT NULL,
 created_at_ms BIGINT UNSIGNED NOT NULL, expires_at_ms BIGINT UNSIGNED NOT NULL,
 payment_id CHAR(36), paid_at_ms BIGINT UNSIGNED, refund_id CHAR(36), refunded_at_ms BIGINT UNSIGNED,
 carrier VARCHAR(60), tracking VARCHAR(100), shipped_at_ms BIGINT UNSIGNED, delivered_at_ms BIGINT UNSIGNED,
 UNIQUE KEY uq_shop_checkout(user_id,retry_key), KEY ix_shop_expiry(status,expires_at_ms),
 FOREIGN KEY(user_id) REFERENCES users(id), CHECK(amount_fen>0)
) ENGINE=InnoDB;
CREATE TABLE shop_items (
 order_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, sku_id BIGINT UNSIGNED NOT NULL,
 title VARCHAR(200) NOT NULL, size_eu VARCHAR(10) NOT NULL, image_url VARCHAR(512) NOT NULL,
 quantity INT UNSIGNED NOT NULL, price_fen BIGINT UNSIGNED NOT NULL,
 PRIMARY KEY(order_id,sku_id), FOREIGN KEY(order_id) REFERENCES shop_orders(id), FOREIGN KEY(sku_id) REFERENCES skus(id),
 CHECK(quantity BETWEEN 1 AND 10), CHECK(price_fen>0)
) ENGINE=InnoDB;
