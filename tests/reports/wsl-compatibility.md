# WSL测试兼容性更新

日期：2026-10-12。范围：新增测试平台约束、WSL入口与依赖隔离；不是S1业务实现。

- Ubuntu24.04.4 LTS，CMake3.28.3、GCC13.3、Python3.12.3。
- `bash -n scripts/test-wsl.sh`：通过。
- `bash scripts/test-wsl.sh --cpp`：实际WSL构建并运行CTest，3/3通过；[日志](wsl/s0-cpp.log)。
- `bash scripts/test-wsl.sh --all`：环境预检拒绝继续；Linux java/mvn/node缺失，PATH中的npm/docker来自Windows安装目录；[日志](wsl/s0-all.log)。未执行全套Java/Vue/契约/Compose测试，不宣称WSL全部通过。
- /mnt/e挂载构建观察到亚秒级时钟偏差警告，最终构建与测试成功。大规模压测使用WSL ext4工作目录并记录实际存储位置。
- Windows Python脚本语法、契约验证与skill格式检查通过；不代替WSL检查。

新增要求已写入项目skill/AGENTS与docs/TESTING；S0历史结果保留原平台归属。后续阶段验收需补齐原生依赖、执行本阶段所需WSL测试并保存证据。当前MQ仍按C++方案规划，RocketMQ询问未视为切换决定。
