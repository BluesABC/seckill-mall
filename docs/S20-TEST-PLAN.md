# S20 / T053：64人瞬时请求长尾

关联G02/G04/G08；本阶段仅验证WSL本机HTTP连接接入与库存正确性，不更新生产容量承诺。

## 冻结工况与判定

1. 原S7镜像、32工作线程/128任务排队、64人同时buy、库存64，重复三轮。用服务响应的X-Trace-Id关联客户端、Nginx和C++日志，同时采集C++网络命名空间TcpExt ListenOverflows/ListenDrops。不能用handler耗时替代HTTP耗时。
2. 只有证据指向接入等待才调整接入配置。固定版本cpp-httplib默认listen backlog=5；候选128与工作任务队列独立，不改限流、鉴权、库存、AOF或MQ协议。
3. 修改后先跑WSL完整S2/S4正确性回归；构建/故障测试与性能复验串行。真实MQ发送/消费逻辑不变，不以新增模拟代替真实依赖。
4. 修复镜像32线程下库存64、32各三轮；再以默认8线程/128任务排队做库存64三轮。每轮64条HTTP buy，64/32个202，其余仅409 SOLD_OUT；订单与支付数恰为库存，只读活动对账CLEAN，不能覆盖存量库存。
5. 沿用临时接口P95≤500ms；每轮分别判断，不用合并平均掩盖坏轮。固定候选应无ListenOverflows/ListenDrops增量。P99如实报告，不把三轮短突发等同于S17/S19的30分钟持续容量。
6. 补跑S19短自检，确认登录、验证码、MOCK支付和交易链路可用；短测不能代替历史完整30分钟工况。

## 夹具与恢复

- 使用已有自有`seckill-mall-s7`卷，独立新建活动。64个测试账号/会话为私有夹具，不测注册与登录容量；验证码按真实可读题面求解，真实token兑换，60秒有效期保持。
- 准备请求控制在网关40 r/s以下，准备后等3秒释放频控余量；同步提交阶段仍64人屏障，不更改网关限流。支付/查询收尾也限速，避免测试自身耗尽入口桶。
- 支付保持MOCK、900000ms期限不变。失败试跑订单保留并由原有流程自然关闭，不清库、不删卷。
- `bash scripts/test-s20-burst-wsl.sh --label NAME --stock 64 --workers 32`；每次标签唯一。脚本持有共享capacity.lock，临时增加仅含URI/状态/trace/耗时的网关日志，不记录查询参数、token、答案或body；退出恢复原Nginx内容和实际线程/任务队列配置。
- 每轮HTTP结果先写本机`build/wsl/s20-*-checkpoint.json`再收尾；公开报告去除逐请求业务ID和trace，仅保留状态、耗时及聚合值。异常试跑不能作为通过证据。
- 独立核验：`python3 scripts/check_burst_gate.py tests/reports/wsl/s20-NAME.json`。完整结果和局限记录在S20阶段报告、PROGRESS、BUGS和BENCHMARK。
