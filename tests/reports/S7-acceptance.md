# S7 阶段验收报告（V011）

日期2026-10-14（Asia/Shanghai）；T030/T031/T040、G11/G12/D10。用户确认先完成本机实测基线。本阶段真实WSL故障10/10、容量/恢复/限流13场景通过；没有声明生产容量/HA或真实支付。

## 交付与实际结果

只读限量对账与机器可读告警、私有S7 Compose与故障/压测入口、C++Redis旧连接恢复、[运维说明](../../docs/OPERATIONS.md)、[容量报告](../../docs/BENCHMARK.md)、[演示说明](../../docs/DEMO.md)。原有业务契约不变，PING仅安全读重试，Lua/AOF结果未知仍不自动重试。

最终[故障JSON](wsl/s7/faults.json)、[负载JSON](wsl/s7/load.json)、[负载日志](wsl/s7-load-run.log)、[续跑收尾日志](wsl/s7-finalize-run.log)和[故障演练日志](wsl/s7-run.log)。故障九类恢复检查与真实DLQ重放分开完成，容量负载九个订单场景和DB故障场景通过，最后独立收尾入口退出0；全新卷的一体化`bash scripts/test-s7-wsl.sh`入口因已有保留的S7卷拒绝重跑，未宣称整入口退出0。容量受理976/持久订单976，每场景逐ID核对并CLEAN；最终DB/Redis库存守恒，超量不超卖，重复有效订单为零。具体分位/资源/限制不重复改写，见容量报告。

故障清单：bounded read-only clean reconciliation; relay outage distinguishes in-flight/aged alarm and recovers without overselling; injected stock drift is reported; checker makes no writes; lost ledger refuses purchases and cannot reset durable inventory; hard-bounded consumer stop restores queued order and replay is unique; broker outage retains Redis reservation until official SDK recovery; database outage is unavailable, not clean; durable order recovers; Redis unavailable returns unknown/503; AOF crash preserves reservation and replay; MOCK payment replay and autonomous close conserve stock after faults; real retry exhaustion/DLQ and durable termination fence reject late original event。

| 组件恢复测量 | 秒 |
| --- | --- |
| relayRestartSeconds | 1.09 |
| consumerRestartSeconds | 75.945 |
| brokerRestartSeconds | 13.923 |
| databaseRestartSeconds | 12.038 |
| redisRestartSeconds | 5.358 |

上述为实际单组件docker start至原请求查到MySQL订单的观测，普通场景预算180秒；真实重试到死信观测预算240秒。是观测窗口，不是生产SLA。消费者恢复较长等待仍然存在；不能将“最终收敛”包装为低延迟。

单组件恢复需用受项目label保护的docker start；Compose5.6 start relay会恢复依赖MYSQL，测试已修正并断言DB仍exited。DLQ使用实际Broker偏移增加证明，恢复后先持久终止并回补，再用官方C++ SDK重放原始事件。私有QUARANTINED标记仅用于证明精确payload经过消费者并被RESOLVED，不冒充真实业务隔离来源。库存差异/丢失账本/宽限/隔离JSON在同目录。

## 回归与已知边界

真实Redis重启暴露线程旧socket，C++增加只读PING单次重连；64并发查询复验通过。`bash scripts/test-s2.sh`HTTP/Redis23/23（含WAITAOF回复丢失和相同ID不重复扣减）、CTest3/3退出0。Python/Shell语法、契约与Markdown链接检查通过。

失败记录s7-failed1–5.log保留：首次脚本误用缺失账本/落库后重放返回码；随后发现并修复真实旧连接问题；死信夹具老化顺序与Compose依赖启动曾使恢复任务提前执行，修正后重新真实验收。不删约束或用模拟组件替代业务证明。

私有夹具包括SQL用户/Redis会话/验证码答案摘要、订单到期与请求老化、库存差异、精确payload隔离标记；仅作用seckill-mall-s7，不在公网添加绕过接口。故障不会停止共享开发基础设施；自有失败夹具卷按label核查后重建，最终证据/卷保留。

仍为单Broker/Redis/MySQL、本机HTTP/MOCK支付，未验证小时级压力/HA/永久数据丢失重建/备份恢复。消费者硬停恢复时延的分解与优化、生产TLS、真实支付、多规格/分页/图片压缩和非视觉验证码继续保留为已知事项。阶段完成指本轮确认的本机基线交付完成。
