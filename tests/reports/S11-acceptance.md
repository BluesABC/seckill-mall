# S11 RocketMQ 强制终止恢复诊断

日期：2026-10-14。目标是确认 S4-005 中 `docker stop -t 1 order` 后约75秒的恢复等待是否由 RocketMQ Proxy 通道清理配置造成；本阶段是诊断，不宣称修复该缺陷。

## 结论

将 Proxy `channelExpiredInSeconds` 设为30秒后，稳定三轮仍耗时72.145、73.555、72.198秒；另一次初始结果8.324秒未复现。撤回配置并重建仅项目S7 Broker后，默认设置基线69.985秒，后续三轮75.103、73.340、76.033秒。默认与实验结果没有可验证的改善，故保留RocketMQ镜像默认配置并新增ADR-021。

每轮都在订单服务强停期间真实提交抢购并收到202，服务启动健康后订单最终达到`PENDING_PAYMENT`，只读库存对账`CLEAN`。这验证了消息最终恢复，但70–76秒尚无可接受的生产恢复SLA。

## WSL 验收

- 环境：Ubuntu 24.04.4 LTS / WSL2，Python 3.12.3；真实项目S7 Docker Compose、RocketMQ Broker/Proxy、C++、Redis、Java、MySQL。
- 命令：`bash scripts/test-s11-wsl.sh --baseline`，然后`bash scripts/test-s11-wsl.sh --verify --maximum-seconds 120`；两命令均退出0。
- 结果：默认配置基线1/1，回滚后默认配置3/3；总计4笔恢复订单均可查，库存对账4/4 CLEAN。
- 对照：30秒配置3轮72.145–73.555秒；一次8.324秒的非稳定结果被后续测试推翻。
- 证据：机器结果`wsl/s11-recovery.json`；复跑输出`wsl/s11-run.log`；入口`../../scripts/test-s11-wsl.sh`。

## 后续

`docs/BUGS.md`中S4-005保持开放。下一次诊断需记录RocketMQ Consumer 客户端重连、队列分配及消息重试时间点，再选择有证据的修复方案。此单Broker测试不代表HA或生产SLA。
