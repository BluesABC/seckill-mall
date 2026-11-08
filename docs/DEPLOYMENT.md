# 完整容器部署

关联 G07/G08、D09、T024。此方案为本机可复现部署，唯一发布端口是 `127.0.0.1:18080`，不是公网生产发布。

## 前置与启动

WSL2 Ubuntu / Linux，Docker Engine 与 Compose v2，Python 3。先确认 `docker info`。必须能下载 Docker 镜像、Ubuntu 签名包、Maven/npm 依赖和已固定 SHA256 的 RocketMQ SDK 源码。默认 Ubuntu 构建源为官方 archive 的 HTTPS 地址，可通过 `--build-arg UBUNTU_MIRROR=...` 改为其他 Ubuntu 镜像；保留包签名与 HTTPS 校验。Ubuntu 基础镜像缺少 CA 时，从固定版本官方 Python 镜像复制公共 CA bundle，再经签名包安装 ca-certificates。

从项目根目录执行：

```bash
python3 scripts/prepare-deploy.py
bash scripts/stack.sh up
bash scripts/stack.sh status
```

`prepare-deploy.py` 生成独立随机密码且保留已有文件。模板为 `deploy/.env.stack.example`，不要直接使用占位密码。`.env.stack` 不纳入 Git 或镜像上下文。改变已初始化数据库密码时，不能只改 env 文件，应先按数据库账户变更流程操作。

访问 <http://localhost:18080>，注册用户、浏览鞋款、参加秒杀并按图片输入验证码；等待真实 MQ 消费得到待支付订单，再使用 MOCK 支付。管理员账号默认`admin`；`MALL_ADMIN_PASSWORD`只用于首次bootstrap，已存在管理员不会因修改env自动改密。本机演示数据库当前管理员密码为`admin`；该弱密码只适合本机演示，生产部署必须使用长随机密码。页面清单只记录逐款抢购意向，不占库存、不支持合并结账。

C++服务从S20起编译`CPPHTTPLIB_LISTEN_BACKLOG=128`，启动日志可核对；这是TCP连接等待队列，与`MALL_HTTP_QUEUE`任务队列独立，仍受内核somaxconn限制。通用worker默认8/任务排队128保持；S7的32线程只用于指定本机容量对照。更新需从源码重建C++镜像后重建seckill容器，保留所有命名卷，不通过放开后端端口或增加无限排队解决长尾。

首次启动依次应用仓库中的 SQL 迁移，健康检查确认数据库、Redis 和订单消费者就绪后启动 C++/Nginx。初始化先创建 NORMAL topic 与消费组，再建立订单消费者。`seed` 仅对空商品库建立四款运动鞋及60个演示尺码SKU（男/中性EU39–46半码、女款EU35–42半码），并为每个SKU单独创建活动；再次执行不会覆盖活动库存和订单，也不会刷新时间。活动过期后通过管理接口创建新场次。若首次种子操作中途失败，已有商品不会自动清空，应检查并手动补齐。

## 服务与存储

| 服务 | 容器端口 | 外部可达 | 数据 |
| --- | --- | --- | --- |
| gateway | 80 | 本机18080 | Vue 静态构建 |
| seckill | 8083 | 否 | Redis Lua；无本地业务持久化 |
| relay | 无监听 | 否 | Redis pending 恢复依据 |
| order | 8082 | 否 | MySQL + Redis |
| mysql | 3306 | 否 | mysql-data 卷 |
| redis | 6379 | 否 | redis-data，AOF always / noeviction |
| namesrv / broker Proxy | 9876 / 10911 / 8081 | 否 | broker-store、broker-logs、namesrv-logs |

`migrate`、`prepare-mq`、`mq-init` 是一次性服务，正常退出0不是故障。C++/Java 以 UID10001 运行。官方 SDK 从源码构建，不复制宿主机二进制或 Windows 缓存；Java 构建运行 Maven verify，前端运行类型检查与生产构建。

## Nginx 与可信代理

`/api/seckill/` 转 C++，其他 `/api/` 转 Java；关闭代理自动重试，交易请求结果未知时查询原 requestId。Nginx 覆盖用户传入的 X-Real-IP/X-Forwarded-For，仅可信的固定 gateway IP 可向后端提供客户端 IP。默认直连后端不会信任转发头。改变子网时需同步 `MALL_SUBNET`、`MALL_GATEWAY_IP` 与 `ORDER_TRUSTED_PROXY_REGEX`，只信任网关单个 IP。

