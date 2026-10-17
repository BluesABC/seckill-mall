# S18 / T051 容量门禁自动化验收

- 日期：2026-10-17。
- 结论：**阶段完成**；完整真实30分钟报告通过独立证据校验，短测/历史失败报告被拒绝。

## 交付

- `scripts/test-s18-capacity-wsl.sh`：WSL/Linux入口，限定自有S7项目，检查健康和实际配置、记录镜像/资源/源码，执行负载并校验结果；已有报告拒绝覆盖，不创建/清空数据卷，不自动修改运行参数。
- `scripts/check_capacity_gate.py`：忽略passed声明，依据计数守恒、实际时长/发送率、202受理率、5xx、传输未知、延迟、持久化覆盖、阶段证据、outbox和库存CLEAN独立计算；核对五分钟窗口及其汇总一致性、库存明细守恒。缺失/损坏证据返回非零。
- `tests/test_capacity_gate.py`：7个测试方法验证成功证据与短时长、慢响应、缺样本、库存明细不守恒、5分钟集中错误、错误计数/NaN/伪造passed、CLI损坏输入等拒绝路径。合成数据仅用于校验器逻辑，不是性能证明。
- 项目skill增加持续容量修复/门禁参考，说明读放大、连接模型、调度隔离、WSL回归和证据边界。

## 实测

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| WSL工具行为/语法/skill验证 | 7项通过，含7个门禁单测与阶段解析单测 | [验证记录](wsl/s18-tooling-validation.json) |
| 60秒短测不能替代完整门禁 | 返回1、拒绝 | [短测拒绝](wsl/s18-reject-short-capacity-run.json) |
| 历史失败长测不能通过 | 返回1、拒绝 | [历史失败拒绝](wsl/s18-reject-historical-failed-long-run.json) |
| 新完整真实长测 | 27,000次、15 QPS×30分钟，独立校验通过 | [原始报告](wsl/t048-fixed-durability-30m.json)、[门禁结果](wsl/t048-fixed-durability-30m-gate.json) |

复现步骤与参数恢复见[测试说明](../../docs/TESTING.md)。本工具验收不是生产上线审批；注册/验证码/支付/查询混合旅程、突发和生产故障域仍需单独测量。

补充验证：[264条文档链接/契约检查](wsl/s18-contract-validation.json)、[测试参数恢复与本地演示健康](wsl/s18-runtime-verification.json)。容量运行所记录的10份源码原始字节哈希在完成后复核一致；镜像与运行参数单独记录，不将未提交工作树的基准HEAD当作运行源码版本。
