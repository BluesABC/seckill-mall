# API v1 核心契约

核心契约版本1.2.0，S2于2026-10-12新增凭证接口，S4于2026-10-13实现Java业务，S9增加公共目录分页，S15增加管理员尺码SKU创建接口。C++承担活动缓存查询、验证码/令牌和预扣；Java业务启用后承担账号、商品/活动管理、MySQL订单查询与MOCK支付。阶段验收状态以PROGRESS为准。

S4已通过真实业务验收：Java业务启用后承担账号、商品/活动管理、MySQL权威查询和MOCK支付；具体运行见[订单运行说明](ORDER-RUNTIME.md)，证据见[S4报告](../tests/reports/S4-acceptance.md)。

S3独立RocketMQ转发进程已接通，Broker确认后请求可推进QUEUED。HTTP健康接口的mqIntegrated=false仍表示HTTP进程内部未直接加载SDK；转发进程单独运行，QUEUED不代表MySQL订单已创建。运行方法见[MQ说明](ROCKETMQ.md)。

| 方法与路径 | 用途 | 输入索引 | 输出索引 |
| --- | --- | --- | --- |
| GET /api/seckill/info | 查询活动与商品 | activityId、skuId | 活动时间、价格、展示库存与活动状态 |
| POST /api/seckill/buy | 提交抢购 | requestId、activityId、skuId、验证码凭证、活动令牌 | 请求 ID、受理状态、查询入口；不承诺订单已创建 |
| GET /api/order/status | 查询抢购与订单结果 | requestId 或 orderId | 请求进度、订单 ID、订单状态与失败原因 |
| POST /api/order/pay | 开发MOCK支付入口 | orderId、idempotencyKey | 订单/支付状态 |

## 通用规则

- 用户身份从认证上下文获得，查询与支付校验归属；价格以服务端快照为准。
- requestId作用域、合法重放与受理边界按下文执行；同范围参数与原请求不匹配返回REQUEST_CONFLICT。
- 请求/订单状态使用下文统一枚举；稳定错误码见错误码表，示例为契约样本而非真实订单。
- 普通商品/用户/后台接口与真实支付回调在后续阶段补充；验证码/活动令牌见下文已实现契约。

ID、金额分和 UTC 毫秒时间使用十进制字符串，业务 ID 最大有符号64位；requestId/reservationId/orderId 使用小写 UUID。购买固定数量1，活动+SKU+用户一人一单，关闭不释放资格。请求体16KiB上限，未知字段拒绝。

认证使用Authorization: Bearer <64位小写十六进制opaque令牌>，Redis Key为`<prefix>:session:<SHA256(token)>`，Hash字段userId/role/expiresAtMs并设置TTL，角色仅USER/ADMIN；默认prefix=seckill，会话目标2小时。C++从服务端会话解析身份，禁止客户端指定userId。会话发行/注册/登录由S4负责，S2没有公开测试登录或身份伪造入口。幂等范围是activityId+skuId+认证用户+requestId，重试保留ID。其他用户请求结果返回404。

JSON未知字段/重复字段、重复查询键和非规范查询键拒绝400，查询键必须使用文档中的ASCII名称（不接受编码后的同义键）。HTTP body上限16KiB，超出413。当前IP以socket对端为准，不相信X-Forwarded-For；可信代理策略在S6完善。

失败格式：`{"code":"RATE_LIMITED","message":"请求过于频繁","traceId":"...","retryable":true}`。429/503可带Retry-After；客户端超时或依赖错误先按原ID查询，不能推断没扣库存。

## S4 Java基础接口

所有写接口拒绝未知/重复JSON字段，body至多16KiB；数字ID、金额分、时间使用十进制字符串。首页、活动和其他现有列表接口保留各自上限；公共商品目录使用显式分页。Java独立8082，C++8083，统一代理在S5/S6。

