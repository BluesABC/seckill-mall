# WSL测试入口

自2026-10-12起，后续阶段验收必须包含WSL实际结果。S0历史Java/Vue/静态契约Windows结果不自动视为WSL通过。

## 原生环境

Ubuntu WSL2需要CMake3.20+、C++20编译器、Python3.10+/venv/pip、Java21、Maven3.6.3+、Node22.12+和npm。当前已安装Java21/Maven3.8.7/Pythonvenv/pip，项目tooling中有Node22.20；Docker Desktop Linux引擎已启动且Ubuntu集成可用，S1真实引擎与骨架全套通过。

新的Ubuntu环境可安装基础依赖（本阶段已安装缺失包）：
```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake python3-venv python3-pip openjdk-21-jdk-headless maven
sudo apt-get install -y libhiredis-dev libssl-dev nlohmann-json3-dev libpng-dev
```
Node按所选Linux发行版的官方安装说明安装满足版本的发行版；不要使用WSL自动继承的Windows npm或node.exe。用`command -v java mvn node npm docker`确认来源。Docker integration是否可用用`docker version`和`docker compose version`核对；不依赖Windows PowerShell启动测试。

## 运行

```bash
cd '/mnt/e/c++project/seckill-mall'
source scripts/env-wsl.sh
bash scripts/test-s10-assets-wsl.sh
bash scripts/test-wsl.sh --cpp
bash scripts/test-wsl.sh --all
bash scripts/test-s1.sh
bash scripts/test-s2.sh
bash scripts/test-s3.sh
bash scripts/test-s4.sh
```
--cpp只运行C++子集；--all运行C++、静态契约、Java测试/打包/进程冒烟、Vue类型与生产构建、Compose解析。缺失依赖退出2不降级。S1脚本运行真实MySQL/Redis集成与SIGKILL+AOF恢复；最新证据见[S1验收](../tests/reports/S1-acceptance.md)，[兼容性报告](../tests/reports/wsl-compatibility.md)保留补环境前的历史结果。

构建与Python依赖使用build/wsl/，Vue源码复制到build/wsl/web/安装Linux原生依赖；不要混用Windows的node_modules或build/validation-deps。输出写入tests/reports/wsl/。压测推荐WSL ext4工程目录并记录路径/CPU/内存；/mnt/e工作目录可用于功能检查。

test-s1使用Compose项目seckill-mall-s1/端口16379和13306，测试凭据仅用于开发；随机数据库/Key由测试创建并只清理自己数据，不删除卷。崩溃测试重启这个专用Redis，勿与使用此实例的应用并行。--all仍为骨架回归，不能代替真实引擎与MQ验证。

test-s2构建真实C++服务并用随机端口/Key前缀执行HTTP/Redis测试，结束停止自己启动的进程；不与test-s1的Redis崩溃测试并行。私有会话/固定验证码答案只由Python测试夹具写Redis，服务没有公开绕过入口；relay_probe仅允许s2_test_前缀，不是RocketMQ实测。TCP代理丢弃一次WAITAOF回复验证未知受理的安全重放，未关闭真实实例AOF。样例PNG与JSON/日志保存在tests/reports/wsl/。

## MQ选型状态

S4入口构建Java JDBC/Redis业务和C++，随后在随机数据库、Redis前缀、Topic/消费组上验证真实HTTP→C++→RocketMQ→Java→MySQL订单链路、MOCK支付、关闭/幂等回补、outbox恢复、迟到消息和消费隔离。S4测试短暂停止本项目MySQL，验证失败重投到DLQ及DB恢复后的终止 fence；不与S1/S3故障套件或使用本实例的应用并行。C++验证码答案只由私有测试夹具在测试前缀内设置，无公开绕过入口。运行细节见[订单说明](ORDER-RUNTIME.md)。

S3原生依赖增加`libgrpc++-dev protobuf-compiler-grpc libprotobuf-dev libabsl-dev zlib1g-dev`，先通过Ubuntu apt安装。`test-s3.sh`使用独立Compose项目seckill-mall-mq，固定SDK源码/校验哈希并构建至build/wsl，执行六项真实跨语言与故障测试。首次构建较慢；不与其他Broker故障测试或依赖实例的应用并行。详情见[MQ说明](ROCKETMQ.md)与[S3验收](../tests/reports/S3-acceptance.md)。订单MySQL事务验收在S4。

用户明确采用RocketMQ，ADR-009替代原C++ Broker选择。S3做NameServer/Broker/Proxy部署与官方C++/Java SDK集成，不实现自研WAL/复制协议。pending、消息schema和DB幂等不绑定厂商；未来用户要求时再更换自研MQ。S1未部署RocketMQ或测试消息收发。

## S5 WSL 浏览器验收

