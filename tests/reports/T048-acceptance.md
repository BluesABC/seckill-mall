# T048 / S16 持续容量诊断报告

- 日期：2026-10-15
- 环境：WSL2 Ubuntu、Docker Desktop Linux engine；压测器与被测服务运行在同一宿主机。
- 目标：暂定基线 v0.1 的15 QPS × 30分钟单热点SKU负载，不是生产容量承诺。
- 判定：**诊断完成，持续容量门禁未通过。** 同宿主机测试不能证明生产容量。

## 结果

| 验证 | 观察结果 | 判定 |
| --- | --- | --- |
| 15 QPS × 60秒，32线程 | 900/900 HTTP 202，0个5xx；订单可查P95 1.567秒；对账CLEAN | 短测通过，不代表持续容量 |
| 15 QPS × 30分钟，32线程/128队列 | 27,000次提交；20,356次HTTP 202、6,644次5xx（24.6%）；已接受请求接口P95 17.123秒；最终20,499笔订单 | 门禁失败 |
| 15 QPS × 60秒，64线程/512队列 | 900/900 HTTP 202，0个5xx；订单可查P95 1.310秒 | 短测通过，不代表持续容量 |
| 15 QPS × 30分钟，64线程/512队列 | 27,000次提交；16,230次HTTP 202、10,768次5xx（39.9%），另有1,016次明确BACKPRESSURE；接受响应P95 8.263秒；最终19,250笔订单 | 门禁失败，增加入口线程和排队没有改善长稳态 |
| 订单阶段耗时 | 32线程组事务P95 274ms、relay pending年龄P95 2.082秒；64线程组事务P95 459ms、relay pending年龄P95 24.406秒 | 下游排空速度和热SKU数据库写竞争需继续定位 |
| 最终清理与库存一致性 | 两轮活动的outbox均在压测脚本600秒等待上限后继续收敛；最终库存只读对账CLEAN | 一致性最终通过；不能抵消容量门禁失败 |

HTTP超时和5xx不代表服务端没有执行交易。两组数据库订单均多于HTTP 202数；客户端遇到超时后应按requestId查询，不能盲目创建新请求。

## 诊断改进和证据

- Relay仅扫描活动pending集合，避免对累积账本重复全量扫描；空闲轮询改为100ms，发布失败仍指数退避。
- 订单资格检查使用非锁定库存快照，保留条件扣减作为库存串行点；避免随机reservation主键缺失时的RR间隙锁；事务内先条件扣库存再插入外键请求记录，失败会整体回滚。
- 客户端响应统计会在等待订单/outbox清理前原子保存。清理超时后可用恢复脚本结合数据库、容器日志重建报告。逐请求checkpoint仅在本机保留，不提交到公共仓库。
- 64线程/512队列短测：[`t048-sustained-workers64-queue512-60s.json`](wsl/t048-sustained-workers64-queue512-60s.json)；32线程短测：[`t048-sustained-workers32-relay100ms-60s.json`](wsl/t048-sustained-workers32-relay100ms-60s.json)。
- 32线程长测：[`t048-sustained-workers32-relay100ms-30m.json`](wsl/t048-sustained-workers32-relay100ms-30m.json)；64线程长测：[`t048-sustained-workers64-queue512-30m.json`](wsl/t048-sustained-workers64-queue512-30m.json)。
- `bash scripts/test-s2.sh`：24/24通过；`bash scripts/test-s4.sh`：23/23通过；阶段分析单测通过。

## 后续

T050应补充MySQL锁等待/死锁、RocketMQ队列积压和Java消费者在途观测，再为单SKU库存写入与outbox排空设计可回滚方案。未证明库存守恒和超卖回归前，不应直接分片库存。实施后重跑15 QPS×30分钟门禁，并验证5xx、订单可查延迟、outbox排空时间和库存对账。

生产容量、HA、支付、TLS及NVDA/JAWS人工实测仍未完成；此报告不构成生产上线批准。