| 方法与路径 | 权限 | 请求/行为 |
| --- | --- | --- |
| POST /api/auth/register | 公开，注册限流 | `{username,password}`；201，固定USER角色 |
| POST /api/auth/login | 公开，IP/账号限流 | 同上；200，token/userId/role/expiresAtMs |
| GET /api/auth/me | 已登录 | userId、role |
| POST /api/auth/logout | 已登录 | 撤销当前会话 |
| GET /api/goods | 公开 | 首批最多100个展示SKU：items含goodsId/skuId/title/description/imageUrl/priceFen |
| GET /api/goods/catalog | 公开 | 服务端筛选、排序和分页公共商品目录 |
| GET /api/goods/{id} | 公开 | 当前商品的SKU列表items |
| GET /api/activities | 公开 | READY/ACTIVE/ENDED活动及SKU、时间、价格、DB展示库存 |
| GET /api/orders | 本人 | 本人的订单列表 |
| GET /api/admin/users | ADMIN | 用户列表，不返回密码哈希 |
| PATCH /api/admin/users/{id} | ADMIN | `{enabled:boolean}`；禁用撤销会话，不允许禁用自己 |
| POST /api/admin/goods | ADMIN | `{title,description,imageUrl,priceFen,stock}`；创建商品与首SKU，201 |
| PATCH /api/admin/goods/{id} | ADMIN | `{title,description,imageUrl,enabled}`；逻辑下架影响展示，活动停止用end |
| POST /api/admin/activities | ADMIN | `{name,skuId,stock,priceFen,startsAtMs,endsAtMs}`；划拨SKU库存，READY，201 |
| POST /api/admin/activities/{id}/activate | ADMIN | `{skuId}`；首次预热并激活，相同请求可恢复DB→Redis激活窗口 |
| POST /api/admin/activities/{id}/end | ADMIN | `{skuId}`；停止新购买，处理已受理消息 |
| GET /api/admin/orders | ADMIN | 订单管理列表 |
| GET /api/admin/recovery | ADMIN | 消费失败messageHash/原因/状态和消费/补偿指标 |
| POST /api/admin/recovery/{hash}/replay | ADMIN | 按原始消息重放，保留幂等标识，拒绝伪造/冲突事件 |
| POST /api/admin/recovery/run | ADMIN | 执行一轮有界关闭/outbox/恢复，后台同样自动运行 |

username为3–64位ASCII字母/数字/下划线/连字符；password至少12字符、UTF-8至多72字节。登录失败统一401，不暴露用户是否存在。注册限制每IP10分钟15次，登录每IP10分钟80次、每账号30次。商品imageUrl为空或`/assets/...`项目资源路径；不接收任意HTML/远程图片URL。活动价不得高于SKU标价，stock正整数且≤100000000。

Java订单查询/支付沿用本文核心契约，依赖错误返回503。`requestState=COMPENSATING`直到Redis回补经持久化屏障成功后才变FAILED；订单创建、支付、关闭均以MySQL已提交状态为准。MOCK支付接口不调用真实支付渠道。新错误码：409 CONFLICT/INSUFFICIENT_STOCK/ACTIVITY_CONFLICT/CACHE_CONFLICT/SELF_DISABLE_FORBIDDEN。

公共目录`GET /api/goods/catalog`支持可选`q`（标题/描述，最多80字符）、`category`（跑步/篮球/休闲/训练）、`maxPriceFen`、`sort`（featured/low/high）、`page`（从0起，默认0）、`size`（默认12，最大48）。返回`items/page/size/total/hasMore`；每件商品以最早SKU作为目录卡片，详情仍可读取该商品全部SKU。页码和大小非法或超过上限时返回400。排序稳定：精选按商品ID倒序，价格排序按价格后再按商品ID倒序。

```json
{"items":[{"goodsId":"108","skuId":"141","title":"AERO/01 · 轻量跑鞋","description":"轻量鞋款","imageUrl":"/assets/shoe-run-v1.webp","priceFen":"89900","sizeEu":"42","category":"跑步","colorway":"白 / 荧光黄","unallocatedStock":"30"}],"page":0,"size":12,"total":105,"hasMore":true}
```

### C++ GET /api/seckill/info

