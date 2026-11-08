# 源码阅读指南与注释规范

本指南面向第一次接触项目的开发者。功能阶段与验收事实以[PROGRESS](PROGRESS.md)为准，接口字段以[API](API.md)为准；本次注释维护不增加商城功能或生产容量承诺。

## 从哪里开始

先按[部署说明](DEPLOYMENT.md)运行完整商城，再按以下顺序读代码。业务主链为：浏览器 → Nginx → C++预扣 → Redis待发送记录 → C++ relay → RocketMQ → Java事务订单 → outbox镜像Redis。

| 顺序 | 入口 | 先关注什么 |
| --- | --- | --- |
| 1 | [完整Compose](../deploy/compose.yml)、[Nginx](../deploy/nginx/nginx.conf) | 哪些进程常驻，哪些是一次性初始化；秒杀与普通业务如何分流 |
| 2 | [App.vue](../src/web/src/App.vue)、[api.ts](../src/web/src/api.ts) | `startPurchase`、`buy`、`poll`；请求身份如何在刷新、断网和重试间保留 |
| 3 | [C++ main](../src/seckill/main.cpp)、[service.cpp](../src/seckill/service.cpp) | 配置 → `serve` → `Service::bind` → `/api/seckill/buy` |
| 4 | [reserve.lua](../src/seckill/lua/reserve.lua) | 库存/资格/活动/证明在什么顺序校验；预留与待发送事件如何一起记录 |
| 5 | [relay_worker.cpp](../src/mq/relay_worker.cpp)、[relay.cpp](../src/seckill/relay.cpp) | pending索引扫描、发送确认、未知结果保留及重试 |
| 6 | [RocketMQ发布适配](../src/mq/rocketmq_publisher.cpp)、[Push接收适配](../src/order/src/main/java/com/seckillmall/order/messaging/RocketPushReceiver.java) | 业务身份与Broker回执的区别；发送和消费成功分别表示什么 |
| 7 | [Workers.java](../src/order/src/main/java/com/seckillmall/order/business/Workers.java)、[Orders.java](../src/order/src/main/java/com/seckillmall/order/business/Orders.java) | `consume` → `accept` → `consumeLocked`；事务提交与消费确认的先后关系 |
| 8 | [Cache.java](../src/order/src/main/java/com/seckillmall/order/business/Cache.java)、[release.lua](../src/seckill/lua/release.lua) | outbox如何镜像DB事实，Redis写入怎样持久确认，重复回补怎样被阻止 |

`src/mq/main.cpp`是早期配置检查入口，不是Broker或日常消息转发进程；实际relay入口是`relay_worker.cpp`。Java的`RocketTransportProbe`、`RocketPushFailureProbe`和C++的`relay_probe`用于测试，不能当作业务消费者或真实MQ容量证据。

## 先统一几个概念

| 名称 | 含义 | 读代码时容易误解的地方 |
| --- | --- | --- |
| `goodsId` | 一款鞋的身份 | 同款多个尺码共享款式，但不能共享一个虚构SKU库存 |
| `skuId` | 一个真实尺码变体的身份 | 活动与交易都绑定具体SKU |
| `activityId` | 一场秒杀活动 | 活动时间结束后创建新场次，不能通过预热重置旧账本 |
| `requestId` | 浏览器为一次抢购意图保存的UUID | 请求结果未知时沿用，不通过换ID“重试” |
| `reservationId` | 服务端预留身份 | 同一预留的消息重投、DB记录及补偿始终关联它 |
| `eventId` | 事件身份 | 预留事件等于reservationId；DB outbox事件另有自己的事件ID |
| `traceId` | 日志关联标识 | 不是幂等键；HTTP handler耗时不包含所有入口等待 |
| `epoch` | 活动库存版本 | 防止旧活动凭据或消息错误作用于不同版本事实 |
| `priceFen` / `amountFen` | 以整数“分”表示的金额 | 线上JSON保持十进制字符串，前端金额运算使用BigInt |
| `*AtMs` / `*Ms` | Unix毫秒时间 / 毫秒时长 | Redis过期秒、Java调度秒等调用处仍要按实际API单位阅读 |

