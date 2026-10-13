FROM ubuntu:24.04 AS builder
COPY --from=python:3.12.12-slim-bookworm /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
ENV DEBIAN_FRONTEND=noninteractive
ARG UBUNTU_MIRROR=https://archive.ubuntu.com/ubuntu
RUN sed -i "s|http://archive.ubuntu.com/ubuntu|${UBUNTU_MIRROR}|g;s|http://security.ubuntu.com/ubuntu|${UBUNTU_MIRROR}|g" /etc/apt/sources.list.d/ubuntu.sources && apt-get -o Acquire::Retries=3 -o Acquire::https::Timeout=30 update && apt-get install -y --no-install-recommends ca-certificates curl cmake g++ make libhiredis-dev libssl-dev nlohmann-json3-dev libpng-dev libgrpc++-dev protobuf-compiler-grpc libprotobuf-dev libabsl-dev zlib1g-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /project
COPY scripts/setup-rocketmq-sdk-wsl.sh scripts/setup-rocketmq-sdk-wsl.sh
RUN bash scripts/setup-rocketmq-sdk-wsl.sh
COPY CMakeLists.txt ./
COPY src/seckill src/seckill
COPY src/mq src/mq
COPY third_party third_party
RUN cmake -S . -B build/cpp -DBUILD_TESTING=OFF -DMALL_WITH_ROCKETMQ=ON -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH=/project/build/wsl/rocketmq-sdk-install && cmake --build build/cpp -j2
FROM ubuntu:24.04
COPY --from=python:3.12.12-slim-bookworm /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
ENV DEBIAN_FRONTEND=noninteractive
ARG UBUNTU_MIRROR=https://archive.ubuntu.com/ubuntu
RUN sed -i "s|http://archive.ubuntu.com/ubuntu|${UBUNTU_MIRROR}|g;s|http://security.ubuntu.com/ubuntu|${UBUNTU_MIRROR}|g" /etc/apt/sources.list.d/ubuntu.sources && apt-get -o Acquire::Retries=3 -o Acquire::https::Timeout=30 update && apt-get install -y --no-install-recommends ca-certificates curl libhiredis-dev libssl-dev libpng-dev libgrpc++-dev libprotobuf-dev libabsl-dev zlib1g-dev && rm -rf /var/lib/apt/lists/* && useradd -m -u 10001 mall
COPY --from=builder /project/build/wsl/rocketmq-sdk-install/lib/ /usr/local/lib/
COPY --from=builder /project/build/wsl/rocketmq-sdk-src/LICENSE /usr/share/licenses/rocketmq/LICENSE
RUN ldconfig
COPY --from=builder /project/build/cpp/src/seckill/seckill_service /usr/local/bin/
COPY --from=builder /project/build/cpp/src/mq/mall_relay_worker /usr/local/bin/
COPY src/seckill/lua /app/lua
ENV MALL_HTTP_HOST=0.0.0.0 MALL_HTTP_PORT=8083 MALL_LUA_DIR=/app/lua MALL_REDIS_HOST=redis MALL_REDIS_PORT=6379 MALL_MQ_ENDPOINT=broker:8081
USER 10001
WORKDIR /home/mall
CMD ["seckill_service", "--serve"]
