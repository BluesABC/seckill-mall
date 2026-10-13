# S4 Java业务阶段验收报告

日期：2026-10-13。结果：S4/T020/T022b/T023完成。关联需求G03/G06/G09–G11、G12（审计/基础指标）、D05/D08。完整对账与生产性能验收留S7，阶段状态见PROGRESS。

## 可运行产物

- Java21/Boot3.5.16业务模式：BCrypt注册/登录、两小时opaque会话、注销/禁用撤销；C++直接使用Java发行会话。
- 商品/SKU创建与展示、商品编辑/下架、用户管理、活动库存划拨/首次预热/激活/结束，ADMIN权限保护。
- 官方PushConsumer真实消费，在MySQL库存父锁下校验来源/快照、请求幂等、条件扣库存、创建订单/outbox，提交后才确认消息。
- 本人订单查询/列表、MOCK幂等支付、DB时间到期关闭、DB库存归还与唯一回补outbox；支付与关闭共享锁顺序，PAID不回补。
- Redis镜像/Lua回补经同连接WAITAOF确认；失败保留PENDING，可在Java重启后继续。恢复扫描对超龄在途请求先建立DB终止记录，再回补，阻止迟到消息建单。
- 消费失败审计、管理员保留原身份重放、后台有界关闭/outbox/恢复、依赖就绪和有界关闭等待。002增量迁移，保留001哈希。

## WSL证据

Ubuntu24.04.4、WSL3.0.3（WSL2模式）/Linux6.18.54.1、GCC13.3/CMake3.28.3、Java21.0.12.1/Maven3.8.7/Python3.12.3、Docker29.8.2。MySQL8.4.11、Redis7.2.11、RocketMQ5.3.2；Spring Data Redis3.5.13/Lettuce6.6.0。工作目录`/mnt/e/c++project/seckill-mall`，全部Linux原生工具。

| 验证 | 结果与证据 |
| --- | --- |
| C++/Java构建 | CTest3/3与Java健康测试/打包；[阶段日志](wsl/s4-run.log) |
| 真实业务链路 | 最终22/22，0失败/错误/跳过，264.981秒，脚本退出0；[JSON](wsl/s4-business.json) |
| 登录到抢购 | Java真实登录→C++ PNG/凭证→预扣→官方C++SDK发布→Java事务→MySQL订单 |
| 幂等/归属 | 重复消息同订单/扣一次，越权查单/支付拒绝，重复MOCK支付同paymentId |
| 状态竞争 | 支付与关闭竞争，PAID不回补，超时CLOSED只回补一次 |
| 故障 | Redis请求临时不可用时outbox保留、Java重启后恢复；MySQL停机时进入真实组DLQ，恢复后终止并回补，迟到消息不能复活 |
| 管理/输入 | 普通用户拒绝后台、禁用撤销Java/C++会话、分配不足、激活不重置库存、JSON/query/body校验、登录限流 |
| 自动任务/退出 | 后台自动同步/超时关闭，有界SIGTERM退出 |
| S3/S2/S1回归 | 6/6、23/23、28/28与AOF崩溃恢复通过、脚本退出0；[S3](wsl/s3-run.log)、[S2](wsl/s2-run.log)、[S1](wsl/s1-run.log) |
| Skill与静态 | quick_validate通过，Markdown引用与Bash语法通过 |

## 修复记录

首轮登录发现Lettuce未知命令默认ByteArrayOutput无法处理WAITAOF整数数组，改为同连接显式ArrayOutput。独立MQ Topic发现S3 PendingRelay写死默认值，改为读取与SDK同一Config。首轮测试8项失败主要由夹具开始时间过近、注入终态pending后未恢复造成级联失败；[首轮日志](wsl/s4-first-failures.log)保留。夹具改用DB时间、充足开始余量，注入迟到消息验证后恢复tombstone。消费关闭等待新增上限并实际验证退出。

前一轮22项通过（262.461秒），其中消费者重启后的迟到消息观测82.082秒才再次投递；另一次[定向复测](wsl/s4-restart-check.log)在0.239秒观测。一次45秒测试窗口曾超时，现为120秒等待并记录实际耗时；不能据此宣称生产恢复SLA。最终配置为业务消费默认4线程、SDK缓存控制阈值256条/4MiB、JDBC池12连接，整套22项再次通过（264.981秒），本轮重启投递延迟85.446秒。原因和时延优化待S7；JVM关闭有界，测试没有强制SIGKILL Java进程。

## 重现与范围

执行`bash scripts/test-s4.sh`，再顺序执行`test-s3.sh`、`test-s2.sh`、`test-s1.sh`。测试随机创建数据库/Redis前缀/Topic/消费组，完成清理自己的DB/Redis/进程，MQ消息/组/Topic留在专用开发Broker供审计。故障测试会暂时重启本项目MySQL或Broker，禁止与依赖实例的应用/故障测试并行；开发数据卷保留。运行与默认参数见[ORDER-RUNTIME](../../docs/ORDER-RUNTIME.md)。

验证码固定答案只写私有测试前缀，不提供HTTP绕过接口。部分消费者边界测试直接使用Lua夹具或注入DB库存差异/到期时间，与完整HTTP链路测试分开，不将夹具等同于生产请求。

当前购买路径为活动库存；真实支付渠道未接通，支付provider=MOCK。请求恢复期限默认30分钟是可调整业务默认值；扫描/锁等待的生产收敛SLA、HA、QPS/TPS/P95/P99尚未验收。Redis磁盘丢失后的全量恢复和完整库存对账/告警在S7。前端精美商城在S5，完整Docker/Nginx服务编排在S6。
