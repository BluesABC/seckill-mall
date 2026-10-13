# S4订单运行说明

Java业务由`MALL_BUSINESS_ENABLED=true`启用；默认只启动健康骨架，方便独立构建。真实业务需要MySQL、Redis、RocketMQ、002迁移和Lua源码目录。环境变量见[配置例](../deploy/.env.order.example)，从项目根执行。

```bash
source scripts/env-wsl.sh
bash scripts/ensure-rocketmq-topic.sh
bash scripts/configure-order-consumer-group.sh
MALL_DB_USER=root MALL_DB_PASSWORD=s1-local-root-only build/wsl/venv/bin/python scripts/data.py migrate
mvn -B -f src/order/pom.xml -Dmall.build.directory="$PWD/build/wsl/order-target" verify
set -a
source deploy/.env.order.example
set +a
# 首次管理员：自行设置MALL_ADMIN_USERNAME、MALL_ADMIN_PASSWORD（至少12字符）。
java -jar build/wsl/order-target/order-service-0.1.0-SNAPSHOT.jar
```

管理员bootstrap只创建不存在的账号，拒绝覆盖同名普通账号；已有管理员不自动改密码。密码采用BCrypt，输入12字符以上、UTF-8至多72字节。普通注册固定USER角色；登录发行随机Bearer会话（两小时、Redis仅保存SHA256索引），C++直接兼容。账号禁用先在用户行锁内撤销已发行会话，再提交禁用，登录同样使用用户行锁。

启动C++HTTP和独立relay见[MQ说明](ROCKETMQ.md)。Java订单接口在8082，C++秒杀接口在8083；S5开发代理和S6 Nginx将`/api/order/*`路由Java。当前直接访问不同服务端口联调。

## 活动与订单

管理员创建商品/SKU→创建READY活动并从未分配库存划拨→激活。激活仅首次预热空ledger，已有ledger核对元数据，不重置库存。先提交DB ACTIVE，再暴露Redis ACTIVE；中途失败可用相同激活请求恢复。活动结束不拒绝结束前已受理的消息。商品下架控制展示，停止活动另调用end接口。当前购买路径只售活动库存。

消费者校验严格v1消息、Redis预扣来源、DB版本/价格/受理时间。在统一库存父锁下去重请求、条件扣DB库存、创建订单和outbox。事务提交后返回SUCCESS；相同reservationId重投读取已有结果，COMPENSATING/FAILED不会重新创建订单。

支付只提供MOCK，金额取订单。待支付默认15分钟，支付与关闭同时检查DB时间/状态、统一库存→订单锁顺序。关闭归还DB库存并生成唯一回补outbox；已经支付的订单不关闭或回补。

## 恢复与审计

后台每秒执行：关闭到期订单→同步outbox→重试已记录的消费错误→扫描Redis在途请求→再次同步outbox。消费错误持久化至mq_failures，管理员可以查看原因并按messageHash重放原始消息。字段/来源不匹配的消息隔离审计且向Broker返回FAILURE，达到消费组上限进入DLQ；不凭死信数量加库存。

即使DB宕机导致错误无法落库、消息最终进入Broker DLQ，Redis请求仍保留。默认30分钟未产生订单的RESERVED/QUEUED请求由恢复扫描尝试终止：先取得同一库存父锁、核对DB请求和订单、提交COMPENSATING与唯一回补outbox，随后Lua回补，完成后DB请求变FAILED。迟到/重放消息命中该终止记录，不会复活订单。这个30分钟是请求恢复期限，可通过ORDER_RECOVERY_AGE_MS配置，不是生产容量或收敛SLA。

outbox保持PENDING直到Redis状态/回补经同连接WAITAOF确认；未知结果保留同eventId重试。DB回滚后Redis已有副作用时重试由Lua去重。多个事件按DB当前订单状态同步，已支付/关闭不会被旧ORDER_CREATED事件回退。

每轮最多关闭100单、同步100个outbox、重试20条错误、扫描500个Hash字段；扫描游标跨轮保持，最多10个ledger游标。多实例使用DB行锁与唯一约束；当前开发环境单Redis、单Broker，生产水平扩展、告警及全量对账在S7验收。

业务消费者默认4个消费线程（MALL_MQ_CONSUMER_THREADS允许1–64）、SDK缓存限流阈值256条/4MiB，JDBC连接池12个连接。SDK在途批次可能让缓存短暂超过阈值，这不是严格堆内存上限。SDK初始化和Proxy可达不表示所有消息立即可消费；本机重启用例曾观测82.082秒后恢复投递，测试观测窗口120秒。库存/终止记录保持安全，生产恢复时延与SDK/Proxy在途请求优化留S7。

接口与权限见[API](API.md)，阶段测试执行`bash scripts/test-s4.sh`，不要与其他共享实例的故障测试并行。测试使用随机数据库/Redis前缀/Topic/消费组；会短暂停止本项目专用MySQL验证DLQ与恢复，不删开发数据卷。
