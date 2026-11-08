package com.seckillmall.order.business;

import java.util.Map;
/** 微信渠道边界；生产实现仅使用官方SDK，测试替身只存在test源码，不提供HTTP模拟成功入口。 */
public interface WechatGateway {
  record Payment(String tradeNo,String transactionId,String state,long total,String currency,String mchid,String appid) {}
  record Refund(String tradeNo,String transactionId,String refundNo,String refundId,String state,long total,long amount,String currency) {}
  boolean enabled();
  String mchid();
  String appid();
  String prepay(String tradeNo,long amount,long expiresAtMs);
  Payment query(String tradeNo);
  void close(String tradeNo);
  Refund refund(String tradeNo,String refundNo,long amount);
  Refund queryRefund(String refundNo);
  Payment paymentNotification(Map<String,String> headers,String body);
  Refund refundNotification(Map<String,String> headers,String body);
}
