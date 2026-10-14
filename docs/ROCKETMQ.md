# RocketMQ开发环境与传输约束

用户选择先采用RocketMQ。S3以单Broker开发环境跑通C++→Java的真实消息链路；这份说明不表示订单事务、生产HA或容量指标已达成。

## 已采用的组件

- Apache RocketMQ 5.3.2：NameServer + Broker内嵌Proxy，gRPC本机`127.0.0.1:8081`，NameServer`9876`，Broker Remoting`10911`。Compose项目为`seckill-mall-mq`，卷仅由本项目创建，不做自动删卷。
- Broker `SYNC_FLUSH`、`ASYNC_MASTER`、单副本；确认可用于本地磁盘进程崩溃恢复边界。`brokerIP1=127.0.0.1`只适配当前WSL本机SDK连接，S6容器互联前需改为容器网络可达地址。
- 主Topic`seckill_reserved_v1`是NORMAL类型、4读/4写队列，不依赖SKU内严格有序。C++消息Key包含稳定eventId和`activityId:skuId`用于检索；RocketMQ messageId可以在重复投递时不同。唯一订单由S4数据库约束。
- 官方C++ SDK源码固定`apache/rocketmq-clients@6b0bcc422ff1ee66198df6b4a48a4a44ad7218fa`，API proto子模块固定`apache/rocketmq-apis@bc8e1845a8b0a1b5ec828690324401a323244354`。源码档案SHA256在`scripts/setup-rocketmq-sdk-wsl.sh`，从官方codeload重现。Ubuntu系统gRPC1.51/Protobuf3.21的CMake配置方式与上游源码安装说明不同；项目只在忽略的build目录把`find_package(protobuf 3.19 CONFIG REQUIRED)`替为`find_package(Protobuf 3.19 REQUIRED)`，没有把第三方源码复制到src。
- Java官方`rocketmq-client-java:5.2.2`由Maven锁定。S3的SimpleConsumer用于收发/ACK探针；PushConsumer封装`RocketPushReceiver`供S4的业务事务消费者使用。
- Proxy设置见[`rmq-proxy.json`](../deploy/rocketmq/rmq-proxy.json)。S13把`defaultInvisibleTimeMills`从默认60000毫秒调整为30000毫秒；PushConsumer自动续租活跃处理，客户端硬停时旧租约更早过期。强停测试与边界见[S13报告](../tests/reports/S13-acceptance.md)。

## 启动与检查

```bash
source scripts/env-wsl.sh
bash scripts/ensure-rocketmq-topic.sh
bash scripts/configure-order-consumer-group.sh
bash scripts/test-s3.sh
```

`ensure-rocketmq-topic.sh`等待基础容器并声明普通Topic。Compose健康探针仅检查TCP；Broker重启后NameServer Topic路由可能稍晚，本项目测试在SDK连接前额外查询Topic路由。`configure-order-consumer-group.sh`为后续Java订单组`mall_order_v1`设8次重试和1/2/4/8/16/30/30/30秒间隔；实际事务处理和DLQ补偿在S4/S7实现。

手工转发（在S2生成已受理请求后）：
```bash
MALL_KEY_PREFIX=seckill MALL_REDIS_PORT=16379 MALL_MQ_ENDPOINT=127.0.0.1:8081 \
  build/wsl/cpp-s3/src/mq/mall_relay_worker --loop
```

转发进程扫描`<prefix>:ledgers`内的非空pending字段。发布确认后Lua把请求推进QUEUED并清空pending；失败/确认未知保留原eventId和预扣，退避后自动重试，运行时活动有pending上限。`--once`用于运维/测试；故障钩子只有BUILD_TESTING且前缀为`s3_test_`时可用。JVM探针也只接受`mall_s3_probe_`组，不能当作业务消费者。

## 消费、重试与死信

单次发布成功+Java探针ACK只是传输验收。Java订单服务在S4必须先提交MySQL幂等事务再给PushConsumer返回SUCCESS；DB/处理失败返回FAILURE。测试对专用组配置`retryMaxTimes=1`后，PushConsumer失败回调出现至少一次重投并在组专属DLQ看到消息。当前单Broker上的SimpleConsumer未ACK测试虽观察到重投，但没有按该组配置观测到自动DLQ；S4的订单业务因此采用PushConsumer路径。

订单组满重试进入DLQ时，不得凭DLQ数量直接回补库存。S4/S7应以reservationId比对请求和订单状态，原子终止失败请求，记录补偿事件、重放审计和告警；已支付订单不可回补。MQ确认消息可以因Redis推进状态失败而再次发送，业务eventId不变，S4通过MySQL唯一约束完成幂等。

官方参照：[Docker Compose](https://rocketmq.apache.org/docs/quickStart/03quickstartWithDockercompose/)、[C++ SDK](https://rocketmq.apache.org/docs/sdk/03cplusplus/)、[Java SDK](https://rocketmq.apache.org/docs/sdk/02java/)、[消费重试](https://rocketmq.apache.org/docs/featureBehavior/10consumerretrypolicy/)。
