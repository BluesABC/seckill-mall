package com.seckillmall.order.business;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
import java.time.Duration;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.connection.RedisStandaloneConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceClientConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@Configuration
@ConditionalOnProperty(name = "mall.business-enabled", havingValue = "true")
public class BusinessConfig {
  @Bean(destroyMethod = "close")
  HikariDataSource dataSource(@Value("${mall.db-url}") String url,
      @Value("${mall.db-user}") String user, @Value("${mall.db-password}") String password) {
    if (password.isBlank())
      throw new IllegalStateException("MALL_DB_PASSWORD required");
    HikariConfig c = new HikariConfig();
    c.setJdbcUrl(url);
    c.setUsername(user);
    c.setPassword(password);
    c.setMaximumPoolSize(12);
    c.setConnectionTimeout(3000);
    c.setInitializationFailTimeout(-1);
    return new HikariDataSource(c);
  }
  @Bean
  JdbcTemplate jdbc(HikariDataSource ds) {
    return new JdbcTemplate(ds);
  }
  @Bean
  TransactionTemplate transactions(HikariDataSource ds) {
    TransactionTemplate t = new TransactionTemplate(new DataSourceTransactionManager(ds));
    t.setTimeout(10);
    return t;
  }
  @Bean
  LettuceConnectionFactory redisFactory(
      @Value("${mall.redis-host}") String host, @Value("${mall.redis-port}") int port) {
    return new LettuceConnectionFactory(new RedisStandaloneConfiguration(host, port),
        LettuceClientConfiguration.builder().commandTimeout(Duration.ofSeconds(3)).build());
  }
  @Bean
  StringRedisTemplate redis(LettuceConnectionFactory f) {
    return new StringRedisTemplate(f);
  }
  @Bean
  Store store(JdbcTemplate j, TransactionTemplate t) {
    return new Store(j, t);
  }
  @Bean
  Cache cache(StringRedisTemplate r, ObjectMapper m, @Value("${mall.key-prefix}") String p,
      @Value("${mall.lua-directory}") String directory) {
    return new Cache(r, m, p, directory);
  }
  @Bean
  Sessions sessions(Store s, Cache c) {
    Sessions sessions = new Sessions(s, c);
    sessions.bootstrap();
    return sessions;
  }
  @Bean
  Catalog catalog(Store s, Cache c) {
    return new Catalog(s, c);
  }
  @Bean
  Orders orders(Store s, Cache c, @Value("${mall.payment-ttl-ms}") long ttl) {
    return new Orders(s, c, ttl);
  }
  @Bean(initMethod = "start", destroyMethod = "close")
  Workers workers(Store s, Cache c, Orders o, @Value("${mall.mq-endpoint}") String endpoint,
      @Value("${mall.mq-topic}") String topic, @Value("${mall.mq-group}") String group,
      @Value("${mall.recovery-age-ms}") long age, @Value("${mall.jobs-enabled}") boolean jobs) {
    return new Workers(s, c, o, endpoint, topic, group, age, jobs);
  }
}
