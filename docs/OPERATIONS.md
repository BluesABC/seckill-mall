# 对账与故障处置

关联G11/G12、T030。所有例子从项目根执行，默认日常Compose项目；env文件含本机凭证，不打印/提交它。部署拓扑见[DEPLOYMENT](DEPLOYMENT.md)。

## 只读对账

```bash
bash scripts/reconcile-stack.sh
bash scripts/reconcile-stack.sh --strict --grace-seconds 1800
```

输出单个JSON，不执行回补或覆盖库存。MySQL只读一致性快照、前后Redis账本快照及DB版本复查；最多500活动、50000订单/每账本50000字段，超过上限返回UNAVAILABLE，不截断后宣称正常。适合运维批次/定时调用，不是高频交易接口。

| 状态 | 意义 | 退出码 |
| --- | --- | --- |
| CLEAN | 快照稳定、库存守恒、没有未收敛任务 | 0 |
| IN_FLIGHT | 未超过宽限的在途预留、outbox或消费重试 | 0；strict模式3 |
| ALERT | 稳定快照中的差异/超时/隔离消息，需要检查 | 2 |
| INCONCLUSIVE | 读取期间有业务变化，不能下正常/异常结论 | 3 |
| UNAVAILABLE | DB/Redis不可达、异常格式或超过检查上限 | 3 |

检查DB初始库存=可售+未关闭订单占用；Redis初始库存=可售+尚未释放的唯一预留；结合已落库订单与在途预留解释两边暂时不等。另检查用户资格、pendingSend计数、丢失账本、outbox超时/DEAD和mq_failures RETRY/QUARANTINED。CLOSED/FAILED必须已回补才不占Redis库存。MQ消息次数不能当订单数，pendingSend不是Broker积压：发送确认后消息仍可能等待消费。

宽限1800秒与当前30分钟请求恢复默认值对应，是实施参数，不是生产SLA。生产应根据测量窗口和业务预算调整。INCONCLUSIVE可稍后重新采样，不能计作通过；持续流量下应分批缩小检查范围或增加稳定快照机制，不能强制修复库存。输出/退出码可接已有告警系统，当前没有自动发送邮件/通知或外部监控平台。

## 排查与恢复

1. 保存对账JSON、时间和活动ID，查看日常服务日志、健康和ADMIN `/api/admin/recovery`。日志不应加入Bearer、验证码答案或请求体。
2. DB/MQ不可用时，受理请求依然使用原requestId查询。停止制造新流量，恢复相应组件，再等待原订单/终止结果；不可立即退还所有预扣。
3. 恢复后订单worker自动执行持久outbox/超时关闭/重试与过期预留终止。需要立即运行时，以真实ADMIN凭证调用`POST /api/admin/recovery/run`；它使用相同事务/Lua幂等逻辑。
4. `/api/admin/recovery`查看失败hash与原因。修正依赖故障后可`POST /api/admin/recovery/{hash}/replay`，保留原消息业务ID；格式/价格/身份冲突的QUARANTINED消息不能直接改内容冒充原请求。DB停机时可能无法写审计，故障恢复还必须检查Redis在途与Broker死信。
5. 账本丢失时，保持入口拒绝与告警，保存DB/Redis/AOF/MQ证据。禁止直接把初始库存写回Redis。永久数据丢失的自动重建没有实现；需要独立备份/恢复设计后再执行人工恢复。
6. 重复对账到稳定CLEAN，核对有效订单唯一和库存守恒，记录恢复耗时。Broker POP在途/重试与消费者重建会带来等待；[官方重试说明](https://rocketmq.apache.org/docs/featureBehavior/10consumerretrypolicy/)描述其语义，具体本项目数据以S7报告为准。

Redis重启后C++每个业务线程先做只读PING探测，断开连接只重试PING一次。连接在后续Lua/WAITAOF期间断开仍会返回结果未知，客户端查询原ID；没有自动重试库存写操作。

## 可观测数据

C++ADMIN `/metrics` 为HTTP请求/错误、预扣、受理、未知结果、重放、限流与RT总量；JavaADMIN `/api/admin/recovery`为接收/确认/失败、outbox、补偿、隔离和worker错误。累计计数在进程重启后归零。S7另外保存HTTP与端到端分位、Docker CPU/内存/连接/IO、Redis命令延迟、MySQL锁等待/连接状态、Broker consumerProgress原始输出与最终库存账。MySQL重启会清零全局状态，不跨重启直接相减；POP offset差值不等于业务在途量。

## 独立故障/容量复现

```bash
bash scripts/test-s7-wsl.sh
```

必须WSL/Linux。使用独立seckill-mall-s7、18081、172.30.87/24与随机env，不重启日常数据库。入口拒绝已有S7测试卷，避免覆盖留存证据。私有SQL用户/Redis会话/验证码摘要、账本差异与老化请求只在该测试内注入，没有公开绕过接口。

容量探索把该测试Nginx提升5000r/s、C++IP10000，并将每账本待发送上限设128；认证/证明/Lua/AOF/真实SDK/MySQL事务仍执行。最后另测标准Nginx40r/s限流。测试不代表标准配置的单IP吞吐或注册/登录/人工验证码吞吐，不是HA演练。
