# S0阶段验收报告

日期：2026-10-12。阶段：工程骨架、组件评估与核心契约。结果：S0通过；S1–S7未开始。相关任务T001/T002/T010/T011/T012完成，不代表交易闭环完成。

| 检查 | 实际证据 | 结果 |
| --- | --- | --- |
| C++构建 | Ubuntu WSL/GCC13.3，Release，CMake成功构建seckill_service、mall_mq、contract_tests | 通过 |
| CTest | state_contracts、seckill_configuration、mq_configuration | 3/3通过 |
| Java构建与测试 | Maven3.9.11/Spring Boot3.5.16/Java21；test package；HealthControllerTest | BUILD SUCCESS；1测试、0失败/错误 |
| 实JAR启动 | scripts/smoke_order.py随机本地端口启动打包jar并关闭本进程 | live200、ready503；[结果](s0-order-smoke.json) |
| Vue构建 | npm install生成lock；vue-tsc --noEmit与vite build | 类型检查与生产构建通过 |
| 消息契约 | 有效消息1个；非法quantity/version/金额类型/userId/UUID/额外字段6个 | 通过 |
| SQL | sqlglot MySQL方言解析10条CREATE TABLE | 通过，仅语法解析 |
| Lua | lupa编译reserve.lua | 通过，仅语法 |
| Compose | docker compose --env-file deploy/.env.example -f deploy/compose.infra.yml config --quiet | 通过，无容器启动 |
| Skill/引用 | quick_validate.py、verify_contracts.py | 通过；[静态结果](s0-contract-checks.json) |

## 重现

从项目根执行，Windows运行Python/Maven/npm，WSL运行C++。完整命令见 [快速开始](../../docs/README.md)。契约检查依赖固定在scripts/requirements-validation.txt，安装到被忽略的build/validation-deps。Maven位于build/tooling；下载来源Maven Central，与.sha512校验一致；未修改系统PATH。测试生成数据只在本项目或WSL临时构建目录，不修改父工作区候选项目。

## 实现范围与限制

C++二进制仅检查配置；Java仅健康端点；Vue仅预告页。没有生产Broker、HTTP秒杀、认证、商品管理、消费订单或支付实现。SQL未在MySQL执行，Lua未在Redis执行，没有超卖、幂等、回补或故障恢复实测，也无QPS报告。

Docker引擎未启动，基础设施配置只解析；Redis7.2.11/MySQL8.4镜像未拉取。后续阶段需实际依赖与故障测试才能确认运行组合。MQ核心可靠性和HA仍为实现要求，当前不可标称高可用。

## 下阶段入口

S1/T013：启用开发数据库环境，执行SQL迁移/种子数据，补全预热/回补脚本，验证Lua原子预扣、重复请求、库存边界与错误无副作用；输出真实MySQL/Redis证据再进入S2。
