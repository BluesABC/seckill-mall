# 秒杀商城项目约定

本文件仅约束本项目及子目录。处理商城设计、实现、评审、部署或压测时，读取 `.agents/skills/seckill-mall/SKILL.md`，依照项目目标与一致性约束推进。

## 目录与工作边界

- `src/seckill/`：C++ 秒杀网关与核心服务。
- `src/mq/`：消息适配与RocketMQ集成；用户当前选择RocketMQ，后续明确要求时再切自研C++ MQ。暂停独立Broker/WAL/复制实现。
- `src/order/`：Java/Spring Boot 订单与普通管理业务。
- `src/web/`：TypeScript 前端。
- `deploy/`：Dockerfile、Compose、Nginx 配置。
- `scripts/`：初始化 SQL、压测、对账等运维脚本。
- `tests/`：交易正确性、集成与故障测试；压测报告置于 `tests/reports/`。
- `docs/`：项目说明、契约、决策和工作记录。

前端按用户2026-10-13明确指定的运动品牌/运动鞋秒杀方向执行，优先读取 `.agents/skills/seckill-mall/UI_Skill.md` 并实际查看 `UI/` 参考图片；具体规范见 `docs/FRONTEND-DIRECTION.md`。此选择替代此前的家居精品主题。

不要修改父目录下的其他项目。需要复用时先核对并明确引入范围，不假设候选组件已经满足商城要求。

## 文档同步

- 开工先查 `docs/PROGRESS.md` 与 `docs/TODO.md`。`PROGRESS.md` 是唯一项目阶段进度真相源；TODO 管理任务状态，通过任务 ID 引用，不复制阶段完成比例。
- 新增或调整接口同步 `docs/API.md`；调整架构、数据流或状态机同步 `docs/ARCHITECTURE.md`。
- 重要技术选择在 `docs/DECISIONS.md` 记录背景、选项、结论、后果与决策状态。
- 完成迭代后更新 PROGRESS、相关 TODO 和 CHANGELOG；每天工作结束补充 WORKLOG；未解决缺陷写入 BUGS。
- 任务负责人默认 AI，状态使用待办、进行中、阻塞、完成。只有阻塞任务填写阻塞原因；完成项链接验证证据。
- 日期按用户所在时区 Asia/Shanghai。耗时仅记录实测或明确标注估算，未计时写“未记录”。版本使用语义化版本，未发布内容放入 CHANGELOG 的“未发布”区。
- 设计草案、计划和目录初始化不能标为已实现；没有实测结果不能声称高并发或高可用已达标。

## WSL测试

后续测试必须支持并实际通过WSL2/Linux，Windows结果不能替代。遵循skill的references/wsl-testing.md与docs/TESTING.md；提供Bash/跨平台Python入口，各平台隔离依赖和构建产物，输出WSL命令/版本/结果。缺依赖报缺失，不静默跳过。当前MQ为用户明确选择的RocketMQ。
