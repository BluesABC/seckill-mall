# T062 模拟微信收银闭环验收

日期：2026-11-02；负责人：AI；关联目标：G03/G13。用户明确要求演示支付方式选择、微信样式二维码和手动模拟付款，无需商户号。

## 实现与结论

普通购买及秒杀订单共用模拟收银弹窗：待支付订单→方式选择→模拟二维码→显式确认→服务端PAID→成功结果。QR展示接口不落支付凭证、不改变订单。二维码只是演示文本，不是真实收款链接；原真实Native实现保持独立。

## WSL实际验证

环境：WSL2 Ubuntu 24.04.4 LTS，OpenJDK 21.0.12.1，Node v22.20.0，Python 3.12.3。在项目根目录执行，依赖沿用项目WSL原生构建环境与自有测试栈：

```bash
source scripts/env-wsl.sh
mvn -q -f src/order/pom.xml -Dmall.build.directory="$PWD/build/wsl/order-target" verify
bash scripts/build-web-wsl.sh
MALL_DB_USER=root MALL_DB_PASSWORD=s1-local-root-only MALL_DB_PORT=13306 MALL_REDIS_URL=redis://127.0.0.1:16379/0 build/wsl/venv/bin/python tests/test_s4.py test_05j_mock_cashier_does_not_pay_until_confirmed
node tests/browser/mock-cashier-live.mjs
node tests/browser/wechat-ui.mjs
build/wsl/venv/bin/python scripts/verify_contracts.py
```

- Java验证及Vue/TypeScript构建通过。
- 静态契约检查退出0：1个正例、6个反例、10条SQL解析、Lua语法及377个文档链接；首次误用系统Python缺少sqlglot，改用已有项目虚拟环境通过。该检查不执行Redis/MySQL或压测。
- 真实HTTP/C++/RocketMQ/Java/MySQL/Redis定向集成1项通过，57.209秒；包含普通/秒杀二维码、展示前后无支付凭证、错误所有者、伪造金额、无效方式、过期/已付拒绝、直接模拟方式、幂等支付。见[t062-cashier-http.json](wsl/t062-cashier-http.json)。
- 独立普通用户真实浏览器下单→选择方式→二维码→确认→服务端PAID→刷新保留→退款通过。Escape及QR展示不付款；390/768/1440无弹窗横向溢出。测试退款恢复该普通订单库存占用；不改管理员密码/商品。见[结果](wsl/t062-cashier-live.json)。
- 本机源码容器已更新，order/gateway健康，默认MOCK。
- 可选真实Native页面夹具回归通过：MOCK只提供演示收银台，WECHAT隐藏模拟按钮，原二维码/查单/退款/关单展示正常；该测试不连接微信渠道。

## 限制与未通过项

- 管理员版本的`retail-live.mjs`本轮登录返回401，未完成；改用不需要管理员的`mock-cashier-live.mjs`完成本任务真实购买验收，未重置现有账号。
- 未重跑完整商城历史回归；秒杀后端走真实MQ链路，当前浏览器端到端主流程使用普通订单。
- 未进行微信真实支付、渠道通知、真实退款/外部账单验证；未完成NVDA/JAWS人工实测，未新增容量/HA/TLS上线证据。
- 总耗时未记录；不以本任务完成代替S20或生产上线门禁。
