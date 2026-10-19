# T056 GitHub商城预览缺少商品图

- 日期：2026-10-19；关联G01/G13与项目展示维护。
- 原因：README引用的`home-1440.png`在资源尚未加载完成时保存，PNG本身就没有跑者主视觉和鞋款图。它是静态截图，GitHub不会再为它补加载网页资源。
- 修复：README改用同目录中已跟踪、人工查看确认图片完整的`desktop-home.png`，不改写历史截图冒充原始测试结果。
- 防止复发：响应式截图前先等待8张商品卡出现，再强制加载视口外懒加载图片、核对naturalWidth、decode、字体和两帧绘制；缺图时明确失败。

## WSL验证

运行`source scripts/env-wsl.sh && node tests/browser/image-ready.mjs`，Linux原生Chromium检查4/4通过：390/1440宽度下延迟及懒加载的9张真实WebP均完成加载；404图片拒绝截图；README引用路径对应现存PNG。三份相关mjs执行`node --check`通过。[机器可读证据](wsl/t056-image-ready.json)。

该回归使用静态资源夹具，不依赖数据库/MQ，不重跑或宣称完成完整S5交易验收。已人工查看正确截图的主视觉、两排商品图。图片无需重新上传，修复仅改变README引用并补充截图检查。
