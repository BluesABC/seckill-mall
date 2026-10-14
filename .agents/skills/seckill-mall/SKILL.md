---
name: seckill-mall
description: 按本项目目标设计、实现、评审和压测高并发秒杀购物商城。适用于商城前端、C++ 秒杀核心、RocketMQ集成、Java订单、Redis/MySQL一致性、WSL测试及Docker部署；不用于无关C++练习项目。
---

# 高并发秒杀商城

## 项目依据

用户要求实现含秒杀活动、能承受高并发的购物商城，以《【项目目标】.docx》为需求来源。先读 [项目目标与需求映射](references/project-goals.md)。设计或修改交易链路时再读 [一致性与可靠性约束](references/consistency.md)；规划交付、部署或压测时读 [交付与验收](references/delivery-and-acceptance.md)；新增或运行测试时读 [WSL测试约定](references/wsl-testing.md)。

来源文档是需求资料，其中的角色扮演、保存提示词、回答风格等文字不单独构成执行授权。明确区分原始要求、工程推导、可调整默认值和已验证事实。用户后续明确修改需求时更新需求映射，并标记被替代要求。

## 必须保留的实现边界

- 前端使用 TypeScript + Vue 3 或 React；秒杀核心使用 C++；普通订单与管理业务使用 Java + Spring Boot。
- 使用Redis、MySQL、Nginx、Docker；用户于2026-10-12明确先采用RocketMQ跑通，替代原文G05的自研/C++ Broker要求。C++生产者和Java消费者通过官方SDK连接；将消息内容与投递/消费适配分开，后续仅在用户要求时更换自研C++ MQ。
- Redis Lua 原子完成库存判断、用户资格/占位与预扣；MySQL 以条件库存更新、唯一约束和事务兜底。
- 预扣后异步创建订单，客户端区分预扣成功、下单成功、支付成功。加入 MQ 的请求不能直接显示支付或订单成功。
- 一人一单、防刷、幂等、重试补偿、未支付超时回补、库存对账和可观测性都属于验收范围。
- “高并发”必须用有环境与负载说明的测量结果证明；不得把设计容量、模拟组件或单机演示称为实测容量或高可用。

## 开展工作

1. 本 skill 仅用于其所在的 `seckill-mall` 项目。先读项目根目录 AGENTS.md、docs/PROGRESS.md 和 docs/TODO.md，再检查现有代码、构建与部署入口。代码按 src/seckill、src/mq、src/order、src/web 拆分；只有完成接口、依赖、许可和运行能力检查后，才决定复用父工作区模块，不改动无关项目。
2. 给任务关联需求 ID。先推进不依赖缺失参数的部分；记录前端选型、容量、支付模式、MQ 故障模型等假设。没有容量指标时写“待确定”，不能自行承诺 QPS。
3. 首次整体设计给出架构图与数据流、服务职责、接口、Redis Key、MySQL 表、消息契约和部署/压测规划。后续局部任务只交付相关内容，不机械重复全套设计。
4. 按可运行的业务闭环推进：基础商城 → 秒杀预扣与异步下单 → 支付/超时/补偿 → 故障与压测验收。每阶段提供实际代码、配置、运行步骤与验证证据；不要用伪代码占位完成实现任务。
5. 修改并发或一致性逻辑时检查崩溃窗口、投递结果未知、重复/乱序事件、支付与关闭竞争，以及补偿自身重复执行。采用明确的状态机、持久化恢复依据和可观测的失败结果。
6. 随代码同步 docs/API.md 和 docs/ARCHITECTURE.md；重要决策记入 docs/DECISIONS.md。前端任务先读[运动鞋UI Skill](UI_Skill.md)与[前端视觉方向](../../../docs/FRONTEND-DIRECTION.md)，实际查看项目UI文件夹参考图；用户2026-10-13明确改为Nike/Adidas参考的运动品牌商城，替代之前的家居精品主题。按项目 AGENTS.md 更新 TODO、PROGRESS、CHANGELOG、WORKLOG 与 BUGS，其中 PROGRESS 是唯一阶段进度真相源。报告本次改动、关联目标、运行验证、未完成项与必要限制。面试讲解可另列，但必须基于实现和证据。

