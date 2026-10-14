# 迭代进度

本文件是唯一阶段进度真相源。目录和设计草案不算代码实现；验收完成需要命令与证据。

| 阶段 | 状态 | 关联任务 | 已有证据 | 下一步 |
| --- | --- | --- | --- | --- |
| S0 骨架与核心契约 | 完成 | T001/T002/T010–T012 | V001、V002；C++3检查、Java测试/实进程、Vue构建、静态契约检查 | 等待下一阶段指示 |
| S1 数据与缓存 | 完成 | T013 | V004及S2期间回归28项/AOF恢复通过 | 为HTTP/后续订单提供存储 |
| S2 C++秒杀服务 | 完成 | T021 | V005：真实HTTP/Redis23项、CTest3/3，S1回归通过 | 等待进入S3 |
| S3 RocketMQ集成 | 完成 | T022a | V006：真实官方SDK六项/重试/DLQ/崩溃恢复，WSL退出0 | 下一阶段S4 Java事务订单 |
| S4 Java订单 | 完成 | T020/T022b/T023 | V007：真实业务22/22、S3/S2/S1回归与AOF恢复，WSL退出0 | 下一阶段S5精品商城前端 |
| S5 前端与运动主题修订 | 完成 | T025/T026 | V008历史基线；V009：UI_Skill/六图参考、WSL浏览器16/16、真实尺码/清单与SQL守恒 | 下一阶段S6部署 |
| S6 部署 | 完成 | T024 | V010：源码容器/干净卷10项、守恒/重启、生产页面与WSL回归；公开GitHub已上传 | 下一阶段S7 |
| S7 验证收尾 | 完成 | T030/T031/T040 | V011：WSL真实故障10项、容量/恢复/限流13场景；976/976订单持久化、最终只读对账CLEAN；S2 23/23、S1 28/28与AOF恢复回归通过 | S8专项恢复验收 |
| S8 消费者优雅恢复 | 完成 | T041 | V012：关闭等待20秒与30秒容器宽限匹配；优雅重启真实订单3/3，10.970/12.212/14.510秒落库可查，consumer关闭无超时，三次只读对账CLEAN | 下一阶段S9公共目录分页 |
| S9 公共目录分页 | 完成 | T042 | V013：WSL浏览器17/17；105件API分页24/24/24/24/9，分类/价格/排序、编码查询、非法参数与无重复通过 | 下一步由用户确定 |
| S10 静态商品图优化 | 完成 | T043 | V014：四张在用图8,493,658 B→433,276 B（94.9%减少）；WSL资源检查0、商城浏览器17/17、真实交易与SQL守恒通过 | 下一步由用户确定 |
| S11 RocketMQ强制终止恢复诊断 | 完成（根因未解决） | T044 | V015：默认配置基线+回滚后3/3均最终CLEAN；30秒Proxy配置无改善并已撤回 | 继续围绕Consumer重连和队列分配采集根因证据 |
| S12 非视觉验证码替代 | 完成 | T045 | V016：C++/Redis 24/24、两套CTest 3/3、商城浏览器17/17、屏幕阅读器题真实RocketMQ/MySQL交易和SQL守恒通过 | 后续S13已改进Consumer强停恢复 |
| S13 RocketMQ强停消息恢复 | 完成 | T046 | V017：识别60秒消息不可见期；调`defaultInvisibleTimeMills`为30秒后真实订单恢复8.539/50.979/52.755秒、库存对账CLEAN 3/3 | 本机验收完成；生产恢复SLA/HA目标待明确 |

## 验证记录

- V001，2026-10-12：项目初始化检查记录于 `tests/reports/project-initialization.md`。涵盖目录结构、九份文档、skill 格式与本地链接、父工作区旧商城入口移除。
- V002，2026-10-12：[S0验收](../tests/reports/S0-acceptance.md)记录工程构建、核心契约及环境限制。
- V003，2026-10-12：[WSL兼容性更新](../tests/reports/wsl-compatibility.md)：新增后续WSL必测要求与入口，C++3/3通过；完整模式环境前置未满足，未宣称全平台验收。
- V004，2026-10-12：[S1验收](../tests/reports/S1-acceptance.md)：补齐WSL环境，全套骨架检查通过；MySQL8.4.11/Redis7.2.11真实集成28项及AOF SIGKILL恢复通过。RocketMQ选择已确定，集成待S3。
- V005，2026-10-12：[S2验收](../tests/reports/S2-acceptance.md)：C++HTTP/真实Redis23项通过、CTest3/3，S1回归28项+崩溃恢复通过；生产MQ适配未接通。

- V006，2026-10-13：[S3报告](../tests/reports/S3-acceptance.md)。WSL环境中断已恢复，最终真实MQ六项通过，C++CTest3/3、Java健康测试与构建通过；S2/S1回归证据见报告。单Broker非HA，无MySQL订单事务。

- V007，2026-10-13：[S4报告](../tests/reports/S4-acceptance.md)。Java认证/商品/活动/事务订单/MOCK支付/关闭/outbox/回补与实际MySQL停机到DLQ恢复验证22项通过；最终消费资源配置已复验，S3六项、S2二十三项、S1二十八项/AOF恢复回归通过。最终重启投递延迟85.446秒，生产恢复SLA待S7。

- V008，2026-10-13：[S5报告](../tests/reports/S5-acceptance.md)。拾间精品商城与真实认证/商品/验证码抢购/查询/订单/MOCK支付/管理页面完成；WSL浏览器14/14、SQL唯一订单/支付/库存守恒通过，截图人工复核。非视觉验证码替代、分页/图片优化及生产部署/容量待后续。

