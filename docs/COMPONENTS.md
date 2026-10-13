# 组件评估与环境

S2新增：cpp-httplib v0.18.3（third_party保留MIT/license/hash）、hiredis1.2.0、OpenSSL3.0.13、nlohmann-json3.11.3、libpng1.6.43。有界线程池而非自写HTTP协议；C++默认端口8083，为RocketMQ gRPC8081避让。发布适配内核已有但真实SDK未接通；当前结果见V005。

S1更新：用户已明确先采用RocketMQ（ADR-009），下表保留S0评估历史。当前不实现自研Broker/WAL/复制，src/mq为官方SDK适配边界；未来用户要求时重新评估自研。WSL已补齐Java21/Maven3.8.7/Pythonvenv/pip，Node22.20在项目tooling目录；DockerLinux引擎已运行。真实MySQL8.4.11/Redis7.2.11与镜像digest见deploy/IMAGES.lock.json，验收见PROGRESS V004。

日期：2026-10-12；此次只读评估，没有修改或复制父目录代码。

| 候选 | 检查依据 | 结论 |
| --- | --- | --- |
| mq_project | README、CMakeLists、client/mq_client.h、broker.cc、replication.cc、storage_engine.cc、api-spec.md | 有 WAL/刷盘、消费位点、TCP 和复制实现；文档 ack=all 说明前后不一致；复制状态 PersistLocked 采用 flush/删除/重命名，不能据此证明断电持久性；未发现 LICENSE/COPYING。不直接复制，本项目独立实现 MQ 模块并保留其为协议研究候选 |
| ReactorKV | README 列出的命令与运行环境 | 不支持目标 Lua/Hash/Stream 能力，不能替代 Redis；不引入 |
| Krpc-main | README 的 Muduo/Protobuf/Zookeeper/gl​​og 依赖 | 属于 RPC 组件，不能直接承担浏览器 HTTP API；当前不引入，避免增加无必要的注册中心 |

上述自研WAL/多数派复制是S0历史方案，已由ADR-009替代。S3当前采用RocketMQ官方SDK与独立mall_relay_worker；`src/mq/main.cpp`的mall_mq仅保留骨架配置检查入口，不能用于发布消息。单Broker不是HA，SDK版本与实际能力见[ROCKETMQ.md](ROCKETMQ.md)。

## S0历史环境

- Windows：Java 21.0.12.1、Node 24.16.0、Docker CLI 29.8.0、CMake、MinGW 可发现。
- Ubuntu WSL：GCC 13.3、CMake 可用；未发现 Redis/MySQL/Maven/Java/Node 命令。
- Docker context 为 desktop-linux，引擎管道不存在，未启动容器。
- 验证时使用 WSL 编译 C++，Windows 构建 Vue 与 Java；Maven 3.9.11 下载到忽略目录 build/tooling，校验 SHA512 后使用。没有修改系统 PATH。

## 开发基线与验证演进

S4增加Boot管理的Spring JDBC/Hikari、Spring Data Redis3.5.13/Lettuce6.6.0、Spring Security Crypto（BCrypt）和MySQL Connector/J。未引入自动改Schema的ORM，继续显式哈希迁移；WAITAOF使用Lettuce显式数组输出，同连接写屏障。新增Java业务代码由clang-format18按Java Google风格整理，固定版本SDK保持原适配边界。

C++20/CMake3.20+，Java21/Spring Boot3.5.16，Vue3.5.22/TypeScript5.9.3/Vite7.1.9，Redis7.2.11、MySQL8.4。npm lock固定依赖。S0仅静态配置；S1已拉取并实测MySQL8.4.11/Redis7.2.11，digest记录IMAGES.lock.json；S6正式部署按验证digest固定配置。

官方依据：[Spring Boot 要求](https://docs.spring.io/spring-boot/3.5/system-requirements.html)、[Vue 起步](https://vuejs.org/guide/quick-start.html)、[Redis Lua](https://redis.io/docs/latest/develop/programmability/eval-intro/)、[MySQL CHECK](https://dev.mysql.com/doc/refman/8.4/en/create-table-check-constraints.html)。
