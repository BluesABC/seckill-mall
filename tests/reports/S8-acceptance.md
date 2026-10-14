# S8 阶段验收报告（V012）

日期：2026-10-14（Asia/Shanghai）；任务T041。目标是降低RocketMQ订单消费者在优雅部署重启时的恢复延迟，保持原有消息与订单幂等语义。

## 发现与修复

S7一秒强制停止后，订单查询约75.945秒才看到记录。S8用两轮有真实消息的30秒优雅停止复测，分别约76.542秒和73.898秒；Java订单服务在约7.7–9.8秒时已健康，但PushConsumer回调直到约74秒才增加`received/confirmed`，随后订单立即可查。旧服务关闭日志显示`consumer.close()`异步等待5秒后输出`order-consumer shutdown pending`。这些证据把等待缩小到SDK/Broker消费成员关闭/重新就绪窗口；未声称已证明RocketMQ内部的单一根因。

Java PushConsumer关闭等待由5秒增至20秒。完整Compose的order容器`stop_grace_period`为30秒，保留了额外退出时间。修改在新构建的order镜像上运行；Maven `verify`（1/1测试）与真实WSL订单栈验收均通过，日志见[构建验证记录](wsl/s8-maven-verify.log)。

## 验收结果

WSL2 Ubuntu24.04.4，12 Docker逻辑CPU、约8GB内存，独立`seckill-mall-s7` Compose栈。入口：`bash scripts/test-s8-wsl.sh`。每轮创建独立用户、SKU和活动，SIGTERM优雅停止order，停止期间通过真实C++秒杀入口接受请求，恢复后等待RocketMQ消息在Java处理并查询MySQL订单，再做只读库存对账。

| 轮次 | 停止耗时 | order健康就绪 | MySQL订单可查 | consumer关闭超时 | 对账 |
| --- | ---: | ---: | ---: | --- | --- |
| 1 | 13.144秒 | 10.404秒 | 10.970秒 | 否 | CLEAN |
| 2 | 14.660秒 | 11.097秒 | 12.212秒 | 否 | CLEAN |
| 3 | 15.133秒 | 13.289秒 | 14.510秒 | 否 | CLEAN |

成功3/3；所有受理订单为`PENDING_PAYMENT`，最终只读对账三次均CLEAN。对比同机修改前约74秒的消息可见时间，优雅部署恢复落到约11–15秒。原始记录见[三轮JSON](wsl/s8-graceful-recovery.json)、[最终运行日志](wsl/s8-test-run.log)、[修改前复现](wsl/s8-graceful-recovery.log)与[关闭等待延长后的首次复测](wsl/s8-after-closefix.log)。

## 边界

快速硬停（`docker stop -t 1`）或SIGKILL不会给SDK留下20秒注销机会，仍可能遇到S7约75秒级延迟；S8没有改变这一点。部署须保留order容器30秒stop grace。单Broker、单消费者实例、同机WSL，未验证HA、生产滚动部署、小时级压力或恢复SLA。
