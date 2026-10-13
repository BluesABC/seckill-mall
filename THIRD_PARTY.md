# 第三方依赖

依赖自身的许可证与 NOTICE 仍然有效；本文件不替代其许可证，也不为本项目额外授权。

- `third_party/cpp-httplib`：源码与 MIT LICENSE 随仓库保存，版本/来源见该目录 ORIGIN.md。
- Apache RocketMQ：Broker/Proxy 与官方 Java/C++ SDK，Apache License 2.0。C++ SDK 和协议源码的固定提交/SHA256 在 `scripts/setup-rocketmq-sdk-wsl.sh`，构建时下载；运行镜像保留 SDK LICENSE。项目不包含自研 Broker。
- 前端直接依赖与精确锁定版本见 `src/web/package.json` / `package-lock.json`；Java 依赖见 `src/order/pom.xml`，其组件许可证由各上游提供。
- 原创演示品牌、运动鞋和跑者图片用于概念商城展示；UI 文件夹是用户提供的视觉参考资料。没有使用 Nike/Adidas 商标作为本项目品牌。

公开仓库的源码供查看与学习；当前没有给项目整体指定开源许可证。需要再分发或商业使用时，应另行确认项目与所有相关素材的授权。
