# S6 阶段验收报告（V010）

日期：2026-10-13（Asia/Shanghai）。关联 T024、G07/G08、D09。结果：完整源码容器构建与 WSL 实际运行验收通过；容量、HA、真实支付与故障收敛窗口仍属于 S7/待确认范围。

## 交付

四类 Dockerfile 构建 C++/官方 RocketMQ SDK、Java verify、Vue/Nginx 与 Python迁移工具；完整 Compose 独立 Redis/MySQL/NameServer/Broker Proxy/relay/order/seckill/gateway，命名卷与一次性初始化、增量迁移、仅空库运动鞋种子和真实健康检查。随机本机env，只有回环 Nginx 发布端口，C++/Java UID10001。可信代理、动态Docker DNS、交易不自动重试与缓存/安全头均已接入。

可复现启动见 [DEPLOYMENT](../../docs/DEPLOYMENT.md)，运行入口 `python3 scripts/prepare-deploy.py` / `bash scripts/stack.sh up`，地址 http://localhost:18080。不会覆盖已有库存或删除业务卷。

## 实际环境与命令

- Ubuntu24.04.4 LTS / WSL2 Linux6.18.54.1；Docker client/server29.8.2，Compose5.6.0，Python3.12.3，Node22.20.0。容器原生 GCC/Java21/Node源码构建，无Windows二进制替代。
- `bash scripts/test-s6-wsl.sh`：独立 `seckill-mall-s6`，干净命名卷，构建/初始化/业务/浏览器，最终退出0。
- `bash scripts/test-s2.sh`：真实 HTTP/Redis23项、CTest3/3、契约检查退出0。
- `MALL_DB_PORT=13306 MALL_DB_USER=root MALL_DB_PASSWORD=s1-local-root-only MALL_REDIS_URL=redis://127.0.0.1:16379/0 build/wsl/venv/bin/python tests/test_s1.py`：随机自有DB/key的存储/Lua28项退出0；本次没有重做S1 SIGKILL恢复测试，不改写历史证据。
- Shell语法、Python编译、Markdown链接/契约与skill验证通过。构建阶段 Maven verify / Vue 类型检查与生产构建通过。

## 实际结果

[最终JSON](wsl/s6-deploy.json)：10/10，业务套件62.342秒，不含构建/干净初始化/浏览器。完整日志见 [WSL最终日志](wsl/s6-deploy.log)。

| 场景 | 结果 |
| --- | --- |
| 全容器就绪 / Nginx静态页面、CSP、缺失资源404 | 通过 |
| 注册/验证码/C++→官方MQ→Java→MySQL订单/客户端重复受理 | 通过 |
| MOCK支付及重复幂等键 | 一笔成功支付 |
| 自动关闭 / outbox持久回补 | CLOSED1，Redis库存恢复10 |
| 重复seed保留商品/活跃库存 | 商品仍4，无重置 |
| 内部可信代理身份 / 用户伪造转发头 | 可信网关生效，用户头被覆盖 |
| 发布端口 / C++与JavaUID | 仅127.0.0.1:18080，UID10001 |
| order容器重建 / Nginx DNS | 读取既有PAID订单成功 |
| 整栈正常重启 | 会话、PAID1/CLOSED1/订单2/支付1持久化 |
| 库存守恒 | DB初始库存=可售+未关闭订单量；Redis对应库存9/10，非负 |

[生产页面结果](wsl/s6-ui/results.json)：桌面1440与手机390，9张图片全部加载，无控制台错误/横向溢出；[桌面截图](wsl/s6-ui/desktop.png)、[手机截图](wsl/s6-ui/mobile.png)实际查看。该浏览器检查是部署资源/CSP/布局复验，S5完整16项交互验收见V009。

## 修复与边界

首次网络下载遇HTTP502与Maven预下载TLS中断，改为官方HTTPS/CA/签名包、必要依赖构建缓存与verify，未关闭验证。首次脚本发生WSL cwd句柄失效，改绝对路径并重新cd；超时夹具原值1违反数据库时间约束，修正为created_at_ms+1，保留真实约束。失败记录见 [首次记录](wsl/s6-deploy-attempt1.log)；中间通过记录见 [复验记录](wsl/s6-deploy-attempt2.log)。最终为新增守恒断言再次在干净自有测试卷完整运行；只清理该测试创建的夹具，不清理开发/用户卷。

验证码答案摘要与到期时间只在自有测试Redis/SQL中注入，HTTP没有绕过入口。正常整栈重启不等于SIGKILL/HA，也没有验证重启后新下单的恢复SLA；S4-005仍需S7测量/改善。公网TLS、备份恢复、容量目标/资源预算、普通购物车/多规格创建/分页/图片压缩及非视觉验证码仍按BUGS/TODO处理。MOCK支付不是实际收款。

公开GitHub交付包含源码、项目级Skill、UI参考与验收资料；不包含本机env、密钥、构建缓存和运行数据。发布前核查实际本机随机密码及GitHub令牌/私钥模式，无匹配项；具体仓库地址由本次交付确认。
