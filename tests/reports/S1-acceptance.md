# S1数据与缓存阶段验收报告

日期：2026-10-12。结果：S1/T013完成。用户选择RocketMQ已落入ADR-009和skill；Broker/Proxy/SDK集成仍在S3，未宣称消息链路已经跑通。

## 实现与证据

| 项目 | 实现/证据 | 结果 |
| --- | --- | --- |
| WSL环境 | Ubuntu24.04、Python3.12.3、Java21.0.12.1、Maven3.8.7、Node22.20.0、Docker29.8.0 | 实际可用 |
| 真实数据引擎 | MySQL8.4.11、Redis7.2.11，商城专用Compose项目；[镜像记录](../../deploy/IMAGES.lock.json) | 两服务healthy |
| 迁移/种子/预热 | data.py执行001_schema，10业务表+schema_migrations；种子活动/SKU900001，初始库存100；首次Redis预热 | 已执行，重跑不覆盖库存 |
| Lua缓存协议 | preload、reserve、mark_request、mark_order、release | 真实Redis执行通过 |
| MySQL/Redis集成 | [JSON结果](wsl/s1-integration.json)、[日志](wsl/s1-run.log) | 28项，0失败/错误/跳过 |
| AOF崩溃恢复 | [结果](wsl/s1-recovery.json) | 同连接WAITAOF确认后SIGKILL并重启，库存/资格/请求/pending恢复；重试不重复扣减 |
| WSL全套骨架回归 | [日志](wsl/s0-all.log)、[Java进程结果](wsl/s0-order-smoke.json) | CTest3/3，Java1项测试+verify打包/启动，Vue类型与构建，静态契约与Compose解析通过，退出0 |

## 交易正确性覆盖

- 30份库存、200个不同用户并发预扣：接受30、售罄拒绝170，库存0；100个同用户不同请求只接受1次。
- 同请求重放返回原reservationId；epoch/参数/用户/UUID/Key类型/活动时间错误不改库存或资格。
- 100次并发回补只加库存1次，保留资格；同reservation使用另一个eventId也不重复加库存；eventId冲突拒绝。
- 已支付镜像不能关闭/回补，已关闭镜像只回补一次，终态不能回退。
- MySQL10份库存、50次并发事务只创建10张订单；30次同消息并发消费模拟只创建1次；同资格不同请求被唯一索引拒绝并回滚库存。
- CHECK、FK、过期支付条件更新、事务回滚、迁移重放/漂移拒绝与种子不覆盖验证通过。
- 首次预热锁定DB活动/库存记录，拒绝ACTIVE或初始库存不完整的活动，防止把部分可售量误当初始库存重建。

SQL消费部分是独立数据库测试工具，不是已经实现Java消费者或HTTP下单。Redis状态镜像/回补依赖服务端已提交DB终止/关闭证据，脚本不能代替DB授权或事务。

## 修复与环境处理

首轮发现库存FK父记录共享锁升级导致1213死锁；统一先锁活动库存父记录，异常有限退避重试整笔事务。迁移漂移测试改为显式提交/恢复测试哈希，避免MySQL隐式DDL提交污染相邻测试。修复后27项通过；随后补充首次预热的ACTIVE/库存完整性保护用例，最终28项全部通过。

Docker首次MySQL拉取EOF后重试完成，没有改其他项目容器或清空全局数据。WSL系统安装python3-venv/pip、OpenJDK21、Maven；Node下载到项目build/wsl/tooling并校验官方SHA256。测试Python依赖位于独立Linuxvenv，未共用Windowswheel/node_modules。

## 重现与保留状态

在WSL项目根执行：
```bash
source scripts/env-wsl.sh
bash scripts/test-s1.sh
bash scripts/test-wsl.sh --all
```
test-s1会使用seckill-mall-s1专用项目，在Redis16379/MySQL13306运行真实测试；临时数据库与随机Key只由创建它们的测试清理。崩溃测试短暂重启本项目Redis，请勿与使用该实例的应用并行执行。不会删除数据卷。

阶段结束专用Redis/MySQL容器保留运行，演示数据保留；无Java冒烟残留进程。演示活动READY且只在首轮生成一小时窗口，重复seed不延长时间；新活动通过后续管理功能创建，不覆盖已有库存。

## 边界与下一阶段

尚无HTTP秒杀、商品认证/管理、RocketMQ收发、Java订单/支付、购物前端或完整部署闭环。无生产HA、磁盘损坏恢复或QPS/延迟达标结论。

下一步S2：C++HTTP/认证/限流/验证码与活动令牌、Lua接入、状态查询和pending转发接口；实际RocketMQ SDK实现按S3推进。
