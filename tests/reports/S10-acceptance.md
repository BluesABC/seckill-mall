# S10 静态商品图优化验收

- 日期：2026-10-14（Asia/Shanghai）
- 目标：降低运动鞋商城实际发布的商品图片体积，保留可重新生成的原创源图，并保证本阶段测试可在WSL执行。
- 环境：Ubuntu 24.04.4 LTS、WSL2 kernel 6.18.54.1、Python 3.12.3、Pillow 11.3.0；WSL原生Python venv。源代码位于`/mnt/e/c++project/seckill-mall`。

## 改动

- 将原创PNG（包括不再用于当前运动商城的3张家居旧图）保存在`src/web/assets-source/`并保留生成来源提示；Vite发布目录只包含四张当前使用的WebP。
- `scripts/optimize-storefront-images.py`固定使用WebP quality 82、method 6和原图像素尺寸；Pillow固定11.3.0。管理默认值、seed、测试夹具与API示例全部使用WebP路径。
- 首页首屏图保留高优先级且异步解码；商品卡、详情缩略图按需懒加载/异步解码。浏览器测试检查图片可解码、响应Content-Type为image/webp、每图小于500,000字节。

## 资源结果

| 图片 | 原PNG | WebP | 减少 |
| --- | ---: | ---: | ---: |
| sports-hero-v1 | 2,386,620 B | 140,266 B | 94.1% |
| shoe-run-v1 | 2,057,526 B | 100,430 B | 95.1% |
| shoe-court-v1 | 2,141,938 B | 126,666 B | 94.1% |
| shoe-street-v1 | 1,907,574 B | 65,914 B | 96.5% |
| 合计 | 8,493,658 B | 433,276 B | 94.9% |

源图尺寸保持1536×1024（hero）与1254×1254（鞋图）。`public/assets`从包含旧家居图在内的15,654,289 B历史PNG资源缩减为433,276 B，仅发布实际使用的四张图。人工查看WebP跑鞋图，鞋型、配色和留白符合原稿；原始图仍保存在源图目录供重新导出。

## 验收

- `bash scripts/test-s10-assets-wsl.sh`：WSL原生运行；转换/重复检查、public目录精确文件清单和每图500KB上限全部通过，退出0。完整日志：[`s10-assets-run.log`](wsl/s10-assets-run.log)。
- `bash scripts/test-s5-wsl.sh`：Ubuntu 24.04/WSL2；Java21.0.12.1 `mvn verify`通过，Vue 3/TypeScript生产构建通过；商城真实浏览器17/17通过。桌面/手机页面所有实际图片解码成功，HTTP WebP/MIME/大小断言通过，无溢出、axe违规或浏览器异常。
- 同一浏览器回归运行真实验证码 → C++ → RocketMQ → Java/MySQL订单，模拟支付、重复操作保护、超时关闭、管理端及库存守恒；终端SQL断言通过，整套退出0。完整日志：[`s5-run.log`](wsl/s5-run.log)。
- `build/wsl/venv/bin/python scripts/verify_contracts.py`：项目文档/契约静态校验通过，JSON Schema正向1/1、反向6/6、SQL解析10条、Lua语法通过、Markdown内部链接186条通过；机器结果为[`s0-contract-checks.json`](wsl/s0-contract-checks.json)。Redis/MySQL执行测试不属于此静态校验项。

## 限制

WebP兼容现代目标浏览器；本地完整商城浏览器已实际验收，未测公网CDN、带宽或设备性能。当前维持原图像素尺寸和细节，不新增响应式多尺寸；源图质量可按后续视觉评审再调整。
