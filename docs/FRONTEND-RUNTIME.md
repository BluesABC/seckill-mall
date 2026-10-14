# S5 前端运行与页面（运动主题修订）

关联 G01/G03/G09/G10/G13、T025。Vue 3.5.22 + TypeScript 5.9.3 + Vite 7.1.9；当前视觉方向为用户2026-10-13指定的运动鞋商城。SNKR//DROP 为项目概念品牌，原图来源与生成提示见 `src/web/public/assets/ORIGIN.md`。

## WSL 启动

先按 TESTING / ORDER-RUNTIME 启动 Redis、MySQL、RocketMQ，构建 Java JAR、C++ 服务和 relay。Node 使用 `source scripts/env-wsl.sh` 提供的 Linux 原生版本。

```bash
cd /mnt/e/c++project/seckill-mall
source scripts/env-wsl.sh
bash scripts/build-web-wsl.sh
build/wsl/venv/bin/python scripts/storefront_runtime.py
```

浏览器访问 `http://localhost:5173`。这个**本地展厅**创建随机独立数据库、Redis 前缀、Topic 与消费组；通过真实管理接口建立四款鞋与真实尺码活动，并启动 Java、C++、relay 和 Vite preview。管理员用户名 `admin`，每次随机生成的本地密码见 `build/wsl/s5-runtime.json`（忽略目录，不提交）。普通用户从页面注册，密码至少 12 字符。运行期间保持终端开放，Ctrl+C 清理自身进程、数据库和缓存；也可在项目根目录执行 `build/wsl/venv/bin/python scripts/storefront_runtime.py --stop`，校验进程归属后停止展厅。Broker Topic/消费组历史残留不自动删除，避免误删消息。这套 root/测试限流配置仅用于本地演示。

连接自己的开发服务：启动 Java/C++/relay 后运行 `cd build/wsl/web && npm run dev`。默认 Java 8082、C++ 8083；环境变量 `MALL_ORDER_ORIGIN`、`MALL_SECKILL_ORIGIN` 可指定地址。浏览器始终请求同源 `/api`；`/api/seckill` 先路由 C++，其余 `/api` 路由 Java。生产 Nginx 和容器一键部署在 S6，不使用 Vite preview 作为生产服务器。

## 页面与状态

| 地址（hash） | 功能 |
| --- | --- |
| `#/` | 原创跑者主视觉、真实鞋款/秒杀、运动类别 |
| `#/catalog` | 服务端关键词/运动类别/价格筛选、排序与分页加载更多、加载/空/失败状态 |
| `#/product/{goodsId}` | 鞋款画廊/尺码、活动价格/时间、服务端校时倒计时、售罄与未开启禁用、验证码 |
| `#/request/{requestId}` | 同一请求轮询；未知受理结果保留 ID，允许继续查询/重新验证同一请求 |
| `#/order/{orderId}` | Java 权威订单状态、支付截止、MOCK 支付、关闭状态 |
| `#/flash` | 场次筛选、活动时间、订单占用库存快照 |
| `#/cart` | 逐款抢购清单与参考合计，不锁定库存 |
| `#/orders` | 当前用户订单和本浏览器保存的抢购请求 |
| `#/admin` | 商品创建/编辑/下架/重新上架、活动创建/开启/结束、用户启禁、全站订单、恢复记录/重放 |

会话 token 仅存 sessionStorage，不保存密码。重新加载先验证会话；已过期或停用的会话清除并提示重新登录。请求记录保存在按 userId 分区的 localStorage，包含活动/SKU/requestId，不含密码/token。切换账号不查询其他用户记录，后端仍校验订单归属。ID/分金额保持十进制字符串，金额格式化使用 BigInt。

首次抢购先保存 requestId，再换取验证码和绑定凭证。并发点击由 busy 阻止，提交前标记请求在途。网络断开或 5xx **不能直接判失败**；继续查询原 ID，刷新页面仍保留。新验证码/重试仍使用同一 ID。请求轮询从 500ms 退避到 3s，120 秒暂停并提供继续查询；切页中止定时器和请求。PENDING_PAYMENT 每 3 秒查询一次，也在 120 秒暂停。支付使用按用户/订单持久的 idempotencyKey，异常后先查权威订单。

后台只显示管理员页面，同时服务端检查 ADMIN。新增只读 `/api/admin/goods` 返回含隐藏商品的列表，避免下架后无法在页面重新上架。公共目录由 `/api/goods/catalog` 提供服务端分页，默认每页12件、最大48件，并在数据库执行搜索、类别/价格筛选和排序；活动、订单及管理列表仍各有100条上限。恢复页面提供实际端点操作，空队列不能当作已验证前端重放了失败消息。

## 浏览器验收

```bash
bash scripts/test-s5-wsl.sh
```

首次系统依赖单独安装（Ubuntu root 或 sudo）：

```bash
source scripts/env-wsl.sh
cd build/wsl/browser
npx playwright install-deps chromium
sudo apt-get install -y fonts-noto-cjk
```

固定 Playwright 1.56.1、axe-core/playwright 4.11.0 和 Linux Chromium，依赖/浏览器与 Windows 隔离。测试会创建自身数据并清理；验证码答案、超时和售罄的确定性条件只在测试拥有的 Redis/SQL 私下设置，没有应用绕过端点。丢失响应在真实 `/buy` 已接受后由浏览器拦截；订单、MQ 与支付记录仍是真实链路。API 失败呈现测试使用单独明确的响应注入。

截图与逐项结果见 `tests/reports/wsl/s5/`，阶段结论见 `tests/reports/S5-acceptance.md`，分页回归见`tests/reports/S9-acceptance.md`。桌面 1440×1000，移动 390×844。WSL浏览器验收端口可通过`MALL_WEB_PORT`指定，默认15173，不会占用本机展厅5173。自动 axe 检查不等于完整无障碍认证；当前图片验证码没有语音替代，属于已知限制。

工具行为参照 [Playwright 浏览器安装](https://playwright.dev/docs/browsers)、[Vite 开发代理](https://vite.dev/config/server-options#server-proxy) 与 [preview 代理](https://vite.dev/config/preview-options#preview-proxy)。
