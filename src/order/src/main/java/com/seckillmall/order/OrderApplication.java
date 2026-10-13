package com.seckillmall.order;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication(exclude = {
    org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration.class,
    org.springframework.boot.autoconfigure.data.redis.RedisAutoConfiguration.class,
    org.springframework.boot.autoconfigure.data.redis.RedisRepositoriesAutoConfiguration.class})
public class OrderApplication {
    public static void main(String[] args) {
        SpringApplication.run(OrderApplication.class, args);
    }
}
