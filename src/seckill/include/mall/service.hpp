/**
 * @file service.hpp
 * @brief 秒杀HTTP服务启动接口。
 *
 * serve阻塞运行至收到退出信号；返回值交给进程入口作为退出码。
 */
#pragma once
#include "mall/config.hpp"
namespace mall {
/**
 * @brief 启动并阻塞运行HTTP服务，接收SIGINT/SIGTERM后关闭。
 *
 * @return 正常退出0；监听或服务失败返回非零。
 */
int serve(const Config &config);
}
