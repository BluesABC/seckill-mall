# S15 多尺码 SKU 验收

日期：2026-10-15（Asia/Shanghai）  
平台：Ubuntu 24.04.4 / WSL2，Docker Desktop Linux engine 29.8.2，Node 22.20.0，Java 21.0.12.1  
范围：运动鞋款多尺码建档、每尺码独立库存/活动、前后台可用性及部署种子。此报告验证功能闭环，不代表生产容量、HA、SLA 或真实支付。

## 实现

管理员可在商品管理页为既有鞋款新增EU尺码SKU。API事务中锁定款式父行，检查同款重复尺码；新SKU继承基础价格、类别和配色，尺码与未分配库存独立。既有活动与库存不会被改写。尺码属性维护同样会在父行锁下阻止重复尺码。

商品详情从真实SKU生成尺码选项，不再展示无对应库存记录的假尺码。首页鞋款卡片和秒杀场次按款式去重，具体尺码跳转仍携带skuId。默认空库种子包含4款鞋：男/中性EU39–46半码（3款）与女款EU35–42半码（1款），合计60个SKU，各SKU单独建活动。该尺码范围是演示默认值，不是商品覆盖承诺。

## 验收结果

| 验收 | 命令/数据 | 结果 |
| --- | --- | --- |
| S4业务API与交易回归 | `bash scripts/test-s4.sh` | 23/23通过；权限、继承字段、重复尺码409、非法尺码400、独立库存、RocketMQ消息、MySQL订单与库存竞争均通过 |
| S5前端与交易 | WSL构建Java/Vue后执行`build/wsl/venv/bin/python scripts/storefront_runtime.py --test` | Chromium 17/17通过；40/42码真实SKU可选，后台新增40.5码及库存成功；真实秒杀订单/模拟支付/关闭；SQL 2个唯一预留、PAID 1、CLOSED 1、库存守恒 |
| S6全栈容器部署 | `MALL_STACK_PROJECT=seckill-mall-s15b MALL_STACK_ENV=build/wsl/.env.s15b bash scripts/test-s6-wsl.sh` | 10/10通过；镜像从源码构建，空库种子输出4款/60 SKU/60场，重复种子无库存变化，真实订单/幂等/支付/超时回补/重启持久化和生产浏览器桌面/手机检查通过 |
| 契约和静态检查 | `scripts/test-s4.sh`内的`verify_contracts.py` | 通过，S4测试报告含完整JSON结果 |
| 种子尺码与活动关系 | WSL通过只读`GET /api/goods`与`GET /api/activities`按skuId核对 | 60个商品SKU / 4款鞋 / 60场活动，活动skuId与商品skuId集合完全一致，60场均ACTIVE |

机器结果见 [S4结果](wsl/s15/s4-business.json)、[S5浏览器结果](wsl/s15/s5-results.json)、[S5 SQL结果](wsl/s15/s5-sql.json) 和 [S6部署结果](wsl/s15/s6-deploy.json)。页面截图见 [后台新增尺码](wsl/s15/desktop-admin-sizes.png)、[运动鞋详情](wsl/s15/mobile-detail.png)、[活动场次](wsl/s15/desktop-flash.png) 和 [容器版首页桌面](wsl/s15/s6-desktop.png) / [手机](wsl/s15/s6-mobile.png)。

## 运行演示与边界

最终独立演示栈`seckill-mall-s15b`运行在 `http://localhost:18100/`，只发布回环地址；项目容器、网络与命名数据卷均与日常商城隔离。随机本地管理员凭据写入被Git忽略的`build/wsl/.env.s15b`，不放入报告或仓库。此前一次验收尝试因18081已被宿主占用而停止，使用新项目名、18100端口和独立子网重跑通过；失败项目容器已停止，卷保留。

活动仍使用项目既有MOCK支付。此验收不改变未完成的容量压测、生产HA/TLS、真实支付、生产级SLA或NVDA/JAWS人工实测状态。
