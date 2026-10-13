#include "mall/contracts.hpp"
#include "mall/service.hpp"
#include <cstdlib>
#include <iostream>
#include <string_view>

int main(int argc, char **argv) {
  try {
    mall::Config config;
    if (argc == 2 && std::string_view(argv[1]) == "--serve")
      return mall::serve(config);
    if (argc != 2 || std::string_view(argv[1]) != "--check-config") {
      std::cerr << "Usage: seckill_service --check-config | --serve\n";
      return 2;
    }
    std::cout << "{\"service\":\"seckill\",\"contractVersion\":\""
              << mall::contract_version
              << "\",\"stage\":\"S2\",\"configured\":true,\"ready\":false}\n";
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 2;
  }
}
