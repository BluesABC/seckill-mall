package com.seckillmall.order.business;

import com.wechat.pay.java.core.RSAPublicKeyConfig;
import com.wechat.pay.java.core.http.DefaultHttpClientBuilder;
import com.wechat.pay.java.core.notification.NotificationParser;
import com.wechat.pay.java.core.notification.RequestParam;
import com.wechat.pay.java.service.payments.nativepay.NativePayService;
import com.wechat.pay.java.service.payments.nativepay.model.*;
import com.wechat.pay.java.service.payments.model.Transaction;
import com.wechat.pay.java.service.refund.RefundService;
import com.wechat.pay.java.service.refund.model.CreateRequest;
import com.wechat.pay.java.service.refund.model.AmountReq;
import com.wechat.pay.java.service.refund.model.QueryByOutRefundNoRequest;
import com.wechat.pay.java.service.refund.model.RefundNotification;
import java.nio.file.*;
import java.net.URI;
import java.time.*;
import java.util.*;

/** 官方SDK0.2.17、公钥模式。验签/解密由SDK执行；私钥、APIv3密钥只从挂载文件读取。 */
public final class WechatSdk implements WechatGateway {
  private final String merchant,app,notify;
  private final NativePayService nativePay;
  private final RefundService refunds;
  private final NotificationParser parser;
  public WechatSdk(Map<String,String> env) {
    merchant=required(env,"WECHAT_MCH_ID");app=required(env,"WECHAT_APP_ID");notify=required(env,"WECHAT_NOTIFY_URL");
    URI uri=URI.create(notify);
    if(!"https".equals(uri.getScheme()) || uri.getHost()==null || uri.getUserInfo()!=null || uri.getQuery()!=null || uri.getFragment()!=null || !uri.getPath().equals("/api/payments/wechat/notify"))
      throw new IllegalArgumentException("WECHAT_NOTIFY_URL must be an HTTPS payment notification URL");
    try {
      String key=Files.readString(Path.of(required(env,"WECHAT_API_V3_KEY_PATH"))).strip();
      if(key.getBytes(java.nio.charset.StandardCharsets.UTF_8).length!=32)throw new IllegalArgumentException("APIv3 key must be 32 bytes");
      var config=new RSAPublicKeyConfig.Builder().merchantId(merchant).privateKeyFromPath(required(env,"WECHAT_PRIVATE_KEY_PATH"))
        .merchantSerialNumber(required(env,"WECHAT_MERCHANT_SERIAL"))
        .publicKeyFromPath(required(env,"WECHAT_PAY_PUBLIC_KEY_PATH")).publicKeyId(required(env,"WECHAT_PAY_PUBLIC_KEY_ID")).apiV3Key(key).build();
      var http=new DefaultHttpClientBuilder().config(config).connectTimeoutMs(3000).readTimeoutMs(5000).writeTimeoutMs(5000).build();
      nativePay=new NativePayService.Builder().httpClient(http).build();refunds=new RefundService.Builder().httpClient(http).build();parser=new NotificationParser(config);
    } catch(java.io.IOException e){throw new IllegalArgumentException("WeChat secret files unavailable");}
  }
  private static String required(Map<String,String> env,String key){String v=env.get(key);if(v==null||v.isBlank())throw new IllegalArgumentException(key+" required");return v;}
  public boolean enabled(){return true;}public String mchid(){return merchant;}public String appid(){return app;}
  public String prepay(String tradeNo,long value,long expires){
    Amount amount=new Amount();amount.setTotal(Math.toIntExact(value));amount.setCurrency("CNY");
    PrepayRequest request=new PrepayRequest();request.setMchid(merchant);request.setAppid(app);request.setAmount(amount);request.setOutTradeNo(tradeNo);
    request.setDescription("SNKR DROP 运动鞋订单");request.setNotifyUrl(notify);request.setTimeExpire(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ssXXX").format(Instant.ofEpochMilli(expires).atOffset(ZoneOffset.ofHours(8))));
    return nativePay.prepay(request).getCodeUrl();
  }
  private Payment payment(Transaction tx){
    var amount=tx.getAmount();
    // 非成功查单可能没有金额，保留未知哨兵；SUCCESS落账仍必须严格匹配金额/币种。
    long total=amount==null||amount.getTotal()==null?-1:amount.getTotal();
    String currency=amount==null?"":Objects.toString(amount.getCurrency(),"");
    return new Payment(tx.getOutTradeNo(),tx.getTransactionId(),Objects.toString(tx.getTradeState(),""),total,currency,tx.getMchid(),tx.getAppid());
  }
  public Payment query(String number){var r=new QueryOrderByOutTradeNoRequest();r.setMchid(merchant);r.setOutTradeNo(number);return payment(nativePay.queryOrderByOutTradeNo(r));}
  public void close(String number){var r=new CloseOrderRequest();r.setMchid(merchant);r.setOutTradeNo(number);nativePay.closeOrder(r);}
  public Refund refund(String number,String refundNo,long value){
    var r=new CreateRequest();r.setOutTradeNo(number);r.setOutRefundNo(refundNo);r.setReason("用户申请未发货全额退款");
    r.setNotifyUrl(URI.create(notify).resolve("/api/payments/wechat/refund-notify").toString());var a=new AmountReq();a.setTotal(value);a.setRefund(value);a.setCurrency("CNY");r.setAmount(a);
    return refund(refunds.create(r));
  }
  private Refund refund(com.wechat.pay.java.service.refund.model.Refund r){return new Refund(r.getOutTradeNo(),r.getTransactionId(),r.getOutRefundNo(),r.getRefundId(),r.getStatus().toString(),r.getAmount().getTotal(),r.getAmount().getRefund(),r.getAmount().getCurrency());}
  public Refund queryRefund(String number){var r=new QueryByOutRefundNoRequest();r.setOutRefundNo(number);return refund(refunds.queryByOutRefundNo(r));}
  /** 原始JSON字节内容必须保持；SDK先验RSA签名，再用APIv3密钥AES-GCM解密。 */
  private RequestParam notification(Map<String,String> h,String body){
    try{if(Math.abs(Instant.now().getEpochSecond()-Long.parseLong(h.get("Wechatpay-Timestamp")))>300)throw new IllegalArgumentException("stale");
      return new RequestParam.Builder().serialNumber(h.get("Wechatpay-Serial")).timestamp(h.get("Wechatpay-Timestamp")).nonce(h.get("Wechatpay-Nonce")).signature(h.get("Wechatpay-Signature")).body(body).build();
    }catch(RuntimeException e){throw new Fault(400,"INVALID_WECHAT_NOTIFICATION");}
  }
  private void event(String body,String... expected){try{String type=new com.fasterxml.jackson.databind.ObjectMapper().readTree(body).path("event_type").asText();if(!Set.of(expected).contains(type))throw new Fault(400,"INVALID_WECHAT_EVENT");}catch(java.io.IOException e){throw new Fault(400,"INVALID_WECHAT_NOTIFICATION");}}
  public Payment paymentNotification(Map<String,String> h,String body){try{var tx=parser.parse(notification(h,body),Transaction.class);event(body,"TRANSACTION.SUCCESS");return payment(tx);}catch(RuntimeException e){throw new Fault(400,"INVALID_WECHAT_NOTIFICATION");}}
  public Refund refundNotification(Map<String,String> h,String body){try{RefundNotification r=parser.parse(notification(h,body),RefundNotification.class);event(body,"REFUND.SUCCESS","REFUND.CLOSED","REFUND.ABNORMAL");return new Refund(r.getOutTradeNo(),r.getTransactionId(),r.getOutRefundNo(),r.getRefundId(),r.getRefundStatus().toString(),r.getAmount().getTotal(),r.getAmount().getRefund(),r.getAmount().getCurrency());}catch(RuntimeException e){throw new Fault(400,"INVALID_WECHAT_NOTIFICATION");}}
}
