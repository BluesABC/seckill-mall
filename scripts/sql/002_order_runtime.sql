-- Additive migration: do not rewrite the applied 001 schema.
ALTER TABLE users ADD COLUMN enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE goods ADD COLUMN image_url VARCHAR(512) NOT NULL DEFAULT '';
CREATE TABLE mq_failures (
  message_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
  payload MEDIUMTEXT NOT NULL,
  status ENUM('RETRY','RESOLVED','QUARANTINED') NOT NULL DEFAULT 'RETRY',
  attempts INT UNSIGNED NOT NULL DEFAULT 1,
  reason VARCHAR(64) NOT NULL,
  updated_at_ms BIGINT UNSIGNED NOT NULL,
  KEY ix_failure_status(status, updated_at_ms)
) ENGINE=InnoDB;
