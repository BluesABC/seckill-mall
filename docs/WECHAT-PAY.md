# 微信 Native 扫码支付接入（T060）

状态：代码与本地验证已实现；用户尚无微信商户号，真实渠道联调未完成。当前本机保持MOCK，页面明确显示“微信 Native 扫码支付尚未配置商户信息，当前不可收款”。本地测试替身不是微信官方沙箱，也不是收款凭证。

## 采用方案与依据

电脑网页使用Native扫码，直连商户APIv3、公钥模式、CNY全额支付/退款；普通SHOP订单与SECKILL订单均支持。官方Java SDK固定0.2.17，负责商户请求签名、微信响应验签、回调RSA验签及APIv3 AES-GCM解密。二维码用本地ZXing3.5.3生成PNG，不向第三方二维码网站发送支付链接。

- [官方Java SDK](https://github.com/wechatpay-apiv3/wechatpay-java/tree/v0.2.17)
- [微信Native下单](https://pay.wechatpay.cn/doc/v3/merchant/4012525171)
- [微信支付公钥验签](https://pay.wechatpay.cn/doc/v3/merchant/4013053249)
- [Native接入易错点：主动查单、确认关闭后释放库存](https://pay.wechatpay.cn/doc/v3/merchant/4054257695)

## 必须由商户提供的信息

| 项目 | 本机配置 | 说明 |
| --- | --- | --- |
| 已开通Native的直连商户号 | WECHAT_MCH_ID | 当前暂无，须自行申请/开通 |
| 与商户绑定的AppID | WECHAT_APP_ID | 不是商户号或AppSecret |
| 商户API证书序列号 | WECHAT_MERCHANT_SERIAL | 签名所对应商户证书序列号 |
| 商户API私钥 | merchant_private_key.pem | 从只读文件读取，不发送到聊天、不提交仓库 |
| 微信支付公钥ID | WECHAT_PAY_PUBLIC_KEY_ID | 与商户证书序列号不同，用于识别微信验签公钥 |
| 微信支付公钥 | wechat_public_key.pem | 仅支持当前配置的公钥ID；轮换需更新并复验 |
| 32字节APIv3密钥 | api_v3_key | 文件原文，可有末尾换行；不是APIv2密钥 |
| 公网HTTPS回调域名 | WECHAT_NOTIFY_URL | 必须以/api/payments/wechat/notify结尾 |

回调还需要同域名的 `/api/payments/wechat/refund-notify`。当前默认Nginx仅监听本机回环HTTP，不具备公网TLS回调能力；不要把填了HTTPS字符串当作已验证域名、证书或回调可达。不得用真实资金给无实物交付承诺的演示商品作生产销售。

## 配置与启用

默认不加载微信覆盖层，不出网收款。先在项目目录之外准备私有目录，内放上述3个文件。容器以UID10001运行，须有只读权限；不要全局放宽密钥权限。示例Linux目录可使用目录750、文件640并授予应用组读取，具体属主按部署平台设置。

复制 `deploy/.env.wechat.example` 为Git忽略的 `deploy/.env.wechat`，只填写标识符、HTTPS通知URL和私有目录的WSL/Linux绝对路径。私钥和APIv3值不写进env或Compose。`deploy/compose.wechat.yml`将目录只读挂载到/run/wechat，并显式启用MALL_PAYMENT_PROVIDER=WECHAT；缺字段/密钥无法读取/密钥长度不对会拒绝启动，不会静默转为收款成功或生成假码。

商户信息、公网TLS及环境准备好后，从WSL项目根目录运行：

```bash
MALL_WECHAT_ENV=deploy/.env.wechat bash scripts/stack.sh up
```

该入口构建源码、执行增量008/009迁移并启动服务；首次切换应先备份数据库、核对现有订单/密钥及迁移状态。保持已有MySQL凭据与数据卷，不通过改env密码来覆盖旧数据库。管理员生产账户应使用强密码；已有本机短密码演示账户不能直接视为生产配置。

有在途微信支付或退款时必须保留对应商户配置，不要切回MOCK来解决故障。即使切回，后端仍会阻止旧模拟接口绕过微信意图，也不会擅自释放这些库存。商户号/AppID/公钥变更须先安排在途交易迁移和回调复验。启用前必须升级全部订单写入和关单实例，不能新旧支付逻辑混部；本轮只验证单实例本机升级。

## 支付与退款流程

1. 订单先创建，金额来自服务端订单快照。本人申请Native支付时，wx_payments先持久化唯一意图和稳定out_trade_no，再在DB事务之外调用微信。普通订单和秒杀订单不会共享或伪造预留。
2. 只有SDK已验签的预下单响应才生成二维码。扫码页跳转、二维码生成成功、客户端按钮都不能把订单改成PAID。
3. 支付通知和主动查单共用落账逻辑，核对商户、AppID、CNY、订单号、总金额和交易号。重复通知不重复记账；秒杀支付继续写原ORDER_PAID outbox，不在回调事务中改Redis。
4. 未确认渠道关闭时，本地到期任务不会释放库存。SDK确认CLOSED后才关本地单并一次释放；网络超时/结果未知保留意图并继续查单。ORDER_NOT_EXIST等无法构成关闭证明的情况可能继续占用库存，须先排查商户配置并获得渠道关闭事实，不能手改数据库强行“成功”。
5. 用户只可申请未发货全额微信退款；先持久化稳定out_refund_no和REFUNDING，再调用渠道。PROCESSING不是已退款，只有验证渠道SUCCESS才落账。普通未发货订单退款成功后恢复普通库存一次；秒杀退款仍只恢复资金，不恢复活动库存或资格。
6. 已关闭订单异常收到真实支付成功通知时，不复活订单/库存，而是持久化原路退款补偿意图；退款未知继续持有REFUNDING，不能假称退款已到账。
7. 微信异常退款进入REVIEW，禁止继续发货。管理员可以重新向渠道核实，不存在强制置支付成功/跳过签名的入口。商户平台绕过本应用手工发起的外部退款需要另行人工对账，不自动导入到本地订单。

后台每轮完成后间隔5秒、单轮至多检查10个在途意图；本人查单也共用每意图5秒查询租约；预下单使用独立15秒租约，避免后台查询阻塞二维码恢复。已成功收款不会被后台永久高频轮询。此为保守默认值，非生产容量承诺；需按商户接口限额及真实压测调整。SDK网络连接超时3秒、读写5秒，失败不清除持久意图。回调要求单份签名头、5分钟时间窗及匹配事件类型，依赖服务器时钟同步。

## HTTP接口

用户接口均从Bearer会话取身份，只允许本人订单；金额和商户号不接受客户端传入。

| 接口 | 请求 | 结果 |
| --- | --- | --- |
| GET /api/payments/config | 无 | provider、wechatConfigured；不返回密钥或路径 |
| POST /api/payments/wechat/native | {orderKind,orderId} | PREPAY+本地qrImage，或已持久化状态 |
| GET /api/payments/wechat/status | orderKind、orderId | 主动查单/退款与权威状态 |
| POST /api/payments/wechat/close | {orderKind,orderId} | 渠道确认后关闭，未知返回503 |
| POST /api/payments/wechat/refund | {orderKind,orderId} | REFUNDING或REFUNDED；不等同到账承诺 |
| POST /api/payments/wechat/notify | 微信原始JSON及签名头 | 验签/落账完成后204；失败不确认成功 |
| POST /api/payments/wechat/refund-notify | 微信原始JSON及签名头 | 同上 |
| GET /api/admin/payments/wechat | ADMIN | 最近100笔状态/渠道单号/错误码，无私钥 |
| POST /api/admin/payments/wechat/recheck | ADMIN，{orderKind,orderId} | 重新查询渠道并按已验证事实推进状态 |

orderKind为SHOP或SECKILL，orderId是本地UUID。主要错误：WECHAT_NOT_CONFIGURED、USE_WECHAT_PAYMENT、WECHAT_PAYMENT_MANAGED、WECHAT_RESULT_UNKNOWN、WECHAT_CLOSE_UNKNOWN、WECHAT_REFUND_UNKNOWN、WECHAT_PAYMENT_MISMATCH、INVALID_WECHAT_NOTIFICATION。未知结果必须查询原单，不能换新订单号再次付款。

## 本地验证与真实验收的边界

`bash scripts/test-wechat-wsl.sh`运行官方SDK密码学测试，并创建自有MySQL库执行进程内渠道替身状态机验证；最终删除自有测试库，不触碰业务卷。不提供测试成功HTTP回调或可配置假微信域名。

`source scripts/env-wsl.sh && node tests/browser/wechat-ui.mjs`是界面夹具：覆盖未配置不出码、真实模式隐藏模拟按钮、二维码/查询/关闭/退款处理中与确认，以及390/768/1440布局。截图带“非真实收款二维码”标记。

本地通过不能替代以下真实商户验收：实际小额支付和全额原路退款；公网HTTPS回调与重试；支付/关单竞争；跨进程故障恢复；公钥轮换；与微信交易/退款账单逐笔核对。当前未实现渠道账单下载/自动差异修复、部分退款、服务商分账、JSAPI/App支付及发货后退货退款。真实联调前不得宣称可正式收款或达到生产上线标准。

真实WECHAT模式下，没有已确认微信支付意图的历史MOCK订单不能直接发货；保留历史单据，不把演示支付当成真实收款。
