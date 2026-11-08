-- 预下单重试与主动查单分开租约，避免查询任务一直占用二维码恢复机会。
ALTER TABLE wx_payments ADD COLUMN prepay_lease_until_ms BIGINT UNSIGNED NOT NULL DEFAULT 0;
