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

首次空库自动迁移 001–003，健康检查确认数据库、Redis 和订单消费者就绪后启动 C++/Nginx。初始化先创建 NORMAL topic 与消费组，再建立订单消费者。`seed` 仅对空商品库建立四款运动鞋及60个演示尺码SKU（男/中性EU39–46半码、女款EU35–42半码），并为每个SKU单独创建活动；再次执行不会覆盖活动库存和订单，也不会刷新时间。活动过期后通过管理接口创建新场次。若首次种子操作中途失败，已有商品不会自动清空，应检查并手动补齐。

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
