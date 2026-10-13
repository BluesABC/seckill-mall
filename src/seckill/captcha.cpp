#include "mall/captcha.hpp"
#include <openssl/evp.h>
#include <openssl/rand.h>
#include <png.h>
#include <stdexcept>
#include <vector>

namespace mall {
Captcha create_captcha() {
  constexpr int width = 180, height = 60;
  std::vector<unsigned char> pixels(width * height * 3, 245);
  auto random = [](int range) {
    unsigned char byte;
    do {
      if (RAND_bytes(&byte, 1) != 1)
        throw std::runtime_error("Entropy unavailable");
    } while (byte >= 256 - (256 % range));
    return byte % range;
  };
  auto pixel = [&](int x, int y, int r, int g, int b) {
    if (x >= 0 && x < width && y >= 0 && y < height) {
      auto offset = (y * width + x) * 3;
      pixels[offset] = r;
      pixels[offset + 1] = g;
      pixels[offset + 2] = b;
    }
  };
  static constexpr const char *glyphs[] = {
      "11111100011000110001100011000111111",
      "00100011000010000100001000010001110",
      "11111000010000111111100001000011111",
      "11111000010000101111000010000111111",
      "10001100011000111111000010000100001",
      "11111100001000011111000010000111111",
      "11111100001000011111100011000111111",
      "11111000010001000100010000100001000",
      "11111100011000111111100011000111111",
      "11111100011000111111000010000111111"};
  Captcha captcha;
  for (int n = 0; n < 6; ++n) {
    int digit = random(10);
    captcha.answer += static_cast<char>('0' + digit);
    int x0 = 8 + n * 27 + random(3), y0 = 10 + random(8);
    for (int y = 0; y < 7; ++y)
      for (int x = 0; x < 5; ++x)
        if (glyphs[digit][y * 5 + x] == '1')
          for (int dy = 0; dy < 4; ++dy)
            for (int dx = 0; dx < 4; ++dx)
              pixel(x0 + x * 4 + dx, y0 + y * 4 + dy, 30, 55, 75);
  }
  for (int n = 0; n < 160; ++n)
    pixel(random(width), random(height), 130, 145, 155);
  png_image image{};
  image.version = PNG_IMAGE_VERSION;
  image.width = width;
  image.height = height;
  image.format = PNG_FORMAT_RGB;
  png_alloc_size_t size = 0;
  if (!png_image_write_to_memory(&image, nullptr, &size, 0, pixels.data(), 0,
                                 nullptr))
    throw std::runtime_error("PNG encode failed");
  std::vector<unsigned char> bytes(size);
  if (!png_image_write_to_memory(&image, bytes.data(), &size, 0, pixels.data(),
                                 0, nullptr))
    throw std::runtime_error("PNG encode failed");
  std::string encoded(4 * ((size + 2) / 3), '\0');
  EVP_EncodeBlock(reinterpret_cast<unsigned char *>(encoded.data()),
                  bytes.data(), static_cast<int>(size));
  captcha.image_data_url = "data:image/png;base64," + encoded;
  return captcha;
}
} // namespace mall
