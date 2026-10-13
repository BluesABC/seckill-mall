# C++ MQ 传输契约 v1

状态：延期方案。2026-10-12用户选择先用RocketMQ，本文件不再是当前实现契约；当前使用官方SDK/gRPC，不实现以下自定义帧和复制协议。保留历史说明用于未来用户要求切换时重新评估。

S0冻结的基础客户端接口，S3实现，不复用父mq_project二进制协议。跨语言使用TCP长连接，生产部署加TLS/服务身份认证。本契约不表示broker已运行。

每帧：4字节网络大端unsigned载荷长度，后跟UTF-8 JSON；载荷1–1048576字节，超过长度/非法UTF-8/JSON关闭连接且不执行业务。支持半包/粘包；空闲与请求超时默认5秒。每连接一个在途请求，requestId用于响应关联，不充当业务幂等键。服务token不记录日志。

请求公共字段：version=1、requestId（UUID）、command、serviceToken、body；响应公共字段：version、requestId、code、body。code为OK/BAD_REQUEST/UNAUTHENTICATED/NOT_LEADER/NOT_READY/OVERLOADED/STORAGE_ERROR/STALE_GENERATION/INVALID_OFFSET。未知版本拒绝。

| command | body | 成功结果 |
| --- | --- | --- |
| PRODUCE | topic、partitionKey、eventId、value（消息JSON对象）、ack=DURABLE或QUORUM | partition、offset、term，均十进制字符串 |
| FETCH | topic、partition、group、memberId、generation、nextOffset、maxMessages（1–100） | records数组（offset、eventId、value）、highWatermark |
| COMMIT | topic、partition、group、memberId、generation、nextOffset | committedNextOffset |
| JOIN | topic、group、memberId | generation与分区分配 |
| HEARTBEAT | group、memberId、generation | 当前generation |

partitionKey为activityId+":"+skuId，所有语言使用字节级FNV-1a 32位无符号哈希取模固定分区数，初始1分区；不在客户端使用语言内建hash。offset从0开始，nextOffset为最后连续处理offset+1。consumer重新入组、lease过期、分配变化必须增加持久化generation，拒绝旧generation提交；不能在进程重启后重用失效generation。

DURABLE确认本地WAL记录及CRC刷盘；QUORUM还确认当前term多数派已持久化且commitIndex覆盖记录。确认未知重试保留eventId，producer去重不能取代订单DB唯一约束。FETCH只暴露已提交日志；消费者commit也需持久化，提交确认未知时再次提交相同/更大连续位点，不回退位点。

复制为S3的三节点Raft式协议：term/votedFor、日志、consumer generation/offset和topic元数据需落盘后确认；旧term请求拒绝，已提交前缀不可截断，未提交冲突后缀校正。多数派不可用时停止确认新写，禁止通过“自动降成单机”继续QUORUM。S3需补充复制帧与选举用例并故障验证；本阶段只冻结客户端和可靠性要求。
