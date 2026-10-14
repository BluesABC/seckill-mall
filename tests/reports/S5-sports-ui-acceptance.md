# S5 运动鞋主题修订验收 — V009

2026-10-13，Asia/Shanghai；T026，G01/G03/G09/G13。用户明确指定 UI_Skill 和 UI 文件夹六张 Nike/Adidas 参考图，替代此前家居主题。**运动主题修订完成**，完整部署/容量仍在S6/S7。

## 依据与设计交付

已实际读取`.agents/skills/seckill-mall/UI_Skill.md`并逐张查看nike.png、nike01/02/03.png、adidas.png、adidas02.png。没有下载品牌商品素材。参考分析→完整设计规范→信息架构/组件树→关键代码→替换/接入指南，按skill顺序记录在[设计规范](../../docs/FRONTEND-DIRECTION.md)。

原创SNKR//DROP品牌，黑白底色/红色秒杀强调，原创跑者主视觉和三款鞋图；Vue3/TS/Tailwind4.1.14/官方Vite插件。新组件ShopFront/ShoeCard/ShoeDetail/ShoppingBag覆盖首页、分类/价格筛选、加载更多、秒杀场次/库存快照、画廊/局部放大、真实尺码、清单抽屉/参考合计；原有认证/验证码/稳定请求/订单/MOCK支付/后台保留。

新增003增量迁移，为SKU增加sizeEu/category/colorway；ADMIN属性维护在库存父行锁下校验“从未分配过活动库存”，避免并发或事后重写订单规格。READY检查新增003要求。未修改001/002历史迁移、库存扣减或订单/支付算法。

## 实测命令与结果

WSL Ubuntu24.04.4、Linux Node22.20.0、Java21.0.12.1/Maven3.8.7；Chromium141.0.7390.37/Playwright1.56.1/axe4.11.0。Redis7.2.11/MySQL8.4.11/RocketMQ5.3.2与官方C++/Java SDK沿用V008环境。Windows依赖没有用于Linux构建。

```bash
source scripts/env-wsl.sh
mvn -f src/order/pom.xml -Dmall.build.directory="$PWD/build/wsl/order-target" -B verify
bash scripts/build-web-wsl.sh
build/wsl/venv/bin/python scripts/storefront_runtime.py --test
```

Java测试1/1及打包退出0；Vue类型与生产构建退出0。最终构建JS118.53kB(gzip44.44)、CSS38.86kB(gzip9.04)；原图未压缩，这些体积不是容量/性能达标证据。

浏览器**16/16通过，40.360秒**，真实SQL核对通过，运行退出**0**。证据：[运行日志](wsl/sports-ui-run.log)、[逐项结果](wsl/sports-ui/results.json)、[SQL](wsl/sports-ui/sql.json)，Java构建日志在忽略目录build/wsl/sports-java-build.log。后续可用既有`bash scripts/test-s5-wsl.sh`运行完整入口，浏览器结果目录更新为sports-ui。

| 验收 | 结果 |
| --- | --- |
| 图像/首页/目录 | 真实4款SKU；原创图可解码，搜索/排序/空态、运动分类/价格联动通过 |
| 尺码/画廊/清单 | 未选择不能抢购，未上架尺码禁用；局部查看、原生抽屉、移除入口、清单刷新保留/合计与键盘扫描通过 |
| 秒杀专区 | 全部/已开启/即将开抢筛选、时间与快照显示；没有伪造销量、进度或库存 |
| 真实链路 | 验证码/C++/Redis→官方SDK/RocketMQ→Java/MySQL；丢失受理响应保留ID，双击不重复，支付/关闭刷新可查 |
| 库存/唯一性 | 2订单=2唯一reservation；PAID1/CLOSED1、MOCK成功支付1；全部活动可用≥0且可用+有效订单占用=初始 |
| 权限/规格锁定 | USER读取ADMIN及修改SKU属性403；ADMIN创建商品/修改属性/活动/用户/订单/恢复通过；分配活动后尝试改尺寸409 |
| 断点/无障碍 | 390/640/768/1024/1280/1440首页与目录无横向溢出；桌面/手机详情与订单检查；已检查页面/登录/清单dialog axe0违规，pageerror0 |
| 页面条件 | 错误验证码私有解题夹具、售罄/过期私有DB/Redis条件；COMPENSATING/FAILED/商品503明确响应注入，与真实交易分开 |

首轮发现分类数字对比度不足，已调深；新清单dialog导致旧测试的通用dialog定位不唯一，改为认证dialog；中文分类hash编码未解码导致空结果，修复并回归。人工查看最终桌面首页和手机详情后确认主标题、完整鞋图、尺码/按钮、布局与参考节奏。

## 图与可运行预览

[桌面首页](wsl/sports-ui/desktop-home.png)、[手机详情](wsl/sports-ui/mobile-detail.png)、[清单](wsl/sports-ui/desktop-cart.png)、[秒杀专区](wsl/sports-ui/desktop-flash.png)。各宽度home-390/640/768/1024/1280/1440.png保存在同目录。

本地展厅`http://localhost:5173`通过真实ADMIN API建立四款演示鞋/尺码/活动；启动/停止与管理员本地凭据见[运行说明](../../docs/FRONTEND-RUNTIME.md)。[图像来源与提示](../../src/web/assets-source/ORIGIN.md)记录内置imagegen资产；截图只作视觉参考。

## 保留边界

清单是逐款秒杀选择，数量固定1，不锁库存，不提供合单结算/优惠券或真实支付。当前每款演示一个SKU尺码，其他尺码置灰；多SKU展示代码支持已有数据，但未提供专门的新建多规格接口。图库第二视图是原图局部放大，没有伪造鞋底/后跟图。库存进度为DB已确认占用快照，不能当作实时抢完百分比。

非视觉验证码、服务端分页/全量目录、图片尺寸压缩、多规格管理、S4消费重启时延等后续项仍见BUGS/TODO。自动axe不等于完整无障碍认证；S6/S7尚未执行，不能宣称容量或HA完成。

CHECKPOINT: S5-V009-UI_Skill/六图参考/运动鞋主题/WSL16项与SQL验收完成。
NEXT: S6-T024-完整容器与Nginx部署。
STATUS: T026完成，S6–S7未开始。

补充：主题红色统一为CSS变量后再次WSL构建退出0，并刷新实际应用内浏览器，标题/四款鞋已更新，读取accent=#d62820、saleColor=rgb(214,40,32)；应用内预览截图为Windows补充，不计入WSL16项。静态契约/125处链接和项目skill验证退出0。