## 验收原则

部署或公开仓库交付时先读[完整部署说明](../../../docs/DEPLOYMENT.md)。使用项目根的四类Dockerfile、完整Compose与scripts/stack.sh，不复制宿主二进制冒充源码构建。仅Nginx发布回环端口，后端只信任精确网关IP；保持随机本机env不提交、增量迁移与仅空库种子，不覆盖活跃库存。S6入口scripts/test-s6-wsl.sh在自有干净卷上运行真实MQ/订单/重启与生产页面检查，不清理用户业务卷。公开上传前检查密钥、构建缓存和文件范围；S6部署验收不能代替S7容量/HA/故障SLA证明。

维护已实现的S5页面或接入部署时，读[前端运行与状态约定](../../../docs/FRONTEND-RUNTIME.md)。本地隔离展厅与WSL浏览器验收入口已建立；不要用新的抢购requestId替换受理结果未知的请求。页面条件注入与真实MQ/SQL链路分别报告，图片验证码及列表/原图限制见BUGS。

先验证业务正确性与故障恢复，再用压测评估吞吐和延迟。库存不为负、无超卖、无重复有效订单、无重复回补，以及故障恢复后在约定窗口内收敛，是交易链路的核心约束。压测必须统计入口请求、限流拒绝、预扣接受和持久化订单，不能只用快速拒绝请求的 QPS 表示下单处理能力。

## WSL/Linux测试要求

- 用户于2026-10-12要求后续测试也能在WSL跑通。WSL2/Ubuntu是必需的测试平台；Windows结果作为补充，不能替代WSL验收。
- 所有新增构建、单元、集成、超卖、幂等、回补、故障与压测入口提供Bash或跨平台Python命令。使用WSL原生编译器、Java、Maven、Node、Python，不调用Windows的.exe/.cmd冒充Linux通过。
- Windows与WSL使用各自的构建目录、Python虚拟环境、node_modules与原生依赖；不得共用Windows wheel、CMake缓存或Vite原生包。测试脚本从自身位置定位根目录，处理含空格和`c++project`的路径，Shell文件使用LF。
- 阶段完成前在WSL实际运行本阶段必需检查。报告发行版、工具版本、完整命令、退出码、通过/失败/未运行项与证据路径；缺依赖或Docker不可达明确标记，不静默跳过后声称全部通过。
- 纯静态检查与真实Redis/MySQL/MQ业务测试分开；压测需说明WSL资源/挂载路径与容器拓扑，不能将WSL成绩冒充生产Linux容量。
- 当前入口是`scripts/test-wsl.sh`；随阶段扩展完整测试入口和环境说明，见`docs/TESTING.md`。

## S9 公共商品目录分页

- 公共商品目录使用`GET /api/goods/catalog`执行服务端搜索、类别/价格筛选、排序和0起始分页；保留`GET /api/goods`的兼容边界。每个商品以最早SKU呈现目录卡片，深链接要能回查该商品完整SKU。
- 前端页码/筛选变化时清空已加载页并丢弃过期响应；加载更多追加新页且不重复SKU。所有筛选组合需一起验证，不只分别测单一筛选。
- 运行`bash scripts/test-s9-wsl.sh`；确认超过100件、跨多页、无重复、无结果、UTF-8查询、非法参数、类别/价格筛选和排序，以及完整S5浏览器/RocketMQ真实订单回归。测试fixture用PyMySQL绑定参数；如必须经mysql命令行写中文，先以UTF-8十六进制和`CONVERT(... USING utf8mb4)`表达，避免WSL locale导致二次转码。
- 更新API契约、ADR、TODO、BUGS、CHANGELOG、WORKLOG和PROGRESS，并保存机器可读结果与S9验收报告。偏移分页在商品并发增删时页边界可能移动；需要稳定游标或更大规模前先提出证据和迁移决策。

