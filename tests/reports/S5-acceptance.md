# S5 阶段验收报告 — V008

日期：2026-10-13，Asia/Shanghai。T025；关联 G01/G03/G09/G10/G13。结论：**S5 前端阶段完成**，S6 部署与 S7 容量/收尾尚未完成。

## 交付

拾间 SHIJIAN 简约精品商城：原创概念商品摄影、首页、真实商品列表/搜索/排序、详情/校时倒计时、登录注册、图片验证码、稳定 requestId 抢购与查询、订单列表/详情、MOCK 支付/超时关闭、管理页面及手机布局。管理覆盖商品编辑/下架/重新上架，活动创建/开启/结束，用户启禁，全站订单，恢复查询/重放入口。

新增 ADMIN `GET /api/admin/goods` 包含隐藏商品，其余交易接口保持 S4 契约。未知受理只查/重试同一 ID；支付使用稳定幂等键；消息受理不能显示为订单或支付成功。接口失败显示重试提示，不填充假商品。项目 skill 已补充运行/状态参考。

## 环境与命令

- WSL2 Ubuntu **24.04.4 LTS**，内核 **6.18.54.1-microsoft-standard-WSL2**；工程在 `/mnt/e/c++project/seckill-mall`。
- Linux Node **22.20.0**、Java **21.0.12.1**、Maven **3.8.7**；Docker **29.8.2**。Redis **7.2.11**、MySQL **8.4.11**、RocketMQ **5.3.2** NameServer/Broker/Proxy，官方原生 C++ / Java 5.2.2 SDK。
- Playwright **1.56.1**、axe-core/playwright **4.11.0**、Linux Chromium **141.0.7390.37**，中文字体 Noto CJK。浏览器与 Node 包在 Linux 独立目录，未调用 Windows `.exe/.cmd`。
- 系统浏览器依赖/中文字体安装独立执行；步骤见 [前端运行说明](../../docs/FRONTEND-RUNTIME.md)。

完整入口：

```bash
source scripts/env-wsl.sh
bash scripts/test-s5-wsl.sh
```

完整入口退出 **0**：Java 测试 1/1、打包成功，Vue 类型检查/生产构建通过，真实浏览器与 SQL 核对通过。日志：[s5-run.log](wsl/s5-run.log)。随后调整后台中文字段/零计数显示、失败指导文字，并补充恢复/失败展示条件测试；最终代码再次构建并执行：

```bash
source scripts/env-wsl.sh
cp -R src/web/src build/wsl/web/
(cd build/wsl/web && npm run build)
build/wsl/venv/bin/python scripts/storefront_runtime.py --test
```

最终退出 **0**，浏览器 **14/14**，SQL 核对通过；日志 [s5-final-run.log](wsl/s5-final-run.log)、逐项 [results.json](wsl/s5/results.json)、数据库 [sql.json](wsl/s5/sql.json)。最终静态产物 JS 102.47kB（gzip 38.87kB）、CSS 16.03kB（gzip 4.31kB）；此为构建体积，不是性能/容量验收。

## 实际覆盖与结果

| 验收项 | 结果及边界 |
| --- | --- |
| 原创图与真实首页/目录 | 3 件数据库商品；图片可解码，搜索/价格排序/空结果通过 |
| 注册登录与键盘 | 真实注册/登录/退出，原生 dialog 输入焦点、Esc 关闭和焦点恢复通过 |
| 验证码错误/刷新 | 服务拒绝错误答案，刷新保留 requestId；固定答案只在测试拥有的 Redis 私下设置 |
| 真实抢购/未知响应 | 真 C++受理后丢弃浏览器响应；官方SDK/RocketMQ/Java/MySQL生成同一订单，刷新可查询，没有另起请求 |
| 双击与模拟支付 | 快速双击不重复提交，真实MOCK支付记录仅1条，刷新后服务器仍为PAID |
| 关闭 | 第二笔真实订单；私下提前 expires_at_ms，后台真实任务关闭，页面撤去支付按钮 |
| 售罄 | 仅测试拥有的ledger设置0并恢复，买按钮禁用；不把这项显示条件当库存并发测试 |
| 恢复/失败页面 | 明确注入 COMPENSATING/FAILED 查询响应，指导文字与无支付动作通过；没有宣称本次真实MQ链路产生了失败订单 |
| 移动布局/无障碍 | 1440×1000和390×844，无横向页面溢出；已检查首页/目录/dialog/详情/订单/后台的WCAG标签axe扫描0违规；人工复核截图 |
| 权限与后台 | USER页面限制及真实ADMIN接口403；ADMIN创建/编辑/下架/重新上架、活动启停、用户启禁、订单和执行恢复一轮通过；恢复队列为空，本次未声称真实前端重放了失败事件 |
| API失败界面 | goods 503明确注入并强制首次加载，显示错误/重新加载，恢复后读取真实目录 |
| JS异常 | 浏览器 pageerror 0 |
| SQL | 订单2条=唯一reservation2条，PAID1/CLOSED1，成功MOCK支付1；各活动 available≥0 且 available+有效订单占用=initial |

测试仅使用随机 `mall_s5_*` 数据库、`s5_*` Redis前缀、独立Topic/组。退出清理自己的进程/SQL/Redis，基础设施保持运行；Broker历史Topic/组未批量删除。库存守恒证据是这个功能夹具的结果，不是S7多用户压测。

## 截图与复核

- [桌面首页](wsl/s5/desktop-home.png)、[手机首页](wsl/s5/mobile-home.png)、[手机详情](wsl/s5/mobile-detail.png)。
- [桌面订单](wsl/s5/desktop-order.png)、[手机订单](wsl/s5/mobile-orders.png)、[管理页](wsl/s5/desktop-admin.png)。
- 原图与生成提示：[ORIGIN](../../src/web/public/assets/ORIGIN.md)，使用内置 imagegen；没有安装外部 GitHub 设计 skill。

首轮用户数量断言写错已修正；API失败测试首次只改hash未重新取数，改为reload后确实覆盖初始化失败；初始化清空错误提示与标题末字落单/隐藏商品编辑入口也已修复。历史失败日志 [s5-run-failed-2.log](wsl/s5-run-failed-2.log) 与结果文件保留用于追溯，最终判定以V008上述成功证据为准。

## 限制与下一阶段

MOCK支付、单Broker/Redis不代表生产支付或HA。S4-005的消费重启等待仍待S7优化；当前S5未重跑S1–S4故障套件，交易算法未改，新增只读管理端点已做真实权限/业务联调。

图片验证码没有语音/非视觉替代；列表100条尚无分页，原始PNG约2.1–2.6MB待网页优化。见BUGS S5-003/004；自动axe不等于完整无障碍认证。生产Nginx/TLS、服务Dockerfile/完整Compose、干净环境启动在 **S6**；高并发容量/对账/故障收尾在 **S7**。

CHECKPOINT: S5-V008-精品商城/真实接口/WSL浏览器与SQL验收/文档完成。
NEXT: S6-T024-服务容器、Nginx与全链路Compose。
STATUS: S5任务1/1完成，S6–S7未开始。

补充：静态契约、106处Markdown本地链接和项目skill quick_validate均退出0；本地展厅启动及 --stop 的归属校验/进程/自身数据清理已实际退出0，随后保留新的本地展厅供预览。
