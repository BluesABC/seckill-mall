# S17/T050 与 S18/T051：持续容量修复与门禁

涉及购买关键路径或持续压测时读取本参考；阶段事实以项目PROGRESS与验收报告为准，不把历史短测视为当前容量。

## 不应再次引入的瓶颈

- 活动ledger混存库存、资格和全部请求历史。info/captcha/token/buy读取活动元数据必须有界；现实现固定9字段HMGET。不得恢复HGETALL或逐请求全量扫描。session是固定小Hash，与活动历史规模不同。
- 当前cpp-httplib模型每条连接占用一个worker，包括空闲等待。C++后端每次响应关闭连接，浏览器到Nginx仍可复用；更换HTTP引擎或重新启用后端keep-alive前，验证代理空闲连接不会占满有界池。
- TCP listen backlog与worker任务排队是两层队列。项目固定版本cpp-httplib默认backlog仅5；S20将服务编译值设128，保留有界worker任务队列和业务背压。升级HTTP库或调整连接模型后，用同步64人至少三轮、网关upstream_connect_time、服务X-Trace-Id/rtUs与服务网络命名空间ListenOverflows/ListenDrops联合复核，不能仅看handler延迟。
- Lua明确返回RESERVED时，同连接已执行库存/请求写入，继续WAITAOF确认；只读REPLAY仍先写causal fence。不得移除持久化确认、未知结果保护或改用新requestId重试。
- Java原始凭据可用一次HMGET取得同账本的原子快照，仍逐项校验。库存条件更新、外键/唯一约束、事务回滚和重复消息幂等保留。
- Java持久化标记与原Lua在同次EVAL完成，包装器恢复原KEYS/ARGV长度；只读重放也必须写入标记并在同连接WAITAOF。不得以省略重放确认或降低appendfsync强度换吞吐。
- outbox独立于过期关闭/恢复扫描调度，仍以逐事件事务、事件行锁下重查PENDING和Redis持久化确认完成。不得用清空历史订单、跳过关闭任务、放松库存约束代替吞吐修复。显式ADMIN recovery可与派发线程并发，必须保证同一事件不重复生效。

## 必需回归

- `bash scripts/test-s2.sh`：包括30,000个历史字段下真实Redis回复总量有界、空闲HTTP连接不占住全部worker，以及库存/幂等/未知受理测试。
- `bash scripts/test-s4.sh`：真实交易/支付关闭/补偿/故障与新增锁等待回归；旧SKU被InnoDB锁住时，新SKU的真实MQ订单仍完成Redis状态派发，解锁后旧订单只回补一次。
- 更改发布或relay循环后运行`bash scripts/test-s3.sh`，验证真实SDK确认未知、重复/重试及Broker故障恢复。
- 故障回归与容量测试串行执行；同宿主机另跑构建、故障套件会干扰性能结果。WSL原生工具要求不变。

## 完整容量门禁

- 在已存在、自有S7 Compose项目与保留数据卷上运行`bash scripts/test-s18-capacity-wsl.sh`。脚本只验证/运行，不自动改服务配置、限流或卷。
- 配置必须显式记录实际容器值。32线程/128排队、4消费线程/4队列是本机对照配置，通用默认仍8/128。隔离压测可将支付TTL设为1小时以覆盖测试与收尾；恢复时保留业务原值，不把测试TTL用于日常演示。
- 至少15 QPS×1800秒；用户初始化、首批证明预备、时钟探针和镜像检查在发送时钟开始前结束，后续证明后台滚动写入，不能制造初始化补发突发。私有证明夹具600秒与生产60秒寿命不同，注册/验证码渲染/token兑换接口不在本专项发流与延迟统计范围，夹具后台准备的资源开销仍共享主机，须如实披露。
- 使用`python3 scripts/check_capacity_gate.py REPORT`独立核验，不能只相信报告的passed字段。检查原始计数守恒、HTTP202≥99.5%、5xx≤0.1%、无传输未知、有效发送率≥目标99%、完整30分钟、接口P95≤500ms、订单可查P95≤3秒/P99≤8秒、阶段与持久化观察覆盖、outbox排空及库存CLEAN≤600秒收尾。每个五分钟窗口也核对流量和错误预算。
- 保留全响应延迟和202响应延迟两种口径、镜像ID、源码哈希、CPU/内存、挂载路径与fixture范围。异常中止或证据缺失不得算通过；原始逐请求checkpoint仅留本机，公开仓库仅提交汇总证据。
- 本机门禁通过只证明该场景；独立压测机、生产拓扑、突发、HA/SLA、TLS、真实支付与NVDA/JAWS仍是独立门禁。

文档同步PROGRESS、TODO、BUGS、ADR、API（如有字段变化）、ARCHITECTURE、TESTING、CHANGELOG、WORKLOG和阶段报告。失败保留证据并继续修复，不调整阈值来制造通过。

## S20 突发接入复核

WSL入口为`bash scripts/test-s20-burst-wsl.sh --label NAME --stock 64 --workers 32`；32线程库存64/32与默认8线程库存64分别三轮。64个同步buy中仅允许库存数量的202及其余SOLD_OUT；逐轮P95≤500ms、零listen溢出、唯一订单/模拟支付数与只读库存守恒一起核验。`scripts/check_burst_gate.py`从逐请求耗时重新计算，不能相信passed或汇总P95声明。短突发不替代30分钟门禁。

该入口预置私有会话，但验证码按真实可读题求解并真实兑换token；准备与收尾限速，屏障提交前让网关频控余量恢复，不为准备流量放宽生产限流。持有共享capacity锁、临时增加脱敏代理耗时日志，退出恢复原配置。原始业务ID/trace checkpoint仅本机保存，公开报告仅含状态和计时。测试失败订单保留正常关闭，不重置库存。
