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