公开查询，必填 activityId、skuId。200响应：
```json
{"activityId":"1","skuId":"1","title":"活动商品","priceFen":"1990","startsAtMs":"1791792000000","endsAtMs":"1791795600000","serverTimeMs":"1791792000100","state":"ACTIVE","stockAvailable":true}
```
活动状态DRAFT/READY/ACTIVE/ENDED/ARCHIVED；stockAvailable只是展示提示。S2读取预热ledger，无缓存返回404，不直接回源MySQL；元数据缺失503。title未预热时使用“SKU <skuId>”标识，普通商品完整展示由S4/S5接口负责。

## GET /api/seckill/captcha

认证必需；query必填activityId、skuId；可选`mode=image|accessible`（默认`image`）。成功200返回一次性挑战ID和有效期，不返回答案。image模式返回6位数字PNG：
```json
{"captchaId":"096d738a-58f8-40e1-a915-87788d02092f","mode":"image","imageDataUrl":"data:image/png;base64,...","expiresAtMs":"1791792060000"}
```
`mode=accessible`返回屏幕阅读器可读取的随机加法题，不返回图片：
```json
{"captchaId":"096d738a-58f8-40e1-a915-87788d02092f","mode":"accessible","challengeText":"请计算 38 加 61，并输入得数。","expiresAtMs":"1791792060000"}
```
挑战绑定认证用户、活动、SKU和epoch，60秒过期，答案仅存SHA256；错误答案最多5次。文字题答案为1–6位数字。两种模式均为基础防刷演示，不能声称抗OCR/自动化求解能力已验证。

## POST /api/seckill/token

认证必需；购买requestId在此阶段生成并绑定，之后buy使用同一个ID：
```json
{"activityId":"1","skuId":"1","requestId":"43c05877-35b9-485e-a1fd-cf20551223e0","captchaId":"096d738a-58f8-40e1-a915-87788d02092f","captchaAnswer":"123456"}
```
`captchaAnswer`必须为1–6位数字；图片挑战要求6位，文字算术题按题面作答。
200返回：
```json
{"requestId":"43c05877-35b9-485e-a1fd-cf20551223e0","activityToken":"<captchaId>.<64位随机hex>","captchaToken":"<64位随机hex>","expiresAtMs":"1791792060000"}
```
Token兑换原子执行，一次挑战只兑换一次，TTL不延长。令牌只保存摘要并绑定用户/requestId/活动/SKU/epoch；不能用于其他请求。兑换响应丢失可重新获取验证码，以相同requestId获取新凭证；此步骤不扣库存。令牌签发和购买均不信任客户端价格/身份。

## POST /api/seckill/buy

认证与上述双凭证必需。动态秒杀地址采用随机活动令牌校验；隐藏路径不替代认证。新请求的双凭证校验与库存/资格/预扣/pending记录处于同一次Lua，挑战与ledger具有同一Cluster hash tag。合法重放在凭证检查前返回旧请求，不再次扣减。
```json
{"activityId":"1","skuId":"1","requestId":"43c05877-35b9-485e-a1fd-cf20551223e0","captchaToken":"opaque-proof","activityToken":"opaque-activity-token"}
```
首次通过同连接的因果写入屏障与WAITAOF本地刷盘边界后202；返回下例核心字段，也包括状态查询协议中的可空订单字段：
```json
{"requestId":"43c05877-35b9-485e-a1fd-cf20551223e0","reservationId":"04a7fd99-bdf0-4c3c-a16a-983bc96e3db3","requestState":"RESERVED","statusUrl":"/api/order/status?activityId=1&skuId=1&requestId=43c05877-35b9-485e-a1fd-cf20551223e0"}
```
重复同范围请求200并返回当前结果，不再次预扣；活动结束也允许合法重试获取已有结果。响应受理不等于订单已创建或已支付。刷盘确认未知返回503 ACCEPTANCE_UNKNOWN，原ID查询，不自动回补。资格/凭证检查前先处理已认证的合法幂等重放，避免凭证一次消费导致重试无法查结果。

