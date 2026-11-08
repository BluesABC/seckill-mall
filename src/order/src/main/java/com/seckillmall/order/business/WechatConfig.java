package com.seckillmall.order.business;

import org.springframework.context.annotation.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.beans.factory.annotation.Value;
import java.util.Map;

/** 默认MOCK，显式WECHAT模式且全部配置有效才启动真实渠道，缺密钥不降级伪造成功。 */
@Configuration
@ConditionalOnProperty(name="mall.business-enabled",havingValue="true")
public class WechatConfig {
  @Bean WechatGateway wechatGateway(){
    String mode=System.getenv().getOrDefault("MALL_PAYMENT_PROVIDER","MOCK");
    if(mode.equals("WECHAT"))return new WechatSdk(System.getenv());
    if(!mode.equals("MOCK"))throw new IllegalArgumentException("Unknown MALL_PAYMENT_PROVIDER");
    return new WechatGateway(){
      public boolean enabled(){return false;}public String mchid(){return "";}public String appid(){return "";}
      private Fault unavailable(){return new Fault(503,"WECHAT_NOT_CONFIGURED");}
      public String prepay(String n,long a,long e){throw unavailable();}public Payment query(String n){throw unavailable();}
      public void close(String n){throw unavailable();}public Refund refund(String n,String r,long a){throw unavailable();}
      public Refund queryRefund(String r){throw unavailable();}public Payment paymentNotification(Map<String,String> h,String b){throw unavailable();}
      public Refund refundNotification(Map<String,String> h,String b){throw unavailable();}
    };
  }
  @Bean(initMethod="start",destroyMethod="close")
  WechatPayments wechatPayments(Store s,Orders o,Retail r,WechatGateway g,@Value("${mall.jobs-enabled}") boolean jobs){return new WechatPayments(s,o,r,g,jobs);}
}
