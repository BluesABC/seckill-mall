# T058 模拟支付凭证、全额退款与对账

2026-11-02，Asia/Shanghai；关联G01/G03/G06。用户明确选择暂不真实收款，完善模拟支付。

## 完成内容

新增本人支付凭证查询与幂等全额退款API、增量迁移004、mock_refunds唯一支付凭证约束、前端确认/凭证/退款/刷新恢复和只读支付账本对账。金额读取原订单/支付快照，跨用户404，未付款409；退款锁序沿用库存父行→订单。重复或并发退款只产生一张凭证，退款后再次pay返回REFUNDED，不再次支付。退款不退货、不回补库存或秒杀资格；订单保留PAID履约事实，财务支付状态单列。

## WSL验收

- `bash scripts/test-s4.sh`：退出0；真实C++/HTTP/RocketMQ/Java/MySQL/Redis 26/26通过，包含新增退款测试（4请求并发、越权、未付款拒绝、金额一致、库存不变、重复支付与对账差额检测/复原）。耗时467.063秒。CTest3/3、Java verify、静态契约328个文档链接检查通过。机器报告见[T058交易回归](wsl/t058-mock-payments.json)。
- `bash scripts/build-web-wsl.sh`：WSL Node22.20.0，类型检查与Vite生产构建通过。
- `source scripts/env-wsl.sh && node tests/browser/mock-payment.mjs`：凭证、取消确认、退款、刷新、390/1280无横向溢出通过。见[页面夹具报告](wsl/mock-payment-ui.json)，390px截图已人工查看，明确是UI夹具而非渠道联调。
- 本机Compose源码构建migrate/order/gateway，执行增量迁移并仅更新order/gateway，保留原卷及管理员账户。首次Maven下载TLS中断，重试构建成功；服务健康。实际首页JS包含两条新接口；认证查询不存在订单404。工具容器执行reconcile-payments.py返回CLEAN，三个差异计数均0。

## 限制

没有真实资金、支付渠道、外部回调或外部账单。仅全额模拟退款，不支持部分退款、退货入库、拒付、支付失败渠道模拟。MOCK功能不是生产支付验收，也不改变原HA/TLS/容量门禁状态。未上传本轮修改到GitHub。