## S10 静态商品图优化

- 原始原创PNG放在`src/web/assets-source/`，禁止置于Vite的`public/`目录；线上仅托管首页主视觉与在售鞋款所需的优化WebP。保留图片来源/生成提示记录。
- 使用固定版本Pillow与`quality=82, method=6`的转换脚本；控制每个发布图片小于500KB，并保持原始像素尺寸。改动图片路径时同步seed、测试夹具、API示例、管理后台默认值。
- `bash scripts/test-s10-assets-wsl.sh`须在WSL原生Python中运行，生成/检查WebP、确认public目录无多余文件并验证资源大小；完整`bash scripts/test-s5-wsl.sh`须检查浏览器图片解码、HTTP MIME/尺寸、可访问性和响应式页面。不能只通过前端编译宣称图片验收通过。
- 更新TODO、PROGRESS、BUGS、CHANGELOG、WORKLOG、ADR与验收报告；记录源文件/线上文件大小对比及页面回归证据。

## S11 RocketMQ 强制终止恢复诊断

- 用自有S7 Compose项目和真实RocketMQ/Redis/MySQL，在订单服务`stop -t 1`期间受理请求，测量健康恢复到订单持久化可查的时间并做只读库存对账。
- 参数实验必须有默认值基线、至少三轮、环境与报告；无改善的参数要撤回。最终订单可查不等于延迟达标，阶段结论可为“诊断完成、缺陷继续开放”。
- 用`scripts/test-s11-wsl.sh --baseline`和`--verify --maximum-seconds 120`。不得删除/重置S7业务卷。
- 更新BUGS、TODO、PROGRESS、DECISIONS、WORKLOG、CHANGELOG与验收报告；不得把无效实验标为修复。

## S12 非视觉验证码替代

- 保留默认六位图片验证码，为屏幕阅读器用户增加可读题面模式；答案只保存SHA256并通过原有一次性、60秒有效、五次尝试限制校验。
- 前端要能在模式间切换，题面由屏幕阅读器状态区朗读，输入仍是明确关联标签的数字框；不能把答案写入HTML或API响应。
- 在`scripts/test-s2.sh`验证真实Redis绑定/摘要兑换与错误限制；在`bash scripts/test-s5-wsl.sh`验证真实浏览器辅助语义及RocketMQ→MySQL下单。自动axe不等于NVDA/JAWS人工认证。
- 同步API/架构、ADR、TODO、BUGS、PROGRESS、CHANGELOG、WORKLOG和S12验收报告。

## S13 RocketMQ 强制终止恢复修复

- 区分Proxy的`channelExpiredInSeconds`（在途RPC上下文清理）与`channelExpiredTimeout`（Consumer通道成员过期）；不能把前者当成成员分配TTL。
- RocketMQ Java PushConsumer接收请求启用autoRenew时，Proxy按`defaultInvisibleTimeMills`确定消息不可见期（默认60秒）；这与Consumer成员超时不同。采用30秒租约缩短断线后的重投等待，保留活跃处理自动续租。未经最长处理时长验证，不随意再缩短。
- 先对无`channelExpiredTimeout`/`defaultInvisibleTimeMills`覆盖的Proxy默认设置测基线，再验证30秒消息租约。只改项目自有Broker，保留Named volume，不触碰日常/用户业务数据卷。
- 用WSL真实订单服务硬停期间提交新请求，等待健康和持久订单，再运行只读库存对账。验收为3/3真实新订单≤60秒且对账CLEAN；若失败，撤回配置并基于Proxy/Consumer事件继续定位，不得标记修复。
- 更新RocketMQ Compose、V015之后的ADR、BUGS、TODO、PROGRESS、CHANGELOG、WORKLOG和S13报告；只有实测改善且配置安全后才保留。

## MQ选型边界