## GET /api/order/status

认证必需。query二选一：orderId；或activityId+skuId+requestId，不可混用。
```json
{"requestId":"43c05877-35b9-485e-a1fd-cf20551223e0","reservationId":"04a7fd99-bdf0-4c3c-a16a-983bc96e3db3","requestState":"ORDER_CREATED","orderId":"993c5340-43bd-4ca3-bef9-f278bc36e726","orderState":"PENDING_PAYMENT","amountFen":"1990","expiresAtMs":"1791792900000","failureCode":null}
```
订单尚未生成时订单相关字段为null。请求枚举 RESERVED/QUEUED/ORDER_CREATED/COMPENSATING/FAILED；订单枚举 PENDING_PAYMENT/PAID/CLOSED。查询以MySQL已落库终态为准，Redis在途状态作为补充，不回退已知终态。轮询500ms起步退避到3s，2分钟后提示稍后查，订单生成或失败后停止抢购结果轮询。

C++端点仍仅提供Redis在途/失败结果，按orderId或ORDER_CREATED请求返回503 ORDER_SERVICE_UNAVAILABLE。S4业务查询使用Java同路径（8082）；S5/S6代理统一把`/api/order/*`交给Java，以MySQL结果为准。Java在DB没有请求记录时读取Redis在途状态，已落库记录不被缓存覆盖。

## POST /api/order/pay

认证并校验归属，仅开发MOCK模式：
```json
{"orderId":"993c5340-43bd-4ca3-bef9-f278bc36e726","idempotencyKey":"b6bca05b-f9cd-4d71-bb63-2dcf64a12c10"}
```
200：`{"orderId":"...","orderState":"PAID","paymentId":"...","provider":"MOCK"}`。同键重试返回原结果；已支付不同键也不创建第二笔支付。价格读取订单。支付条件更新同时检查待支付和未过expiresAtMs；关闭或已过期返回409 ORDER_CLOSED。真实支付渠道和验签回调另增契约。

## 稳定错误码

| HTTP | code | 可重试 |
| --- | --- | --- |
| 400 | INVALID_ARGUMENT | 否 |
| 401 | UNAUTHENTICATED | 重新认证 |
| 403 | FORBIDDEN / INVALID_PROOF | 否 |
| 404 | NOT_FOUND | 否 |
| 413 | PAYLOAD_TOO_LARGE | 否 |
| 409 | NOT_STARTED / ENDED / SOLD_OUT / ALREADY_PURCHASED | 否 |
| 409 | STALE_EPOCH / REQUEST_CONFLICT / ORDER_CLOSED | 否 |
| 429 | RATE_LIMITED | 是 |
| 503 | NOT_READY / DEPENDENCY_UNAVAILABLE / ACCEPTANCE_UNKNOWN | 是，先查原ID |
| 503 | BACKPRESSURE / ORDER_SERVICE_UNAVAILABLE | 是，先查原ID |
| 500 | INTERNAL_ERROR | 是，先查原ID |

## 已实现健康接口

Java GET /health/live 返回200与进程UP。业务未启用时GET /health/ready为503；启用后检查002迁移、MySQL查询、消费者初始化和Redis PING/AOF always/noeviction，满足则200。健康接口不使用业务错误格式；就绪不代表生产HA或已验证容量。

C++ GET /health/live为进程UP；GET /health/ready检查Redis可达及AOF=always/noeviction，成功200，失败503。成功响应scope=seckill-and-Redis且mqIntegrated=false，不能作为全商城就绪。C++默认127.0.0.1:8083，为S3 RocketMQ gRPC8081留端口。

## GET /metrics

认证角色ADMIN必需，返回Prometheus文本。包括http_requests/errors、reserved（Lua成功）、accepted（202持久化确认）、acceptance_unknown、replay、rate_limited及处理时长微秒总和。预扣/受理/拒绝分开统计；P95/P99及端到端下单延迟在S7实测。日志只有path/status/traceId/rtUs，不记录Bearer、验证码、双凭证或请求体。

