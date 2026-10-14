"""Generate readable reports only from the real S7 evidence files."""
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
folder=ROOT/'tests/reports/wsl/s7'
faults=json.loads((folder/'faults.json').read_text())
load=json.loads((folder/'load.json').read_text())
assert len(faults['checks'])==10 and load['finalReconciliation']['status']=='CLEAN'
normal=[c for c in load['campaigns'] if 'ingressQps' in c]
accepted=sum(c.get('accepted',0) for c in load['campaigns'])
persisted=sum(c.get('persisted',0) for c in load['campaigns'])
assert accepted==persisted
rows=[]
for c in normal:
    rows.append(f"| {c['name']} | {c['users']} / {c['concurrency']} | {c['ingressQps']:.2f} | {c['acceptedQps']:.2f} | {c['persistenceTps']:.2f} | {c['accepted']}/{c['persisted']} | {c['httpLatencyMs']['95']:.2f}/{c['httpLatencyMs']['99']:.2f} | {c['orderLatencyMs']['95']:.2f}/{c['orderLatencyMs']['99']:.2f} |")
cpu=max((sum(float(c.get('CPUPerc','0%').rstrip('%')) for c in s['containers']) for s in load['resources']),default=0)
memory=max((sum(float(c.get('MemPerc','0%').rstrip('%')) for c in s['containers']) for s in load['resources']),default=0)
db=next(c for c in load['campaigns'] if c['name']=='db-outage-burst')
gate=next(c for c in load['campaigns'] if c['name']=='standard-nginx-40rps-gate')
bench=f'''# S7 本机实测基线（V011）

日期2026-10-14；用户明确选择本机探索。此报告由`scripts/generate-s7-report.py`从真实JSON生成，不是生产容量或长稳态达标声明。

## 环境与方法

- {load['hardware']}，12为Docker可用逻辑CPU；WSL2 Ubuntu24.04.4 / Python3.12.3 / Docker29.8.2 / Compose5.6.0。CPU型号/内核、镜像ID、LF规范化源码SHA、基线提交与原始采样在[完整原始数据](../tests/reports/wsl/s7/load.json)。代码包括当时未提交S7修改，manifest明确记录。
- 宿主代码在/mnt/e的DrvFs；实际服务/Redis/MySQL/MQ运行于Linux容器与命名卷。客户端也在同机WSL，Python标准库HTTP/1.1新连接模型；不是独立压测机。已有日常后台容器保留，列表在coLocatedContainers，不把共享环境当独占硬件。
- 七个被采样服务：Nginx、C++、relay、Java、Redis、MySQL、Broker；另有NameServer与一次性初始化。单实例、C++8线程/128连接排队、Java4消费者/Hikari12，Redis AOF always/noeviction、MySQL事务与RocketMQ5.3.2/官方SDK。
- 私有SQL用户、Redis会话与验证码摘要提前准备；真实HTTP仍获取验证码/签发双证明，计时窗口只含buy及异步落库。没有对注册、BCrypt登录、人工解题或商品图片带宽作容量承诺。
- 私有探索配置Nginx5000r/s、C++IP10000/用户100/证明10、每账本pendingSend128。认证/限购/证明/Lua/AOF/SDK/事务没有关闭。标准40r/s策略另测；探索数字不代表标准配置单IP吞吐。
- 存储/MQ预热；cold-cpp行只重启C++进程，其他存储仍温热，不宣称冷DB/冷MQ测试。阶梯4/16/64重复2次，另测超量热点、多活动、20r/s约10秒持续流量和下游故障；均为短基线。

## 分开统计入口、受理与持久订单

| 场景 | 用户 / 并发 | 入口QPS | 受理QPS | 落库TPS | 受理/落库数 | HTTP P95/P99 ms | 下单 P95/P99 ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
{chr(10).join(rows)}

入口/受理QPS使用整个HTTP提交窗口；落库TPS=该场景订单数/(最后一单DB创建时间−提交开始时间)，包含排队与启动等待，不使用售罄后的拒绝速度。下单分位为客户端buy开始至DB创建毫秒；HTTP分位包含拒绝，订单分位只含真实受理。小样本短窗口TPS可能跳动，不等于长期可持续极限。

全部容量/下游场景真实受理{accepted}、持久订单{persisted}，逐requestId核对、每场景最终CLEAN、无超卖/负库存/重复有效订单。超量场景和背压的拒绝不计作订单吞吐；状态/业务拒绝分布及逐请求原始延迟都在JSON。

下游DB停机并发32：提交期间受理48笔，恢复后查询到{db['recoveredOrderCount']}笔对应订单，最终只读对账CLEAN；这次续跑未保存总收敛耗时，不推算正常订单RT。标准Nginx40r/s，200次/{gate['concurrency']}并发静态探针：{gate['statuses']}，使用生产限流位置/指令，测试响应由本地静态文件提供，无库存写入。

## 资源与瓶颈解读

- {len(load['resources'])}轮采样，S7七服务CPU合计采样最高{cpu:.2f}%（100%=一个逻辑CPU）、内存占Docker总预算合计采样最高{memory:.2f}%。包含准备/恢复阶段；突发可能漏过采样，不等于瞬时峰值或独占资源上限。
- Redis每命令p50/p99/p99.9、MySQL连接/锁等待、CPU/内存/网络/IO与BrokerconsumerProgress保留原始值。每个常规场景有前后DB状态；MySQL故障重启会清零全局计数，不能跨重启相减。Broker offset/POP积压不是唯一预留数，对账另给出pendingSend与业务在途量。
- HTTP受理与端到端落库明显不同；当前relay逐条同步SDK确认、单热点MySQL父行串行事务和AOF屏障均可能限制吞吐。它们是代码机制/待隔离实验的候选瓶颈，未凭采样宣称某一项已被确证为全部瓶颈。
- 不可从本报告承诺1000QPS、小时级稳定性、HA或生产SLA。下一轮应固定实际业务目标/机器与独立压测机，扩大用户/持续时长，做每个瓶颈的单变量实验，再考虑并发转发、库存分片或横向扩展。

## 复现

`bash scripts/test-s7-wsl.sh`；已有S7卷会拒绝运行，先保存旧证据并明确处理自有夹具。原始JSON完成后运行`python3 scripts/generate-s7-report.py`。配置/只读对账/恢复口径见[OPERATIONS](OPERATIONS.md)，故障与阶段结果见[S7验收](../tests/reports/S7-acceptance.md)。
'''
(ROOT/'docs/BENCHMARK.md').write_text(bench,encoding='utf-8')
times='\n'.join(f'| {k} | {v} |' for k,v in faults['timingsSeconds'].items())
acceptance=f'''# S7 阶段验收报告（V011）

日期2026-10-14（Asia/Shanghai）；T030/T031/T040、G11/G12/D10。用户确认先完成本机实测基线。本阶段真实WSL故障10/10、容量/恢复/限流{len(load['campaigns'])}场景通过；没有声明生产容量/HA或真实支付。

## 交付与实际结果

只读限量对账与机器可读告警、私有S7 Compose与故障/压测入口、C++Redis旧连接恢复、[运维说明](../../docs/OPERATIONS.md)、[容量报告](../../docs/BENCHMARK.md)、[演示说明](../../docs/DEMO.md)。原有业务契约不变，PING仅安全读重试，Lua/AOF结果未知仍不自动重试。

最终[故障JSON](wsl/s7/faults.json)、[负载JSON](wsl/s7/load.json)、[负载日志](wsl/s7-load-run.log)、[续跑收尾日志](wsl/s7-finalize-run.log)和[故障演练日志](wsl/s7-run.log)。故障九类恢复检查与真实DLQ重放分开完成，容量负载九个订单场景和DB故障场景通过，最后独立收尾入口退出0；全新卷的一体化`bash scripts/test-s7-wsl.sh`入口因已有保留的S7卷拒绝重跑，未宣称整入口退出0。容量受理{accepted}/持久订单{persisted}，每场景逐ID核对并CLEAN；最终DB/Redis库存守恒，超量不超卖，重复有效订单为零。具体分位/资源/限制不重复改写，见容量报告。

故障清单：{'; '.join(faults['checks'])}。

| 组件恢复测量 | 秒 |
| --- | --- |
{times}

上述为实际单组件docker start至原请求查到MySQL订单的观测，普通场景预算180秒；真实重试到死信观测预算240秒。是观测窗口，不是生产SLA。消费者恢复较长等待仍然存在；不能将“最终收敛”包装为低延迟。

单组件恢复需用受项目label保护的docker start；Compose5.6 start relay会恢复依赖MYSQL，测试已修正并断言DB仍exited。DLQ使用实际Broker偏移增加证明，恢复后先持久终止并回补，再用官方C++ SDK重放原始事件。私有QUARANTINED标记仅用于证明精确payload经过消费者并被RESOLVED，不冒充真实业务隔离来源。库存差异/丢失账本/宽限/隔离JSON在同目录。

## 回归与已知边界

真实Redis重启暴露线程旧socket，C++增加只读PING单次重连；64并发查询复验通过。`bash scripts/test-s2.sh`HTTP/Redis23/23（含WAITAOF回复丢失和相同ID不重复扣减）、CTest3/3退出0。Python/Shell语法、契约与Markdown链接检查通过。

失败记录s7-failed1–5.log保留：首次脚本误用缺失账本/落库后重放返回码；随后发现并修复真实旧连接问题；死信夹具老化顺序与Compose依赖启动曾使恢复任务提前执行，修正后重新真实验收。不删约束或用模拟组件替代业务证明。

私有夹具包括SQL用户/Redis会话/验证码答案摘要、订单到期与请求老化、库存差异、精确payload隔离标记；仅作用seckill-mall-s7，不在公网添加绕过接口。故障不会停止共享开发基础设施；自有失败夹具卷按label核查后重建，最终证据/卷保留。

仍为单Broker/Redis/MySQL、本机HTTP/MOCK支付，未验证小时级压力/HA/永久数据丢失重建/备份恢复。消费者硬停恢复时延的分解与优化、生产TLS、真实支付、多规格/分页/图片压缩和非视觉验证码继续保留为已知事项。阶段完成指本轮确认的本机基线交付完成。
'''
(ROOT/'tests/reports/S7-acceptance.md').write_text(acceptance,encoding='utf-8')
print(json.dumps({'faults':len(faults['checks']),'campaigns':len(load['campaigns']),'accepted':accepted,'persisted':persisted,'maxObservedPersistenceTps':max(c['persistenceTps'] for c in normal)}))
