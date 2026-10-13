# S2 C++秒杀服务阶段验收报告

日期：2026-10-12。结果：S2/T021完成，S3–S7尚未开始。

## 已实现

- C++20真实HTTP服务：活动查询、PNG验证码、一次兑换令牌、双凭证预扣、Redis请求进度、健康接口和管理员指标。
- 服务端会话认证、IP/用户限流、验证码签发配额、黑名单；不接受客户端userId，不信任伪造X-Forwarded-For。
- 双凭证与库存/资格在同一次Lua验证；有界线程池、HTTP超时/16KiB body限制、线程独享hiredis连接、活动pending上限与原子计数。
- 新受理及重放都使用同连接因果屏障+WAITAOF；未知确认不回补，使用原请求ID查询/重试。
- SDK中立PendingRelay扫描/发布结果/状态确认内核；真正RocketMQ适配仍在S3。probe只允许私有s2_test_命名空间，不被HTTP服务使用。

## 实测证据

| 检查 | 证据 | 结果 |
| --- | --- | --- |
| C++配置/构建/CTest | [S2日志](wsl/s2-run.log) | Release构建成功，CTest3/3 |
| 真实HTTP+Redis | [JSON结果](wsl/s2-http-integration.json) | 23项，0失败/错误/跳过，退出0 |
| 并发库存 | 80不同用户请求竞争20份库存 | 20个202，60个409，库存0 |
| 并发同请求 | 同用户/同requestId并发30次 | 1个202、29个200；同reservationId，扣1次 |
| 凭证/身份 | 无效/过期/撤销/非法角色会话、错误答案5次、挑战一次兑换、用户/请求/活动绑定、过期/篡改凭证 | 通过 |
| 请求与防刷 | 未知JSON字段/重复JSON字段、重复查询键/编码同义键、非法ID、超大body、黑名单、IP/用户配额、XFF伪造 | 通过 |
| 未知受理 | TCP代理丢一次WAITAOF回复 | 首次503 ACCEPTANCE_UNKNOWN但库存已扣；原ID重放200且不重复扣 |
| 背压/发布结果 | 活动pending上限；test-only probe的unknown/rejected/confirmed | 不超上限；unknown/rejected保留，confirmed才推进QUEUED/清理计数 |
| 运维 | Redis不可达、指标管理员权限、SIGTERM与端口释放 | 通过；无错误“订单成功”响应 |
| S1回归 | 本阶段Lua增加pendingCount/安全模式后重跑test-s1 | 28/28与AOF SIGKILL恢复通过 |
| 静态与视觉 | Skill格式/引用/Shell检查；[PNG样例](wsl/s2-captcha-sample.png) | PNG人工查看可读，接口不返回答案 |

## 修复记录

首轮23项中发现HTTP库折叠完全相同的查询参数；应用改为检查原始URI，并拒绝重复键和编码同义键，重跑23/23。JSON解析也拒绝重复字段，非法缓存会话角色归为401，验证码配额Retry-After按窗口返回。

WSL依赖使用hiredis1.2.0、OpenSSL3.0.13、nlohmann-json3.11.3、libpng1.6.43；cpp-httplib v0.18.3头文件与MIT许可证已保留，SHA256记录在third_party。Ubuntu clang-format18.1.3规范化代码。/mnt/e存在亚秒级Make时间偏差警告，但构建与实测通过；生产容量测试仍须注明存储与资源环境。

## 重现与保留状态

WSL项目根：
```bash
source scripts/env-wsl.sh
bash scripts/test-s2.sh
# S1崩溃回归另行执行，勿与HTTP服务测试并行：
bash scripts/test-s1.sh
```
测试使用随机HTTP端口和Redis前缀，结束删除自己的数据、停止自己启动的进程；专用Redis/MySQL继续运行。手动服务入口为`build/wsl/cpp/src/seckill/seckill_service --serve`，默认127.0.0.1:8083；配置与凭证协议见README/API。

## 交付边界

S2接受成功只表示Redis预留/pending达到本地刷盘边界，非MQ投递、订单创建或支付成功。尚无真实登录/注册、RocketMQ收发、Java事务消费者、支付或完整商城前端。orderId查询/ORDER_CREATED权威结果在S4补充；C++返回ORDER_SERVICE_UNAVAILABLE，不能伪造结果。

23项包含显式test-only发布probe，不是RocketMQ实测；验证码只验证基础PNG与绑定/尝试限制，未验证抗OCR。没有QPS/P95/P99达标或生产HA结论。

下一阶段S3：部署NameServer/Broker/Proxy，实现官方C++ SDK Publisher、周期pending转发、Java SDK收发验证、重试/故障与确认语义；订单业务消费仍在S4。