`bash scripts/test-s5-wsl.sh` 运行 Java测试/打包、Vue类型/生产构建、Linux Chromium/Playwright与axe检查，以及真实C++→RocketMQ→Java→MySQL业务。需已有S4的原生SDK/C++/Python和运行中的Redis/MySQL/MQ；系统浏览器依赖和中文字体独立安装，步骤见 [前端运行说明](FRONTEND-RUNTIME.md)。浏览器依赖固定在 tests/browser/package-lock.json，安装目录 build/wsl/browser 与 Windows 分开。报告/截图在 tests/reports/wsl/s5/；静态构建和真实链路分项报告，不将页面性能当容量。

浏览器夹具只修改自身随机DB/缓存中的验证码答案、过期时间、售罄显示条件，退出清理自身数据/服务；不会停止共享基础设施。故障套件（会重启Redis/MySQL/Broker）不要与S5或本地展厅并行运行。丢失响应在真实受理成功后注入，API故障/轮询状态的界面条件测试单列说明，不冒充对应真实后端故障。

## S6 WSL 完整容器验收

`bash scripts/test-s6-wsl.sh` 从源码构建 C++/官方 SDK、Java verify、Vue类型与生产构建、Python迁移工具，在独立 `seckill-mall-s6` 的干净命名卷上启动 Redis/MySQL/RocketMQ/业务/Nginx。需要Docker、Python3、Node22与S5所述Linux浏览器系统依赖，所有工具为WSL原生版本。入口拒绝已有测试卷，不会清空业务数据；生成随机本机 `.env.stack`，不提交密钥。

验收所有请求经Nginx：认证/私有验证码夹具/真实抢购与MQ订单、重复受理/支付、自动关闭与回补、重复种子、可信代理与转发头伪造、私有端口/非root、Java容器重建DNS、整个业务栈重启后会话和订单/库存持久化。重启后读取既有事实不等于重新下单恢复SLA；S7另行测量。生产页面另用原生Chromium检查CSP下资源、真实商品、桌面/手机布局与控制台错误。

证据为 `tests/reports/wsl/s6-deploy.log` / `s6-deploy.json` 与 `s6-ui/`。完整验收报告随阶段结束添加；HTTP API/页面验收不能代替容量压测或生产HA。日常启动/保留卷停止见[部署说明](DEPLOYMENT.md)。

## S7 WSL 故障与容量

`bash scripts/test-s7-wsl.sh`：独立seckill-mall-s7、18081、172.30.87/24、随机本机env；拒绝复用既有卷，保留验收数据。Python3标准库驱动真实Nginx→C++→RocketMQ→Java→MySQL，不调用Windows工具，不改日常数据。入口从源码构建后执行`tests/test_s7.py`与`tests/load_s7.py`。依赖Docker/Python与已有构建镜像网络，无额外压测器依赖。

检查只读对账/在途宽限/注入差异/丢失账本、relay/consumer/Broker/DB/Redis停机与AOF强杀、支付关闭、真实DLQ与终止后原事件重放。用户已选择本机基线：阶梯4/16/64并发重复两次，单热点超量、多个活动、10秒持续流量、下游DB停机、128待发送有界拒绝与标准40r/s限流分开测。每次等待账本收敛，并核对实际接受的requestId是否落库，记录HTTP与端到端分位。

原始证据`tests/reports/wsl/s7/`及`s7-load-run.log`、`s7-finalize-run.log`、`s7-run.log`；夹具说明/故障恢复口径/限流差别见[OPERATIONS](OPERATIONS.md)。C++连接恢复改动另跑`bash scripts/test-s2.sh`，S1存储/AOF另跑`bash scripts/test-s1.sh`。本轮分开运行故障/DLQ和容量/收尾，未将其描述成全新卷聚合入口一次退出0；测试卷保留，聚合入口需在新隔离卷重新验证。当前是本机探索，不是注册/登录/验证码或生产HA/小时级稳定性验收。

## S8 WSL 消费者优雅重启

`bash scripts/test-s8-wsl.sh`使用已存在且独立的`seckill-mall-s7`项目/随机`.env.s7`，只停止/启动该项目order容器并新建私有SKU/用户/订单；不触碰日常`seckill-mall-stack`或`seckill-mall-s1`。需WSL Docker可用、S7完整栈运行、Python标准库。三轮均以真实C++预扣、RocketMQ积压、Java消费者恢复和MySQL订单查询为证，并逐轮只读对账；任一订单超过20秒或consumer.close超时即失败。该入口用SIGTERM和30秒Compose宽限，不代表SIGKILL恢复。

## S9 WSL 公共目录分页

`bash scripts/test-s9-wsl.sh`先运行完整S5真实浏览器验收（测试展厅使用15173端口和独立临时数据库/Redis前缀），再在独立S7订单栈插入105个带唯一前缀的测试商品，验证公共目录连续分页、搜索、类别/价格筛选、排序、无重项、参数拒绝与清理后库存对账。测试商品在`finally`中删除，不更改S7订单或活动数据。WSL入口会启动既有测试基础服务但不重建或清除卷。
