-- 管理员普通库存补货审计；幂等键防止响应丢失后重试重复增加。
CREATE TABLE shop_restocks (
 id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY, sku_id BIGINT UNSIGNED NOT NULL,
 quantity INT UNSIGNED NOT NULL, actor_id BIGINT UNSIGNED NOT NULL, created_at_ms BIGINT UNSIGNED NOT NULL,
 FOREIGN KEY(sku_id) REFERENCES skus(id), FOREIGN KEY(actor_id) REFERENCES users(id), CHECK(quantity BETWEEN 1 AND 1000000)
) ENGINE=InnoDB;
