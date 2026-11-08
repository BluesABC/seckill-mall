-- 秒杀订单履约独立于原订单/Redis预留状态，保留既有库存与付款事实。
CREATE TABLE shop_seckill_delivery (
 order_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
 recipient VARCHAR(60) NOT NULL, phone VARCHAR(30) NOT NULL, address VARCHAR(400) NOT NULL,
 status ENUM('READY','SHIPPED','DELIVERED') NOT NULL DEFAULT 'READY',
 carrier VARCHAR(60), tracking VARCHAR(100), shipped_at_ms BIGINT UNSIGNED, delivered_at_ms BIGINT UNSIGNED,
 FOREIGN KEY(order_id) REFERENCES orders(id)
) ENGINE=InnoDB;