## S5 管理商品列表与前端接入

新增 `GET /api/admin/goods`，Bearer ADMIN 必需，返回 `{items:[{goodsId,skuId,title,description,imageUrl,enabled,priceFen,unallocatedStock}]}`。按 goodsId 降序，最多 100 条，包含下架商品；enabled 为布尔，ID/金额/库存按既有 wire 规则为字符串。普通用户 403、未登录 401。用于后台编辑/下架/重新上架，不暴露给公共商品列表。

前端 hash 页面和同源代理见 [前端运行说明](FRONTEND-RUNTIME.md)。`/api/seckill` 到 C++，包括 `/api/order/status` 的其余 `/api` 到 Java，避免 C++ 在途查询覆盖权威订单接口。客户端保持 requestId/payment idempotencyKey，未知受理先查询，不提交客户端金额或用户身份。

## V009 运动鞋展示属性

003_sneaker_attributes增量迁移加入skus.size_eu/category/colorway。GET /api/goods、GET /api/goods/{id}和ADMIN商品列表新增`sizeEu/category/colorway`字符串；既有goods/sku/price/stock字段保留。GET /api/activities新增十进制字符串`initialStock`，与availableStock一起仅用于DB订单库存占用快照，不是实时Redis预扣百分比。

ADMIN `PATCH /api/admin/skus/{id}`严格body `{sizeEu,category,colorway}`。sizeEu允许空或35–50及半码，category允许空/跑步/篮球/休闲/训练，colorway≤64字符。库存父行锁下若任何activity_stock已引用SKU返回409 SKU_IN_USE；否则仅更新展示属性，不改变库存/价格。USER403、未知SKU404、无效值400。服务就绪需002和003迁移；运行前用data.py migrate应用新增迁移，不改历史SQL。

ADMIN `POST /api/admin/goods/{id}/skus`严格body `{sizeEu,stock}`，201返回`goodsId/skuId/sizeEu/unallocatedStock`。尺码必填且为35–50范围（含半码），库存为1–100,000,000；在事务中锁鞋款行、拒绝同鞋款重复尺码（409 `SKU_SIZE_EXISTS`），新SKU继承鞋款首SKU的标价、类别与配色，库存独立且未分配。USER403、未知鞋款404、参数非法400。创建新尺码不影响原SKU/活动；新SKU需在活动页单独分配活动库存并激活。SKU新增和未分配SKU的属性维护均锁定鞋款行并检查尺码唯一，所有经管理API的同款变更串行执行。

前端尺码按钮只展示该鞋款真实存在的SKU；尺码变体使用独立skuId和未分配库存，可分别建活动并购买。清单不扣库存，quantity仍1；支付和受理保持原契约。后台已支持新增尺码SKU，不支持跨尺码库存共享或合单结算。

## S6 同源部署入口

S7补充：C++业务线程在任何写操作前进行PING连通探测，旧连接断开仅重试该只读探测一次；Lua/库存/WAITAOF未知结果依然不重试。既有404账本缺失、503 BACKPRESSURE/ORDER_SERVICE_UNAVAILABLE/ACCEPTANCE_UNKNOWN契约保持。对账为运维CLI，无新增公开HTTP接口，输出与退出码见[OPERATIONS](OPERATIONS.md)。

默认浏览器地址 http://localhost:18080。业务路径/请求响应保持上述契约：`/api/seckill/*` 路由 C++，其余 `/api/*` 路由 Java。`/health/live` 为 Nginx 存活，`/health/order` / `/health/seckill` 为对应上游就绪，不代表完整容量达标。Nginx API/IP限流可能返回 HTTP429；请求体上限16KiB，超限413。客户端仍使用原 requestId 查询受理结果，不自动换ID重试。

Nginx覆盖客户端转发头，后端仅信任配置的单个网关IP；默认直连不信任。API/CAPTCHA不缓存；访问日志不记录查询参数、Bearer或请求体。部署配置和私有端口见[DEPLOYMENT](DEPLOYMENT.md)。
