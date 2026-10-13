# S3 RocketMQ阶段验收报告

日期：2026-10-13。结果：S3/T022a完成。关联需求G05（用户改为RocketMQ）、G09/G10/D06–D08。传输层已实现，订单事务留在S4。

## 已实现

C++官方SDK生产者、独立pending转发进程（--once/--loop）、Java官方SimpleConsumer收发探针与PushConsumer封装；真实Broker/Proxy部署、固定源码/镜像、消费组重试配置。发布结果未知保留pending，只有确认后才推进QUEUED；稳定eventId供后续订单幂等，MQ确认不表示订单成功。

## WSL实测

Ubuntu24.04.4/WSL3.0.3（WSL2模式），内核6.18.54.1、Docker29.8.2、CMake3.28.3、GCC13.3、Java21.0.12.1、Maven3.8.7、Python3.12.3；工作目录/mnt/e/c++project/seckill-mall，全部使用Linux原生工具。RocketMQ5.3.2、C++SDK固定提交与JavaSDK5.2.2详见[运行说明](../../docs/ROCKETMQ.md)。

| 检查 | 结果与证据 |
| --- | --- |
| C++构建/CTest、Java verify | 构建通过，CTest3/3、Java健康测试通过；[S3日志](wsl/s3-run.log) |
| C++发布→Java接收/ACK | 真实消息确认、pending清理、状态QUEUED |
| Broker停机后重试 | RESERVED与库存预扣保留，恢复后成功发送 |
| send ACK后转发进程崩溃 | 实际exit93，重发相同eventId、接收两次，库存只扣一次 |
| Broker SIGKILL | 已确认消息在持久卷恢复后仍能被同消费组接收 |
| Push消费失败 | 实际失败重投，达到测试组上限后进入该组DLQ |
| 持续转发进程恢复 | Broker停机时保留pending，恢复后同进程自动推进QUEUED |
| S3六项总结果 | 最终6/6，0失败/错误/跳过，197.811秒，脚本退出0；[JSON](wsl/s3-rocketmq.json) |
| S2/S1回归 | HTTP/Redis23/23、数据/Lua/SQL28/28与Redis AOF SIGKILL恢复通过；[S2](wsl/s2-run.log)、[S1](wsl/s1-run.log) |

复现：从WSL项目根执行`bash scripts/test-s3.sh`，再依次执行`bash scripts/test-s2.sh`、`bash scripts/test-s1.sh`。故障套件不能并行运行。最终轮次的测试进程和随机Redis数据由测试清理；中断轮次可能残留测试Key，未批量删除。开发数据库、MQ数据卷、历史测试消息/消费组保留，不自动删除。

## 修复与边界

最终验收前Windows Update的WSL3.0.3安装失败（2902/1603），WSL服务缺失并中断测试；[中断日志](wsl/s3-wsl-interrupted.log)和[安装事件](wsl/wsl-installer-events.json)保留。两次微软签名3.0.1修复因安装源问题返回1603，不能记为修复成功；随后3.0.3安装退出0、服务/WSL/Docker恢复，最终整套在更新后的环境通过。保留Ubuntu和数据卷，未自动重启Windows。

修复新卷权限、Proxy TCP就绪早于Topic路由注册、SimpleConsumer不可见时间低于10秒、客户端请求超时与SDK无端点启动无限等待。无ACK探针仅保留目标消息，ACK无关历史夹具。收尾重跑发现同批次重复消息使探针“恰好一份”断言失败，已改为检查请求的最少投递数并处理整批ACK；[失败证据](wsl/s3-probe-count-failure.log)保留。SimpleConsumer无ACK实测没有观察到自动DLQ；S4采用已验证失败重试/DLQ的PushConsumer，在MySQL提交后返回SUCCESS。

单Broker SYNC_FLUSH不构成HA，不证明磁盘丢失/主从故障安全。当前SDK连接本地无TLS Proxy，Broker广播127.0.0.1，S6需适配容器网络。S3使用真实Redis预扣夹具，S2的HTTP另行回归；没有验证完整HTTP→MySQL订单链路、支付、生产容量或商城前端。下一阶段S4实现事务订单、基础业务、支付/关闭/补偿。