## 一笔抢购怎样走完

1. `App.startPurchase`先保存requestId。`captcha`签发挑战，`token`兑换绑定用户、请求、活动及epoch的证明。可读题与图片模式采用同一服务端校验策略。
2. `App.buy`在发出buy之前保存`submitted`。若响应丢失，页面可以继续查询原请求；`submitted`不是后端成功标志。
3. C++做认证、限流和参数校验，然后执行`reserve.lua`。已有请求优先走幂等查询；首次有效请求预扣库存，记录资格、请求及待发送事件。
4. C++在同连接执行AOF确认，再返回`202`。这只表示预留受理；不能显示“订单成功”或“支付成功”。连接失败可能留下已生效的写入，因此返回未知结果供查询。
5. relay从待发送集合取事件，使用原业务身份发送。拿不到明确回执时保留pending；即使Broker已收到，也允许后续安全重投。
6. Java消费者校验消息及Redis原预留事实，在一个MySQL事务内条件扣库存、写唯一请求、建待支付订单和outbox事件。并发重复消息由唯一约束与事务校验兜底。
7. `Orders.dispatch`将已提交的DB事实镜像Redis。每个事件单独事务并重查PENDING，Lua返回后仍做同连接WAITAOF；消费者、relay及镜像进度可能短暂交错，但不能回退状态。
8. 用户模拟支付或等待自然关闭。支付和关闭采用一致加锁顺序及条件更新；关闭时DB库存与outbox一起提交，Redis库存由幂等release脚本归还。

请求状态是`RESERVED → QUEUED → ORDER_CREATED`，异常可进入`COMPENSATING → FAILED`；订单状态另为`PENDING_PAYMENT → PAID / CLOSED`。两者不是同一个状态机，参见[状态契约](../src/seckill/include/mall/contracts.hpp)。

## 必须理解的设计原因

| 设计点 | 实现位置 | 原因 |
| --- | --- | --- |
| 同一连接确认AOF | C++ `durability_fence`；Java `Cache.eval` | 不能把另一条连接的持久化进度当作本次写入已确认；只读重放也需要因果写入 |
| 活动读取有界 | `Service::activity` | 账本含历史请求，HGETALL会让每次抢购成本随历史规模增长 |
| 库存先锁、请求后插 | `Orders.consumeLocked` | 避免外键共享父行锁升级造成热点死锁；后续失败仍整体回滚 |
| outbox独立调度 | `Workers.outboxExecutor` | 旧订单关闭的锁等待不能长期堵住新订单状态镜像 |
| 先持久终止再回补 | `Workers.recover`、`Orders.terminate` | 仅凭超时或MQ结果未知就回补，可能让迟到订单超卖 |
| 两层幂等释放标记 | `release.lua` | 同事件重放与不同事件指向同预留都不能重复加库存 |
| 后端连接响应后关闭 | C++ `serve` | 当前同步HTTP模型中，空闲keep-alive连接也会占worker；浏览器到Nginx仍可复用 |
| 两层排队分别观测 | TCP listen backlog与worker任务队列 | TCP连接等待、任务排队、handler耗时不能混为一个指标 |
| 隔离浏览器状态 | `api.attempts`、`paymentKey`、清单键 | 用户切换不能混用请求和支付身份，本地状态也不能代替服务端鉴权 |

Redis Lua只保证脚本执行期间不被其他命令交错，不把Redis、MQ和MySQL变成一个原子事务。项目通过持久预留、至少一次投递、幂等事务、outbox和可观察恢复处理跨系统失败窗口。

## 按功能查文件

