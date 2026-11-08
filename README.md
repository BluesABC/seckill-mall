# SNKR//DROP · 运动鞋秒杀商城

Vue 3 / TypeScript / Tailwind 前端，C++ 秒杀服务，RocketMQ 官方 C++/Java SDK，Spring Boot 订单服务，Redis Lua 原子预扣、MySQL 事务库存与幂等订单。

![运动鞋商城：跑者主视觉与运动鞋商品图](tests/reports/wsl/sports-ui/desktop-home.png)

支持商品浏览、每码独立库存的真实 SKU 尺码、用户认证、图片验证码抢购、异步订单查询、模拟支付、超时关闭与幂等回补、商品/活动管理。后台可为既有鞋款新增尺码，并按 SKU 单独配置活动；项目使用原创演示品牌和图片，Nike/Adidas 仅作为用户指定的视觉参考。

## 启动（WSL2 / Linux）

模拟支付演示：下单生成待支付订单 → “去支付” → 选择“微信扫码（模拟）” → “下一步”弹出二维码 → “模拟已支付” → 服务端确认支付成功。无需商户号，二维码不收款，详见[操作说明](docs/DEMO-CASHIER.md)。

秒杀前须填写并选择收货人、联系电话和完整地址；订单创建时保存快照。已取消、已退款或已完成订单可在订单列表点击“删除订单”，详见[收货与删除说明](docs/ORDER-SHIPPING-DELETE.md)。

安装 Docker Engine 或启用 Docker Desktop 的 WSL 集成，确认 `docker info` 和 `docker compose version` 可用。

```bash
python3 scripts/prepare-deploy.py
bash scripts/stack.sh up
```

浏览器访问 <http://localhost:18080>。默认启动 Redis 一主两从和三个 Sentinel。管理账号为 `admin`，密码位于本机生成的 `deploy/.env.stack`，请自行保管；它不会提交到仓库。首次构建包含官方 RocketMQ C++ SDK，耗时取决于网络与机器资源。完整配置、持久化和排障见 [部署说明](docs/DEPLOYMENT.md)。

## 秒杀活动时间与重新开场

首次空库启动时，活动时间按运行时生成，从启动前一分钟开始、持续24小时，不依赖上传日期。其他人克隆后按上面的命令启动，即可注册参与。

已有活动到期后，可以新开七天演示场次：

```bash
bash scripts/stack.sh renew-demo
```

仅处理原创演示鞋款，跳过未到期场次，从每码未分配库存中最多划拨10件；保留旧活动、订单与库存账本。库存不足会跳过，不会无限补货。旧项目更新后先执行 `bash scripts/stack.sh build` 更新工具镜像。若曾手动改过管理员密码，需先让本机 `deploy/.env.stack` 中的 `MALL_ADMIN_PASSWORD` 与现有账号一致。不要并行运行开场命令；中断留下READY活动时，在管理后台激活该场次后再重试。

## 秒杀模拟支付与退款

秒杀订单创建后可在订单详情通过“去支付”打开模拟收银台，完成后可查看支付凭证，并确认“模拟全额退款”。退款不产生真实资金变动，不恢复库存或购买资格；同一支付只能全额退款一次。刷新后保留服务端结果。使用范围、迁移与只读对账见[模拟支付说明](docs/MOCK-PAYMENTS.md)。

## 普通购买与收货

选择鞋款尺码后可“立即购买”或“加入购物车”，添加收货地址后合并结算。支持模拟支付、待付款取消/超时关闭、未发货全额退款、管理员手工发货、用户确认收货与审计补货。普通库存与秒杀活动划拨库存分开，不重复出售。

[购物车](http://localhost:18080/#/shop/cart) · [普通订单](http://localhost:18080/#/shop/orders) · [秒杀收货](http://localhost:18080/#/shop/seckill) · [管理员发货与补货](http://localhost:18080/#/shop/admin)。秒杀订单从下单时保存的地址快照读取收货信息。待支付订单卡片显示剩余时间，到期由服务端关闭；发货后不能直接退款。

范围、接口与状态机见[普通商城说明](docs/ORDINARY-SHOP.md)。本项目是可运行演示：不真实扣款、不寄送实物；退货入库、优惠券、发票及生产上线门禁仍未完成。

## 微信扫码支付（接入代码，本地验证阶段）

普通订单与秒杀订单已增加微信Native预下单、二维码、查单/关闭、全额退款和验签通知处理。**当前尚无商户号，默认仍为MOCK，不能真实收款**。本地测试替身不是微信官方沙箱。

后续商户资料、只读密钥挂载、公网HTTPS和真实验收步骤见[微信接入说明](docs/WECHAT-PAY.md)，配置模板为[.env.wechat.example](deploy/.env.wechat.example)。不要向聊天或仓库上传私钥/APIv3密钥。

## 账号与客服

登录后可通过顶部圆形头像查看本人资料并退出。客服浮窗支持拖动、调整大小和最小化，保留“查看我的订单”入口。客服可按名称和尺码查找商品，用户确认 SKU 和数量后才加入购物车。默认可用商城知识库，模型接入需要服务端配置，见[客服配置](docs/SUPPORT-MODEL.md)。微信网站扫码登录仍待开放平台应用与回调域名。

## 导航

- [项目总览与目录](docs/README.md) · [架构](docs/ARCHITECTURE.md) · [API](docs/API.md) · [决策记录](docs/DECISIONS.md)
- [唯一阶段进度记录](docs/PROGRESS.md) · [待办](docs/TODO.md) · [已知问题](docs/BUGS.md)
- [WSL 测试](docs/TESTING.md) · [验收报告](tests/reports/) · [项目 Skill](.agents/skills/seckill-mall/SKILL.md) · [UI Skill](.agents/skills/seckill-mall/UI_Skill.md)

部署面向本机演示，只有 Nginx 绑定回环地址。支付提供者为 MOCK；RocketMQ 单 Broker，未验证高可用。本机容量、库存对账及 Sentinel 演练证据见[进度记录](docs/PROGRESS.md)。生产上线条件见[临时基线](docs/BASELINE-TARGETS-v0.1.md)。
