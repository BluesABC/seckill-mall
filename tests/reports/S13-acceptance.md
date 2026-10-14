# S13 RocketMQ 强制终止恢复

日期：2026-10-14。S4-005表现为订单服务被强制杀停后，新进程已经健康，已受理订单仍要约70秒才可查。本阶段区分通道成员超时与消息租约，最终调整消息可见性租约并用真实交易验收。

## 根因与修复

- Java RocketMQ Client 5.2.2的PushConsumer接收请求开启`autoRenew`；RocketMQ Proxy 5.3.2会将请求采用的消息不可见期设为`defaultInvisibleTimeMills`，默认60000毫秒。服务强停使旧接收流被取消，未确认消息要等不可见期结束后才重新投递。Proxy日志观察到取消接收流，时延也与60秒租约吻合。
- `channelExpiredTimeout`是另一种Consumer通道成员过期配置。将其设为45000毫秒仍三轮耗时72.855/73.593/73.886秒，没有改善，故最终没有用该参数。
- 在项目Broker Proxy配置中设置`defaultInvisibleTimeMills: 30000`，保留PushConsumer自动续租；有进程继续处理的在途消息仍可被延续，异常断线后的消息更早可重投。设置同步到开发MQ与完整Compose Broker服务。

## WSL 验收

- 环境：Ubuntu 24.04.4 LTS / WSL2、Python 3.12.3；真实S7订单/Redis/MySQL及RocketMQ 5.3.2 Broker/Proxy。
- 默认值基线：74.321秒，订单`PENDING_PAYMENT`，只读库存对账`CLEAN`。
- `channelExpiredTimeout: 45000`反证：72.855、73.593、73.886秒，无有效改善，CLEAN 3/3。
- 正确租约配置：`defaultInvisibleTimeMills: 30000`。强停订单服务时仍收到202；恢复后订单可查8.539、50.979、52.755秒，对账CLEAN 3/3。后两轮相对74.321秒基线缩短约30%；首轮在Broker刚重建后的8.539秒视为较快样本，不用它代表稳定值。三轮均低于60秒观察门槛。
- 完整命令：默认基线在加入Proxy覆盖前运行`S11_REPORT=s13-recovery.json bash scripts/test-s11-wsl.sh --baseline`，退出0。新配置运行`S11_REPORT=s13-lease-recovery.json S11_EXPECT_PROXY_FIELD=defaultInvisibleTimeMills S11_EXPECT_PROXY_VALUE=30000 bash scripts/test-s11-wsl.sh --verify --maximum-seconds 60`，退出0。为从当前树重复基线，先把`rmq-proxy.json`临时设为`{}`并只重建S7 Broker，再运行baseline；然后恢复版本库的30秒配置、重建Broker并运行verify。测试过程不删除S7卷。
- 证据：修复结果`wsl/s13-lease-recovery.json`；无效通道成员实验`wsl/s13-membership-recovery.json`；过程日志`wsl/s11-run.log`。

本结果证明本机单Broker测试环境下三轮强停恢复低于60秒，不构成生产SLA或多Broker HA证明。处理持续超过30秒时SDK自动续租的行为仍保留；后续部署需按业务最长处理时间重新验证Proxy lease参数。
