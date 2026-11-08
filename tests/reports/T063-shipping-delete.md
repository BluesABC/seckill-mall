# T063 收货前置与订单删除验收

日期：2026-11-02；负责人：AI；关联G03/G13。用户要求秒杀创建订单前填写收货信息，并删除一笔历史缺失地址订单及实现订单删除。

实现见[操作与契约](../../docs/ORDER-SHIPPING-DELETE.md)。收货校验同时覆盖前端、C++预扣前、Java异步事务；地址快照不进入MQ。删除为终态逻辑删除，不物理删交易凭证或再次回补库存。

## 验证环境与命令

WSL2 Ubuntu 24.04.4 LTS、Linux原生Node v22.20.0、OpenJDK 21.0.12.1、Python 3.12.3；独立测试库/Redis前缀/RocketMQ topic与消费组，不重置用户数据卷。

```bash
source scripts/env-wsl.sh
cmake --build build/wsl/cpp-s3 -j2
ctest --test-dir build/wsl/cpp-s3 --output-on-failure
mvn -q -f src/order/pom.xml -Dmall.build.directory="$PWD/build/wsl/order-target" verify
bash scripts/build-web-wsl.sh
MALL_DB_USER=root MALL_DB_PASSWORD=s1-local-root-only MALL_DB_PORT=13306 MALL_REDIS_URL=redis://127.0.0.1:16379/0 build/wsl/venv/bin/python tests/test_s4.py
node tests/browser/shipping-delete-live.mjs
build/wsl/venv/bin/python scripts/verify_contracts.py
```

## 证据与限制

初次定向测试中的验证码夹具误用了摘要字段，随后修正；另一次私有SQL结果比较误用list/tuple，随后修正。保留失败日志，不作为通过证据。历史禁用/恢复用户测试须重新登录才能使用新增公开收货准备接口；不能复活撤销令牌。

- C++构建和CTest 3/3、Java verify、Vue/TypeScript构建通过。
- C++真实HTTP/Redis 27/27通过，26.251秒；首次27项业务断言通过但DrvFs覆写已有报告失败，报告改为同目录临时文件原子替换后重新运行成功。
- 真实商城全量36项首轮34项通过、2项测试夹具错误（424.289秒），包含本次收货/删除、支付取消竞争、维护脚本幂等的新用例均通过。失败的2项分别因宿主时钟与DB时钟混用、重新启用用户后沿用已撤销会话；已修正夹具并定向重跑14/16/18三项通过。不能把首轮标为全量通过。
- 三项失败相关复测耗时94.050秒，退出0，见[结果](wsl/t063-fixture-retry.json)；首轮失败事实单独保留在[t063-full-initial.json](wsl/t063-full-initial.json)。
- 真实本机浏览器：无地址禁用→地址簿填写→快照准备→真实C++/MQ异步建单→显示收货人和地址→取消→拒绝删除确认不改变订单→确认删除→刷新保持隐藏，通过。见[机器结果](wsl/t063-shipping-delete-live.json)。第一次浏览器测试定位器漏了按钮箭头，修正匹配后通过；未改业务按钮来迎合测试。
- 本机源码order/seckill/relay/gateway全部健康。用户指定的旧无地址MOCK订单已先预览核对，再执行单笔模拟退款与逻辑删除，订单/支付/库存保留。没有改管理员密码、没有清空数据卷或操作其他用户订单。
- 静态契约/SQL解析/Lua语法与文档链接检查、改动文件空白检查退出0；常用新增/变更Python脚本和浏览器入口语法检查通过。

未重跑30分钟容量、HA/TLS或NVDA/JAWS人工验收；新增准备请求改变交易链路，旧容量报告不证明当前版本性能。低层C++私有夹具只模拟无PII收货标记；真实消费者测试必须先有SQL快照。旧版S5全量页面断言还涉及此前已改变的统一订单/收银交互，当前任务采用新的真实本机浏览器入口验收。
