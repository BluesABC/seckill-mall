#pragma once
#include <string>
namespace mall {
struct Captcha {
  std::string answer;
  std::string image_data_url;
};
Captcha create_captcha();
} // namespace mall
