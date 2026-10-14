# 高并发秒杀商城项目总览

建设支持商品浏览、用户与商品管理、秒杀、异步下单、支付状态和后台接口的商城，重点验证防超卖、防刷、削峰与最终一致性。需求来自《【项目目标】.docx》，完整映射见 [项目目标](../.agents/skills/seckill-mall/references/project-goals.md)。

## 技术栈与职责

| 模块 | 技术 | 职责 |
| --- | --- | --- |
| 前端 | TypeScript + Vue 3 | 运动鞋商城、真实尺码/清单、验证码抢购、订单/MOCK支付、后台与响应式页面 |
| 秒杀服务 | C++ | 网关、限流、活动资格、Redis Lua 预扣、投递 |
| 消息队列 | RocketMQ5.x | 用户明确采用；C++/Java官方SDK适配在S3，后续需要再换自研 |
| 订单服务 | Java + Spring Boot | 商品/用户管理、订单事务、支付与关闭、对账 |
| Redis | Redis | 预热、原子预扣、限流、占位与热点缓存 |
| 数据库 | MySQL | 库存、订单、支付、恢复与审计记录 |
| 接入与部署 | Nginx + Docker Compose | 代理、缓存、限流、独立容器和环境复现 |

工程基线已记录在 [COMPONENTS.md](COMPONENTS.md)。默认开发模拟支付，核心契约v1.0.0；正式容量与HA需实际验证。

生产候选规模、性能/SLO、HA、安全和a11y验收目标见[临时基线目标v0.1](BASELINE-TARGETS-v0.1.md)。其中暂定值仅供继续设计和压测，不能当成生产承诺；每项状态、测量口径和复查条件均在该文档标明。

## 快速开始