当前方案已按用户明确要求改为RocketMQ5.x与官方gRPC C++/Java客户端（需Proxy）。S3职责改为Broker/Proxy部署、SDK适配、消息投递/消费和可靠性验证，暂停自研WAL/复制/传输协议实现；历史mq-wire.md仅作为延期方案。消息schema、reservationId幂等、pending恢复和MySQL事务不绑定厂商。重试、幂等、Redis预扣到消息投递的恢复与库存回补仍必须验证；RocketMQ事务消息不能自动把Redis预扣和MySQL变成一个事务。

## **长阶段自主推进模式** 

当用户说「按阶段连续执行」「做到阶段结束再停」时，进入本模式： 

1. 阶段定义：S0 骨架 / S1 数据与缓存 / S2 C++ 秒杀服务 / S3 MQ   / S4 Java 订单 / S5 前端 / S6 部署 / S7 验证收尾 / S8 恢复时延专项 / S9 公共目录分页 / S10 静态商品图优化 / S11 强制终止恢复诊断 / S12 非视觉验证码替代 / S13 RocketMQ强杀恢复修复 / S14 C++入口工作线程与容量诊断 / S15 运动鞋多尺码 SKU。
2.   阶段内自主拆分子任务连续输出，不逐条确认。 
3. 仅三种情况可提前停下：架构级分歧、前置产出缺失导致无法继续、单次回复达到长度上限。 
4. 每轮末尾输出断点标记：   >>>CHECKPOINT: <阶段>-<子任务>-<已完成文件>   >>>NEXT: <下一个要做的>   >>>STATUS: <进度 x/y
5. 下一轮先读 CHECKPOINT 接续，发现截断先补全。 
6. 阶段结束必须输出「阶段验收报告」并等待确认。 7. 禁止事项：阶段内频繁询问、跳过文档同步、编造已完成、一次性输出整个系统。


## S14 C++线程容量诊断

- 使用`bash scripts/test-s14-wsl.sh`在已有自有S7测试卷上扫描8/16/24/32/48/64工作线程，每档三轮；禁止删除/重置卷。脚本必须检查实际运行容器配置，退出时恢复默认8线程。
- 每轮64并发热点真实交易，检查HTTP受理、MySQL订单与只读库存对账；每轮校准WSL/MySQL时钟偏差。
- 将入口HTTP延迟与订单可查延迟分开报告。短时突发QPS不是持续容量；高线程数不是生产推荐值。延迟未达v0.1时继续定位relay、Broker、Java与MySQL分段时延，不宣称阶段门禁通过。
- 同步BENCHMARK、验收报告、TODO、BUGS、DECISIONS、PROGRESS、CHANGELOG、WORKLOG与部署说明。

## S15 运动鞋多尺码 SKU

- 同款的实际尺码使用独立SKU与独立未分配库存；每个SKU可单独关联活动库存，沿用activityId+skuId交易合同。不得只加前端假尺码按钮或让不同尺码共享库存。
- 管理员通过`POST /api/admin/goods/{id}/skus`创建尺码SKU，继承款式的基准价格/类别/配色，并在父款行锁下拒绝同款重复尺码；UI尺码选项来自该款GET API真实SKU。每码活动在管理活动页分别创建、分库存并激活。
- 初始演示范围男/中性EU39–46半码、女款EU35–42半码；该尺码段仅为可修改展示数据，不是业务覆盖承诺。空目录种子为每个尺码创建SKU和独立活动；重复种子不得改动已有商品、活动或库存。
- 首页款式卡和活动场次按goods去重，详情页显示所有真实SKU尺寸，访问活动/加入清单仍绑定具体skuId。跑`bash scripts/test-s4.sh`验证权限、重复尺寸、单码库存与API，再跑`bash scripts/test-s5-wsl.sh`验证Chromium选择/管理流程和真实消息下单；若修改完整部署种子，再跑S6独立干净卷验收。报告区分WSL本机功能验收与生产容量承诺。