Nginx 使用 Docker DNS 定期解析被重建服务，采用共享 upstream zone；该能力的开源版本边界见 [官方 upstream 文档](https://nginx.org/en/docs/http/ngx_http_upstream_module.html)。当前固定 Nginx1.28.0。API/CAPTCHA no-store，带版本 JS/CSS 长缓存，原图短缓存；CSP、nosniff、referrer 策略与只记录 URI 不记录查询参数的访问日志已配置。HTTP 为本机演示；公网发布另需 TLS、域名、可信入口、备份、密钥轮换和资源预算。

RocketMQ Broker 向 SDK 发布可在 Docker 网络解析的 `broker` 地址，避免把容器的 localhost 当成其他服务地址；官方部署参考见 [RocketMQ Docker 文档](https://rocketmq.apache.org/docs/quickStart/02quickstartWithDocker/)。单 Broker SYNC_FLUSH 不等于 HA。

## 日常操作与排障

```bash
bash scripts/stack.sh logs
bash scripts/stack.sh down
bash scripts/stack.sh up
```

`down` 保留卷，下次 `up` 使用既有数据；不提供默认删卷命令。`up` 不会刷新演示活动时间。迁移历史校验不允许覆盖已执行 SQL，应添加新迁移。宿主端口冲突时改 `MALL_WEB_PORT`；子网冲突时选择空闲私网并同步可信代理配置。若健康检查失败，先检查 `docker compose --env-file deploy/.env.stack -f deploy/compose.yml logs --tail 100`，不要反复清空卷。

可通过 MALL_STACK_PROJECT / MALL_STACK_ENV 选择独立 Compose 项目和 env。测试专用项目 `seckill-mall-s6` 使用独立卷；所有可见状态以 [PROGRESS](PROGRESS.md) 的实际验收为准。

## WSL 验收入口

```bash
bash scripts/test-s6-wsl.sh
```

该入口拒绝复用已有 S6 测试卷，以保证干净初始化。测试使用真实容器与 MQ，私有夹具仅设置验证码摘要和订单到期时间；报告说明这些操作。测试会重启自己的全部业务容器，保留最终数据用于检查。再次完整验收应先保存并明确处理旧测试环境，不能删除用户业务卷。


C++秒杀服务工作线程和有界队列可通过 `MALL_HTTP_WORKERS`（默认8）与 `MALL_HTTP_QUEUE`（默认128）覆盖。S14在12逻辑CPU本机测试发现48线程是后续诊断候选配置，但订单可查P95仍未达到临时3秒门槛；S16的15 QPS×30分钟测试显示64线程/512排队仍未达到持续容量门禁。不要把本机实验值直接用作生产配置。修改线程数或队列后需用目标拓扑重新跑热点正确性、持续容量和延迟验收。

由旧版ledger迁移到活动待发索引时，relay仅在启动时回填旧格式。单实例升级需先停止旧C++入口写入，再部署新入口/relay，保留Redis、MySQL和MQ卷；不能把“旧生产者继续运行时的混部滚动迁移”视为已验证HA。S3包含现格式在线恢复与旧格式启动回填两个独立回归。

S17已在上述本机预算下用32线程/128排队通过15 QPS×30分钟下单创建专项；配置及源码/镜像依据见[S17验收](../tests/reports/S17-acceptance.md)。通用默认仍8/128，不能将该专项容量推广到生产或混合用户旅程。复现与测试后参数恢复见[测试说明](TESTING.md)。

## T059 普通商城升级

先构建源码工具/订单/网关镜像，执行migrate，再更新order和gateway，保留所有命名卷。新增005/006/007迁移不可跳过；不要修改旧迁移校验和。普通商城入口`/#/shop/cart`、`/#/shop/orders`；已支付秒杀物流`/#/shop/seckill`；管理员发货/补货`/#/shop/admin`。若既有管理员曾改短密码，启动bootstrap仍须保持原合法长配置（它不会改已有账户密码），种子登录使用实际当前密码；不要把生产凭据或个人地址提交Git。实际支付与物流为演示，详见ORDINARY-SHOP.md。

## T060 微信可选配置

默认MOCK不变。真正准备好商户和公网TLS后，使用`MALL_WECHAT_ENV=deploy/.env.wechat bash scripts/stack.sh up`，覆盖层只读挂载私钥/APIv3文件；先执行008/009迁移并升级全部订单实例，不能让旧关单逻辑与真实微信并行写订单。当前本机没有商户资料，未启用此覆盖层，不能接收真实微信回调。字段和验收门禁见[微信接入说明](WECHAT-PAY.md)。

## Redis 主从复制基础配置

仅使用基础 Compose 文件时，启动一个主节点 redis 和一个只读副本 redis-replica。日常项目通过 scripts/stack.sh 默认启用下文 Sentinel 覆盖层。副本使用独立数据卷和 AOF 每秒落盘，通过 backend 网络复制主节点。业务连接地址仍为 redis:6379，预扣、订单、消息中继和对账均以主节点为准。

已有运行栈可单独启动副本：

```bash
docker compose -p seckill-mall-stack --env-file deploy/.env.stack -f deploy/compose.yml up -d --no-deps --wait redis-replica
docker exec seckill-mall-stack-redis-1 redis-cli INFO replication
docker exec seckill-mall-stack-redis-replica-1 redis-cli INFO replication
```

主节点应显示 connected_slaves:1，副本应显示 master_link_status:up 和 master_sync_in_progress:0。此拓扑为同机异步复制，主节点故障时应用仍依赖原地址。自动选主需使用下文 Sentinel 覆盖层。跨机器故障演练仍待验证。

## Sentinel 隔离演练

覆盖层 deploy/compose.sentinel.yml 启动三个可晋升 Redis 节点和三个 Sentinel。C++ 与中继在连接失效后向 Sentinel 重新发现主节点，Java 使用 Lettuce 的 Sentinel 配置。候选节点都以 AOF always 运行，满足商城主节点就绪条件。

在 WSL 从项目根目录启动独立演练。需使用空的演练项目数据卷、独立网段和端口，不能对日常商城执行故障脚本。

```bash
export MALL_SUBNET=172.30.93.0/24 MALL_GATEWAY_IP=172.30.93.250 MALL_WEB_PORT=18993
export ORDER_TRUSTED_PROXY_REGEX='172[.]30[.]93[.]250' MALL_ADMIN_PASSWORD=sentinel-lab-only-test-password
lab=(docker compose -p seckill-mall-sentinel-lab --env-file deploy/.env.stack -f deploy/compose.yml -f deploy/compose.sentinel.yml)
"${lab[@]}" build seckill order gateway migrate
"${lab[@]}" up -d --wait --wait-timeout 240 gateway relay redis-replica-2
"${lab[@]}" run --rm --no-deps seed
set -o pipefail
python3 tests/sentinel_lab.py | tee tests/reports/wsl/sentinel-failover.json
```

此覆盖层的 Redis 固定地址属于 172.30.93.0/24。故障演练强停当前主节点，结束后启动旧节点。Redis 启动脚本查询三个 Sentinel，至少两个返回同一主地址才启动。现有运维脚本中的固定 Redis 地址需要在运维前核对当前主节点。

选主后的全栈冷启动使用以下演练入口。脚本先启动 Sentinel 和上次选出的主节点，再启动其余服务，并通过 Sentinel 执行受控回切。演练使用固定项目名与端口，保留数据卷。

```bash
set -o pipefail
python3 tests/sentinel_coldstart.py | tee tests/reports/wsl/sentinel-coldstart.json
```

手工回切只在演练环境执行，要求三个 Sentinel 的主节点视图一致、两台副本在线。脚本临时排除另一候选副本，选主后恢复原优先级。该脚本不提供生产迁移或隔离旧主节点的机制。

本机反复出现 Sentinel TILT。成功轮仅在三个演练 Sentinel 临时执行 SENTINEL DEBUG TILT-PERIOD 3000，生产默认参数未调整。恢复用时只代表该演练参数下的一次结果。测试先确认预留已复制，再强停主节点，不能据此给出异步复制的数据零丢失承诺。

## 日常商城 Sentinel

默认项目 seckill-mall-stack 通过 scripts/stack.sh 启用一主两从和三个 Sentinel。内网默认网段为 172.30.85.0/24，Redis 数据节点使用 .201、.202、.203，Sentinel 使用 .211、.212、.213。自定义网段时设置对应的 MALL_REDIS_NETWORK_PREFIX 并确保这些地址未占用。

在 WSL 使用 bash scripts/stack.sh status 查看容器。使用 bash scripts/reconcile-stack.sh --strict 执行只读对账，脚本向三个 Sentinel 查询当前主节点，至少两个返回同一地址才执行。冷启动用 bash scripts/stack.sh up，先启动 Sentinel，再启动其报告的主节点，随后启动其余服务。不要用基础 Compose 启动参数覆盖选主后的角色。

2026-11-08 实测保留原 Redis 数据卷，切换前完成快照和对账，切换后订单数与 15 个活动库存账本一致。两台副本均收到探针写入，订单与秒杀就绪、商品接口正常。日常拓扑未执行强停验收。宿主机仍观察到 Sentinel TILT，可能推迟选主，保持默认保护参数。同机拓扑与异步复制的容灾边界见隔离演练。
