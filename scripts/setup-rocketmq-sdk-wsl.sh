#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
sdk_commit="6b0bcc422ff1ee66198df6b4a48a4a44ad7218fa"
proto_commit="bc8e1845a8b0a1b5ec828690324401a323244354"
sdk_dir="$project_root/build/wsl/rocketmq-sdk-src"
sdk_build="$project_root/build/wsl/rocketmq-sdk-build"
sdk_prefix="$project_root/build/wsl/rocketmq-sdk-install"
archive_dir="$project_root/build/wsl/tooling"
mkdir -p "$archive_dir" "$sdk_dir"
if [[ -f "$sdk_prefix/.pin" && -f "$sdk_prefix/lib/librocketmq.so" &&
      "$(cat "$sdk_prefix/.pin")" == "$sdk_commit:$proto_commit" ]]; then
  echo "RocketMQ C++ SDK already installed at $sdk_prefix"
  exit 0
fi
client_archive="$archive_dir/rocketmq-clients.tar.gz"
proto_archive="$archive_dir/rocketmq-apis.tar.gz"
if [[ ! -f "$client_archive" ]]; then
  curl -fL --retry 3 --connect-timeout 15 --max-time 180 \
    "https://codeload.github.com/apache/rocketmq-clients/tar.gz/$sdk_commit" -o "$client_archive"
fi
if [[ ! -f "$proto_archive" ]]; then
  curl -fL --retry 3 --connect-timeout 15 --max-time 180 \
    "https://codeload.github.com/apache/rocketmq-apis/tar.gz/$proto_commit" -o "$proto_archive"
fi
echo '882da7b3869c46e93571d9330cf7c5948a8ac1175ca6cffd4c6c0097bc0d2d00  '"$client_archive" | sha256sum -c -
echo 'fc8bdcb0b0df5d095349245ff2c50fb4a6bc33cd21279764cdc0cc7041ab9b39  '"$proto_archive" | sha256sum -c -
if [[ ! -f "$sdk_dir/cpp/CMakeLists.txt" ]]; then
  tar -xzf "$client_archive" --strip-components=1 -C "$sdk_dir"
fi
if [[ ! -f "$sdk_dir/protos/apache/rocketmq/v2/definition.proto" ]]; then
  mkdir -p "$sdk_dir/protos"
  tar -xzf "$proto_archive" --strip-components=1 -C "$sdk_dir/protos"
fi
if [[ ! -L "$sdk_dir/cpp/proto/apache" ]]; then
  ln -s ../../protos/apache "$sdk_dir/cpp/proto/apache"
fi
# Ubuntu's system protobuf package provides FindProtobuf imported targets.
if grep -Fq 'find_package(protobuf 3.19 CONFIG REQUIRED)' "$sdk_dir/cpp/CMakeLists.txt"; then
  sed -i 's/find_package(protobuf 3.19 CONFIG REQUIRED)/find_package(Protobuf 3.19 REQUIRED)/' "$sdk_dir/cpp/CMakeLists.txt"
fi
cmake -S "$sdk_dir/cpp" -B "$sdk_build" -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_EXAMPLES=OFF -DBUILD_TESTS=OFF -DCMAKE_INSTALL_PREFIX="$sdk_prefix"
cmake --build "$sdk_build" -j2
cmake --install "$sdk_build"
printf '%s:%s\n' "$sdk_commit" "$proto_commit" > "$sdk_prefix/.pin"
