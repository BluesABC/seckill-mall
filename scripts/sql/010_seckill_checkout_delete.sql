-- 收货快照先于预扣落盘；按原请求身份不可变，地址簿删除不影响历史订单。
CREATE TABLE seckill_checkouts (
 user_id BIGINT UNSIGNED NOT NULL, activity_id BIGINT UNSIGNED NOT NULL,
 sku_id BIGINT UNSIGNED NOT NULL, request_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 address_id BIGINT UNSIGNED NOT NULL,
 recipient VARCHAR(60) NOT NULL, phone VARCHAR(30) NOT NULL, address VARCHAR(400) NOT NULL,
 created_at_ms BIGINT UNSIGNED NOT NULL,
 PRIMARY KEY(user_id,activity_id,sku_id,request_id),
 FOREIGN KEY(user_id) REFERENCES users(id),
 CHECK(CHAR_LENGTH(TRIM(recipient))>=1 AND CHAR_LENGTH(TRIM(phone))>=5 AND CHAR_LENGTH(TRIM(address))>=5)
) ENGINE=InnoDB;

-- 用户删除仅移出个人列表；订单、支付、库存和后台审计事实仍保留。
CREATE TABLE order_deletions (
 order_kind ENUM('SHOP','SECKILL') NOT NULL,
 order_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 user_id BIGINT UNSIGNED NOT NULL, deleted_at_ms BIGINT UNSIGNED NOT NULL,
 PRIMARY KEY(order_kind,order_id,user_id),
 FOREIGN KEY(user_id) REFERENCES users(id)
) ENGINE=InnoDB;
