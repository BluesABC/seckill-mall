/**
 * @file main.cpp
 * @brief 早期MQ适配层配置检查入口。
 *
 * 此程序不是Broker，也不是实际relay；真实消息投递入口为mall_relay_worker。
 */
#include <iostream>
#include <string_view>
#include "mall/mq/publisher.hpp"
int main(int argc, char** argv) {
  if (argc != 2 || std::string_view(argv[1]) != "--check-config") {
    std::cerr << "S0 skeleton only. Usage: mall_mq --check-config\n";
    return 2;
  }
  std::cout << "{\"service\":\"mq-adapter\",\"backend\":\"RocketMQ\",\"ready\":false,"
               "\"sdkIntegrated\":false,\"highAvailability\":false}\n";
}
