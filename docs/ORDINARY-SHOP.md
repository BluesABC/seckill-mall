# 普通商城闭环（T059）

用户要求由秒杀演示补齐完整商城，本轮以“普通鞋款购买到收货”的本地演示闭环为边界，继续使用模拟支付、手工物流。核心对象为真实SKU、购物车数量、收货地址、订单明细快照、付款/退款凭证、发货单号。前端延续SNKR//DROP黑白运动视觉，图片引用已有原创鞋款，操作页重点是数量、金额、地址和下一步动作，不改造商城主视觉。

## 范围

商品搜索/分页、真实尺码、账号认证、秒杀原链路沿用已有实现。新增普通原价购买、服务器购物车（最多20个SKU，每码1–10双）、收货地址（每用户最多20条）、单次至多20个SKU原子结算、15分钟待支付订单、模拟支付、未付款取消、未发货全额退款、管理员手工发货、用户确认收货、管理员审计补货和本地账本核对。只支持CNY，演示免运费。订单页面分普通订单与原秒杀订单入口。

## 库存与状态

普通订单只消费skus.unallocated_stock；秒杀库存仍须先通过管理API划拨到activity_stock。普通结算与活动划拨均使用同一SKU行的条件更新，不重复售卖。普通订单独立shop_orders/shop_items，不伪造秒杀reservation或活动。

PENDING_PAYMENT → PAID → SHIPPED → DELIVERED。
PENDING_PAYMENT → CLOSED（取消/超时）释放普通库存一次。
PAID → REFUNDED（未发货取消型全额模拟退款）释放普通库存一次；REFUNDED不能再次支付。
已发货不允许直接退款；退货验收/入库需要后续独立流程。与原秒杀的“仅财务模拟退款不退货”语义不同，普通页面明确写“未发货全额退款”。

结算先锁用户行，按skuId升序锁SKU，任一商品不可售/库存不足整单回滚。重试键按用户唯一，保存商品/数量/地址ID指纹，不同参数复用同键返回409；商品金额从服务端加锁快照读取。订单操作锁订单后按SKU升序释放；支付、退款、取消、发货互斥。后台维护每秒扫描到期普通订单，同时列表/详情/操作先补扫当前用户到期单。地址和商品名称/尺码/单价保存快照，后续改名删地址不篡改已下单信息。

## 操作

详情选择尺码后“立即购买”或“加入购物车” → 添加地址 → 合并结算 → 普通订单“模拟支付” → 管理员普通订单发货管理填写承运商/单号 → 用户确认收货。未支付可取消；未发货可全额模拟退款。管理员可在同页按SKU登记补货，沿用原幂等键重试不会重复增加库存。秒杀清单和普通购物车各自有明确名称，原秒杀功能保持。

## 接口

- GET/POST `/api/shop/addresses`，POST `{recipient,phone,address}`；DELETE `/api/shop/addresses/{id}`。
- GET/PUT `/api/shop/cart`，PUT `{skuId,quantity}`设置绝对数量；DELETE `/api/shop/cart/{skuId}`。
- POST `/api/shop/checkout`，`{items:[{skuId,quantity}],addressId,idempotencyKey}`，ID/数量均十进制字符串，幂等键UUID。
- GET `/api/shop/orders`（最近100单）、GET `/api/shop/orders/{id}`；返回独立普通订单与明细、地址/金额快照，时间毫秒、金额分均字符串。
- POST `/api/shop/orders/{id}/pay|cancel|refund|receive`，`{idempotencyKey}`。
- GET `/api/admin/shop/orders`（最近100单），POST `/api/admin/shop/orders/{id}/ship`，`{carrier,tracking}`。已发货同单号重试幂等，不同单号409。
- POST `/api/admin/shop/restock`，`{skuId,quantity,idempotencyKey}`，仅增普通未分配库存，每次至多100万双，总未分配库存至多1亿双。

所有用户接口检查归属，管理员接口服务器校验角色；客户端不能提交价格、用户ID或状态。新增迁移005、006、007需在新版本启动前执行。`python scripts/reconcile-shop.py`执行一致性快照只读状态/金额核对，不能证明全部历史库存守恒，也不自动修数据。

## 验收与边界

WSL真实HTTP交易/并发/权限回归与真实浏览器操作分别记录。测试使用独立数据库/账号/商品，不删除用户数据卷；浏览器夹具结束后下架自有测试鞋款，保留订单审计。

本次不包含真实收款/寄送、退货入库、优惠券、发票、跨境税费、生产HA/TLS/NVDA认证。秒杀订单通过独立履约表补充地址和手工发货，不改变原PAID/Redis库存事实；已发货后原模拟退款接口拒绝退款。管理员普通订单列表当前上限100单，商业运营规模化前需要游标分页/归档及隐私保留策略。上线门禁仍按临时基线复核，不宣称生产商城已完成。

## 秒杀履约补充

T063起，新秒杀订单必须先提交本人完整收货地址快照，再抢购；订单和履约信息同事务创建。下述已付款修改地址接口保留给历史维护/未发货变更，不再作为首次填写收货信息的步骤。普通/秒杀订单的终态删除与取消入口见[收货与删除说明](ORDER-SHIPPING-DELETE.md)。

GET `/api/shop/seckill/orders` / `/api/admin/shop/seckill/orders` 为本人/管理员履约视图。POST `/api/shop/seckill/{id}/address` body `{addressId}`，仅本人已支付未退款未发货可设置地址。POST `/api/admin/shop/seckill/{id}/ship` body `{carrier,tracking}`；POST `/api/shop/seckill/{id}/receive` body `{idempotencyKey}` 确认收货。地址/物流快照保存到shop_seckill_delivery。退款与发货争用原订单行锁，已发货不能直接退款；秒杀退款仍不恢复活动库存或资格。秒杀订单视图的SHIPPED/DELIVERED/REFUNDED是履约与财务合成状态，原订单表PAID保留其已支付事实。