- V009，2026-10-13：[运动主题报告](../tests/reports/S5-sports-ui-acceptance.md)。用户指定UI_Skill和六张UI参考图，已实际查看并改成运动鞋品牌；Vue/Tailwind组件、003真实SKU属性/规格锁定、清单与秒杀场次实现。WSL浏览器16/16与SQL守恒通过；替代V008家居视觉，V008验收保留历史。

- V010，2026-10-13：[S6报告](../tests/reports/S6-acceptance.md)。完整源码构建/独立干净容器10/10（62.342秒）、库存守恒、正常整栈重启、生产页面桌面/手机/9图/零控制台错误通过，最终入口退出0；S2接口23项/CTest3与S1存储28项回归通过。MOCK/单Broker/容量/恢复SLA边界保留，公开仓库交付不携带本机密钥。

- V011，2026-10-14：[S7报告](../tests/reports/S7-acceptance.md)与[容量基线](BENCHMARK.md)。WSL真实故障恢复/DLQ 10项，短容量/恢复场景13项；976笔真实接受/持久化订单，热点超额未超卖，最终只读库存对账CLEAN；Nginx标准40r/s静态探针200次返回200×91/429×109。12逻辑CPU/约8GB Docker本机探索，S2 23/23+CTest3/3、S1 28/28+AOF崩溃回归退出0。故障与DLQ分开完成，完整新卷入口未在本轮重复破坏/替换保留的S7证据卷；不承诺生产容量、HA或SLA。

- V012，2026-10-14：[S8验收](../tests/reports/S8-acceptance.md)。复现发现Java/Spring已健康后消息仍等待约74秒；旧SDK `consumer.close()` 五秒超时。将等待设20秒（Compose order宽限30秒），三轮优雅SIGTERM重启，真实消息10.970/12.212/14.510秒可查，无consumer close timeout，CLEAN 3/3。极短SIGKILL不在本修复承诺范围。

- V013，2026-10-14：[S9验收](../tests/reports/S9-acceptance.md)。公共商品目录新增服务端搜索/分类/价格过滤、排序和0起始分页（默认12、最大48），前端加载更多；WSL完整浏览器17/17，S7真实MySQL/API插入105款并按24页返回24/24/24/24/9，无重复，筛选/排序/六种非法输入通过，最终对账CLEAN。测试夹具以UTF-8十六进制写入中文，避免命令行字符集污染测试数据。

- V014，2026-10-14：[S10验收](../tests/reports/S10-acceptance.md)。使用固定Pillow 11.3.0 / WebP quality82、method6，从保留的原创PNG生成4张线上鞋图/主视觉；源文件8,493,658 B，发布图433,276 B，减少94.9%；无用的3张家居图也从Vite public发布目录移入源图归档。Ubuntu 24.04、WSL2资源生成/目录和单图预算检查退出0；完整S5商城浏览器17/17、Java verify、Vue生产构建、真实RocketMQ订单/支付/关闭、库存SQL守恒与185条文档链接/契约检查通过。

- V015，2026-10-14：[S11验收](../tests/reports/S11-acceptance.md)。Ubuntu 24.04.4/WSL2、真实S7 Broker/Proxy与MySQL；默认设置基线69.985秒，配置回滚后75.103/73.340/76.033秒，订单均最终PENDING_PAYMENT且只读对账CLEAN。30秒`channelExpiredInSeconds`实验三轮72.145–73.555秒，无改善并撤回；强制终止恢复仍是开放P1，未宣称解决。

- V016，2026-10-14：[S12验收](../tests/reports/S12-acceptance.md)。C++/Redis真实接口24/24、C++/MQ配置CTest各3/3、Java verify、Vue生产构建、商城Chromium17/17全部通过；第二笔真实文字题抢购经RocketMQ/MySQL建单并超时关闭，答案不下发，SQL核对2笔唯一订单/PAID1/CLOSED1/库存守恒通过。自动axe通过；NVDA/JAWS人工读屏未做。

- V017，2026-10-14：[S13验收](../tests/reports/S13-acceptance.md)。定位RocketMQ 5.3.2 Proxy的60秒消息不可见期；非因`channelExpiredTimeout`通道成员配置。设置`defaultInvisibleTimeMills=30000`后硬停订单服务，三轮真实受理订单8.539/50.979/52.755秒进入PENDING_PAYMENT且只读库存对账CLEAN；默认基线74.321秒。WSL真实Broker/Proxy/Java/MySQL，脚本退出0。生产SLA与HA未验证。

公开交付：[BluesABC/seckill-mall](https://github.com/BluesABC/seckill-mall)，PUBLIC、main，初始提交32f2a8d已核对远端一致。日常Compose项目已启动，localhost:18080就绪与四款商品读取通过；最终S6测试卷保留、测试容器已停止。

## 未确定事项

用户选择的本机探索预算为12逻辑CPU/约8GB Docker；生产流量目标、独立压测机、RocketMQ HA、生产部署与真实支付渠道仍待确定。SDK版本组合已固定；S4已验证真实事务业务与MOCK支付，S5前端/S6容器已验收。消费者强停恢复本机两轮稳定约51–53秒（V017），不构成生产恢复SLA；详见BUGS S4-005。

## 当前断点

CHECKPOINT: S13-V017-将RocketMQ Proxy消息不可见租约调整至30秒；WSL真实订单服务强停三轮8.539/50.979/52.755秒恢复并CLEAN；S12-V016文字验证码完整浏览器交易验收通过。
NEXT: S0–S13本机阶段完成；生产流量/恢复SLA、RocketMQ HA、TLS与真实支付渠道仍待明确目标。
STATUS: S0–S13本机阶段完成；生产容量/HA/SLA、真实支付与人工读屏认证仍未验证。
