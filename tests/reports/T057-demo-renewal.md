# T057 演示秒杀重新开场

日期：2026-10-23（Asia/Shanghai）。关联G01/G02/G08。

## 行为

首次空库seed原有行为保持：按启动时刻创建24小时活动，与GitHub上传日期无关。新增 `bash scripts/stack.sh renew-demo`，为无未到期READY/ACTIVE场次的原创演示SKU建立七天新场；每码最多划拨10件未分配库存，不修改旧活动时间、订单、Redis账本或库存总量。无剩余库存则跳过。登录使用本机配置，密码若曾手动修改须同步本机env。禁止并行执行；激活失败保留READY场次，管理员重试activate，不能重复新建。

## 实测

- WSL原生Python运行 `build/wsl/venv/bin/python tests/test_demo_renewal.py`：3/3通过，覆盖无待续场、库存上限/运行时日期、激活失败停止。
- WSL `bash -n scripts/stack.sh` 与Python编译检查通过。
- Docker Desktop启动后恢复保留的数据卷；WSL Compose构建migrate工具镜像通过。
- 在现有本机商城经真实管理API建立5场，第二次运行提示无需续场。
- WSL从 `/api/activities` 读取，再逐个核对 `/api/seckill/info`：5/5 ACTIVE且stockAvailable=true。未执行真实购买或支付，不将此检查算完整交易验收。

旧订单与库存未清空。不承诺生产上线；MOCK支付及单Broker边界不变。该工具为人工演示维护，不是自动续期定时器；库存耗尽时需业务补货输入。