| 想了解的功能 | 主要阅读位置 |
| --- | --- |
| 注册、登录、会话撤销、首次管理员 | [Sessions](../src/order/src/main/java/com/seckillmall/order/business/Sessions.java)；登录允许已有短密码不等于注册放宽要求 |
| HTTP字段/大小/重复参数限制 | [Input](../src/order/src/main/java/com/seckillmall/order/business/Input.java)、[RequestLimits](../src/order/src/main/java/com/seckillmall/order/business/RequestLimits.java)、C++ query/body辅助函数 |
| 商品分页、搜索、真实尺码、活动分配 | [Catalog](../src/order/src/main/java/com/seckillmall/order/business/Catalog.java)、[Admin.vue](../src/web/src/Admin.vue)、[ShoeDetail.vue](../src/web/src/ShoeDetail.vue) |
| 支付/关闭竞争、唯一订单、防超卖 | [Orders](../src/order/src/main/java/com/seckillmall/order/business/Orders.java)及现有SQL约束 |
| 重投、失败隔离、受控重放 | [Workers](../src/order/src/main/java/com/seckillmall/order/business/Workers.java)；错误消息不是无条件丢弃 |
| 库存守恒与只读诊断 | [reconcile.py](../scripts/reconcile.py)；CLEAN、INCONCLUSIVE和UNAVAILABLE有不同含义 |
| 一键启动及初始化先后 | [stack.sh](../scripts/stack.sh)、[data.py](../scripts/data.py)、[Compose](../deploy/compose.yml) |
| 私有夹具、并发与故障验收 | [TESTING](TESTING.md)及各tests文件的职责注释；夹具注入不能被描述为真实登录吞吐 |

## 注释格式与维护约定

- **语言与密度**：面向本项目读者使用中文，保留变量、错误码、状态及SDK术语原名。优先解释职责、前置条件、单位、失败后果及设计原因，不逐行复述赋值或循环。
- **C++**：文件使用Doxygen风格`@file`、`@brief`；公开边界按需要补`@param`、`@return`、`@throws`。写明资源所有权、线程归属、连接重试和未知结果语义。
- **Java**：类与关键方法使用Javadoc；类文档放在完整注解组之前。事务方法写清提交边界、锁顺序、幂等、外部副作用和异常处理，不把DB回滚写成能回滚Redis/MQ。
- **TypeScript / Vue**：脚本采用JSDoc风格块注释，Vue组件说明放在`script setup`内部。区分props/事件职责、真实SKU、显示快照与权威状态；异步代码说明失效响应和取消机制。
- **Lua**：文件头明确职责、KEYS/ARGV的位置与单位、前置状态、主要返回码及幂等/原子边界。新增参数时同步调用方与契约，不能只改注释。
- **Python / Bash / 配置**：保留shebang、编码声明及已有模块文档，采用块注释说明入口、环境、隔离和副作用。测试注明模拟/私有夹具、真实依赖和证据边界；注释不包含真实凭据。
- **迁移与第三方代码**：不为补注释改写已经应用、带校验和的SQL迁移；结构演进新增迁移，阅读说明放在文档。第三方固定源码与生成文件不在此次注释范围内。
- **维护原则**：修改代码时同步对应注释；注释里的“已确认”“已提交”“已支付”必须指明是哪一层事实。示例、测试夹具和阶段成绩不得写成生产能力承诺。

## 本次验证边界

本次采用逐文件快照及注释插入记录：逆向移除新增注释后，应与本轮开工时的工作区内容一致。比较对象包含当时已有的未提交改动，不以Git HEAD覆盖它们。

WSL检查包括C++构建/CTest、Java验证、前端类型检查/构建、Python/Bash语法、Lua编译与忽略注释/空白后的词元等价，以及静态契约/链接检查。具体命令、结果及未执行范围见[T055注释维护报告](../tests/reports/T055-code-comments.md)。此次不以注释改动宣称重新完成真实业务压测或生产上线门禁。
