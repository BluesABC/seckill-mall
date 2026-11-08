/**
 * @file captcha.hpp
 * @brief 验证码内部结果与两种生成入口。
 *
 * answer是敏感内部值；image_data_url或accessible_prompt才用于客户端呈现。
 */
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
