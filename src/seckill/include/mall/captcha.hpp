#pragma once
#include <string>
namespace mall {
struct Captcha {
  std::string answer;
  std::string image_data_url;
  std::string accessible_prompt;
};
Captcha create_captcha();
Captcha create_accessible_captcha();
} // namespace mall