数据/缓存、C++HTTP、真实RocketMQ、Java认证/商品/活动/事务订单/MOCK支付/关闭/补偿与Vue运动鞋商城可运行。阶段验收状态以[PROGRESS](PROGRESS.md)为准。前端本地展厅、开发代理与WSL浏览器测试见[前端运行说明](FRONTEND-RUNTIME.md)，订单独立启动见[订单说明](ORDER-RUNTIME.md)。S6完整容器已验收，启动见[部署说明](DEPLOYMENT.md)；S7本机故障/容量与S8消费者恢复见[进度报告](PROGRESS.md#验证记录)、[S7验收报告](../tests/reports/S7-acceptance.md)、[S8验收报告](../tests/reports/S8-acceptance.md)、[容量报告](BENCHMARK.md)与[演示流程](DEMO.md)。

工作目录为 `E:/c++project/seckill-mall`；推荐WSL2 Ubuntu，C++/Java21/Node均有原生工具和测试入口；Windows可做补充开发。先读PROGRESS和TODO。

### C++ HTTP秒杀（WSL/Linux）

```bash
cmake -S . -B build/cpp -DBUILD_TESTING=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build/cpp -j2
ctest --test-dir build/cpp --output-on-failure
build/cpp/src/seckill/seckill_service --check-config
build/cpp/src/mq/mall_mq --check-config
```

依赖安装与当前隔离构建/启动：
```bash
sudo apt-get install -y libhiredis-dev libssl-dev nlohmann-json3-dev libpng-dev
bash scripts/test-s2.sh
build/wsl/cpp/src/seckill/seckill_service --serve
```
C++默认127.0.0.1:8083；`/health/live`检查进程，`/health/ready`仅表示Redis/本服务就绪，mqIntegrated=false。配置例见deploy/.env.seckill.example，按需要export变量；端口和Key前缀可改。绑定限本机，不自动启动公开站点。--check-config不验证网络依赖；mall_mq仍是适配配置检查入口。

S2没有注册/登录接口；会话必须由S4发行。集成测试私有会话与验证码解题夹具只写随机测试前缀，HTTP没有绕过验证码/登录的调试入口。正常流程见API：获取PNG→提交答案并绑定requestId→双令牌buy→查询原requestId。示例活动仍READY，正式活动管理/激活在S4实现，不通过盲改缓存演示抢购。

### Java骨架（PowerShell）

本机Maven3.9.11已下载并校验到build/tooling；其他环境可用已安装的Maven3.6.3+执行同样目标。
```powershell
& .\build\tooling\apache-maven-3.9.11\bin\mvn.cmd -f src/order/pom.xml -B verify
java -jar src/order/target/order-service-0.1.0-SNAPSHOT.jar
```
默认8082端口。未启用业务时`/health/live`为200、`/health/ready`为503。

上述是默认健康骨架模式。启用S4业务及真实依赖、首次管理员配置见[订单运行说明](ORDER-RUNTIME.md)，WSL执行`bash scripts/test-s4.sh`验收。业务启用后账号/商品/活动/订单接口可运行，支付仅MOCK。

### 前端骨架（PowerShell）

```powershell
Set-Location src/web
npm.cmd ci --no-audit --no-fund
npm.cmd run build
npm.cmd run dev
```
开发页位于127.0.0.1:5173，当前只有活动预告，没有模拟可购买商品或抢购按钮。

### S0验收

```powershell
python -m pip install --target build/validation-deps -r scripts/requirements-validation.txt
python -X utf8 scripts/verify_contracts.py
python -X utf8 scripts/smoke_order.py
docker compose --env-file deploy/.env.example -f deploy/compose.infra.yml config --quiet
```
验证命令须从项目根执行。`smoke_order.py`短暂启动随机本地端口并结束自己启动的进程；格式验证不等于SQL/Lua真引擎测试。

### WSL数据与缓存验证

```bash
source scripts/env-wsl.sh
bash scripts/test-s1.sh
bash scripts/test-wsl.sh --all
```
专用Compose项目seckill-mall-s1，Redis16379/MySQL13306仅绑定127.0.0.1；开发凭据见deploy/.env.s1.example。脚本真实运行迁移/种子/预热、集成与AOF崩溃恢复，不删除数据卷。此阶段已执行成功，容器保留运行。

数据工具位于scripts/data.py，迁移记录SHA256并拒绝漂移/未跟踪的部分Schema，重复种子不重置库存；预热仅允许无请求、初始库存完整的READY活动且不能覆盖已有Key。演示活动/SKU900001库存100，首次生成1小时窗口，不因seed重跑延长。无演示登录账户，认证在S4实现。

SQL由显式迁移工具执行，不再自动挂到MySQL入口。独立测试创建随机数据库与Key，结束清理自己的数据；开发数据保留。S1崩溃测试短暂重启其专用Redis，不与依赖该实例的应用并行运行。停止开发服务可执行 `docker compose -p seckill-mall-s1 --env-file deploy/.env.s1.example -f deploy/compose.infra.yml stop`。

## 目录

```text
seckill-mall/
├── AGENTS.md
├── README.md
├── .agents/skills/seckill-mall/
├── docs/
│   ├── README.md
│   ├── ARCHITECTURE.md
│   ├── API.md
│   ├── DECISIONS.md
│   ├── TODO.md
│   ├── PROGRESS.md
│   ├── CHANGELOG.md
│   ├── WORKLOG.md
│   └── BUGS.md
├── src/
│   ├── seckill/
│   ├── mq/
│   ├── order/
│   └── web/
├── deploy/
├── scripts/
└── tests/reports/
```

源码、部署、脚本与测试目录保留 `.gitkeep` 以支持版本管理；不把空目录视为模块实现。

## 文档导航

- [RocketMQ运行说明](ROCKETMQ.md)：固定SDK、Broker/Proxy、pending转发与消费重试；WSL验收执行`bash scripts/test-s3.sh`。
- [前端视觉方向](FRONTEND-DIRECTION.md)：S5简约精品商城设计与验收要求。

- [WSL测试](TESTING.md)：原生环境、依赖隔离与骨架/S1/S2实际入口。
- [架构](ARCHITECTURE.md)：设计基线与状态流转。
- [接口](API.md)：候选接口及契约冻结状态。
- [决策](DECISIONS.md)：项目隔离、技术边界与后续选择。
- [任务](TODO.md)：按优先级管理实现事项。
- [进度](PROGRESS.md)：唯一阶段进度真相源。
- [变更](CHANGELOG.md)、[工作日志](WORKLOG.md)、[已知问题](BUGS.md)。
