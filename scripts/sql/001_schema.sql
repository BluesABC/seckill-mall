-- MySQL 8.4 / InnoDB. Run once on an empty seckill_mall database.
-- All times are UTC milliseconds; money is integer CNY fen.
CREATE TABLE users (
  id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  username VARCHAR(64) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  role ENUM('USER','ADMIN') NOT NULL DEFAULT 'USER',
  created_at_ms BIGINT UNSIGNED NOT NULL
) ENGINE=InnoDB;

CREATE TABLE goods (
  id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  title VARCHAR(200) NOT NULL,
  description TEXT NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE
) ENGINE=InnoDB;

CREATE TABLE skus (
  id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  goods_id BIGINT UNSIGNED NOT NULL,
  price_fen BIGINT UNSIGNED NOT NULL,
  unallocated_stock INT UNSIGNED NOT NULL,
  version BIGINT UNSIGNED NOT NULL DEFAULT 0,
  FOREIGN KEY (goods_id) REFERENCES goods(id),
  CHECK (price_fen > 0)
) ENGINE=InnoDB;

CREATE TABLE activities (
  id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(200) NOT NULL,
  starts_at_ms BIGINT UNSIGNED NOT NULL,
  ends_at_ms BIGINT UNSIGNED NOT NULL,
  status ENUM('DRAFT','READY','ACTIVE','ENDED','ARCHIVED') NOT NULL DEFAULT 'DRAFT',
  CHECK (ends_at_ms > starts_at_ms)
) ENGINE=InnoDB;

CREATE TABLE activity_stock (
  activity_id BIGINT UNSIGNED NOT NULL,
  sku_id BIGINT UNSIGNED NOT NULL,
  initial_stock INT UNSIGNED NOT NULL,
  available_stock INT UNSIGNED NOT NULL,
  price_fen BIGINT UNSIGNED NOT NULL,
  epoch BIGINT UNSIGNED NOT NULL DEFAULT 1,
  version BIGINT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (activity_id, sku_id),
  FOREIGN KEY (activity_id) REFERENCES activities(id),
  FOREIGN KEY (sku_id) REFERENCES skus(id),
  CHECK (available_stock <= initial_stock),
  CHECK (price_fen > 0)
) ENGINE=InnoDB;

CREATE TABLE seckill_requests (
  reservation_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
  request_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  activity_id BIGINT UNSIGNED NOT NULL,
  sku_id BIGINT UNSIGNED NOT NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  epoch BIGINT UNSIGNED NOT NULL,
  price_fen BIGINT UNSIGNED NOT NULL,
  status ENUM('RESERVED','QUEUED','ORDER_CREATED','COMPENSATING','FAILED') NOT NULL,
  created_at_ms BIGINT UNSIGNED NOT NULL,
  failure_code VARCHAR(64),
  UNIQUE KEY uq_request (activity_id, sku_id, user_id, request_id),
  FOREIGN KEY (activity_id, sku_id) REFERENCES activity_stock(activity_id, sku_id),
  FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE orders (
  id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
  reservation_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
  activity_id BIGINT UNSIGNED NOT NULL,
  sku_id BIGINT UNSIGNED NOT NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  quantity INT UNSIGNED NOT NULL DEFAULT 1,
  amount_fen BIGINT UNSIGNED NOT NULL,
  status ENUM('PENDING_PAYMENT','PAID','CLOSED') NOT NULL,
  created_at_ms BIGINT UNSIGNED NOT NULL,
  expires_at_ms BIGINT UNSIGNED NOT NULL,
  version BIGINT UNSIGNED NOT NULL DEFAULT 0,
  UNIQUE KEY uq_purchase (activity_id, sku_id, user_id),
  KEY ix_timeout (status, expires_at_ms),
  FOREIGN KEY (reservation_id) REFERENCES seckill_requests(reservation_id),
  FOREIGN KEY (activity_id, sku_id) REFERENCES activity_stock(activity_id, sku_id),
  FOREIGN KEY (user_id) REFERENCES users(id),
  CHECK (quantity = 1),
  CHECK (amount_fen > 0),
  CHECK (expires_at_ms > created_at_ms)
) ENGINE=InnoDB;

CREATE TABLE payments (
  id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
  order_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
  idempotency_key CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  amount_fen BIGINT UNSIGNED NOT NULL,
  status ENUM('SUCCEEDED','REQUIRES_REFUND') NOT NULL,
  provider VARCHAR(32) NOT NULL,
  provider_transaction_id VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  created_at_ms BIGINT UNSIGNED NOT NULL,
  UNIQUE KEY uq_payment_retry (order_id, idempotency_key),
  UNIQUE KEY uq_provider_transaction (provider, provider_transaction_id),
  FOREIGN KEY (order_id) REFERENCES orders(id),
  CHECK (amount_fen > 0)
) ENGINE=InnoDB;

CREATE TABLE outbox_events (
  event_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
  reservation_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  kind ENUM('ORDER_CREATED','ORDER_PAID','RESERVATION_RELEASE') NOT NULL,
  payload JSON NOT NULL,
  status ENUM('PENDING','PUBLISHED','DEAD') NOT NULL DEFAULT 'PENDING',
  attempts INT UNSIGNED NOT NULL DEFAULT 0,
  next_attempt_at_ms BIGINT UNSIGNED NOT NULL,
  created_at_ms BIGINT UNSIGNED NOT NULL,
  UNIQUE KEY uq_business_event (reservation_id, kind),
  KEY ix_outbox_due (status, next_attempt_at_ms),
  FOREIGN KEY (reservation_id) REFERENCES seckill_requests(reservation_id)
) ENGINE=InnoDB;

CREATE TABLE reconciliation_runs (
  id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  activity_id BIGINT UNSIGNED NOT NULL,
  sku_id BIGINT UNSIGNED NOT NULL,
  checked_at_ms BIGINT UNSIGNED NOT NULL,
  result ENUM('CONSISTENT','IN_FLIGHT','MISMATCH') NOT NULL,
  snapshot JSON NOT NULL,
  FOREIGN KEY (activity_id, sku_id) REFERENCES activity_stock(activity_id, sku_id)
) ENGINE=InnoDB;
