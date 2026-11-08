package com.seckillmall.order.business;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.servlet.http.HttpServletRequest;
import java.util.*;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;

/** 微信入口：用户创建/查询只允许本人；公开回调只接受SDK已验签解密的渠道通知。 */
@RestController
@ConditionalOnProperty(name="mall.business-enabled",havingValue="true")
public class WechatApi {
  private final Sessions sessions;private final WechatPayments payments;private final WechatGateway gateway;
  public WechatApi(Sessions sessions,WechatPayments payments,WechatGateway gateway){this.sessions=sessions;this.payments=payments;this.gateway=gateway;}
  private long user(HttpServletRequest r){return sessions.auth(r.getHeader("Authorization")).userId();}
  @GetMapping("/api/payments/config")
  public Object config(){return Map.of("provider",payments.enabled()?"WECHAT":"MOCK","wechatConfigured",payments.enabled(),"wechatIntegration","NATIVE_API_V3");}
  @PostMapping("/api/payments/wechat/native")
  public Object nativePay(@RequestBody JsonNode b,HttpServletRequest r){Input.fields(b,"orderKind","orderId");return payments.nativePay(user(r),Input.text(b,"orderKind",4,7),Input.uuid(Input.text(b,"orderId",36,36)));}
  @GetMapping("/api/payments/wechat/status")
  public Object status(@RequestParam Map<String,String> p,HttpServletRequest r){if(!p.keySet().equals(Set.of("orderKind","orderId")))throw new Fault(400,"INVALID_ARGUMENT");return payments.query(user(r),p.get("orderKind"),Input.uuid(p.get("orderId")));}
  @PostMapping("/api/payments/wechat/{action}")
  public Object action(@PathVariable String action,@RequestBody JsonNode b,HttpServletRequest r){Input.fields(b,"orderKind","orderId");long u=user(r);String kind=Input.text(b,"orderKind",4,7),id=Input.uuid(Input.text(b,"orderId",36,36));
    return switch(action){case "close"->payments.cancel(u,kind,id);case "refund"->payments.refund(u,kind,id);default->throw new Fault(404,"NOT_FOUND");};}
  private Map<String,String> headers(HttpServletRequest r){Map<String,String> h=new HashMap<>();for(String key:List.of("Wechatpay-Serial","Wechatpay-Timestamp","Wechatpay-Nonce","Wechatpay-Signature")){
    var values=Collections.list(r.getHeaders(key));if(values.size()!=1||values.get(0).isBlank())throw new Fault(400,"INVALID_WECHAT_NOTIFICATION");h.put(key,values.get(0));}return h;}
  @PostMapping("/api/payments/wechat/notify")
  public ResponseEntity<Void> notify(@RequestBody byte[] raw,HttpServletRequest r){if(!gateway.enabled())throw new Fault(503,"WECHAT_NOT_CONFIGURED");payments.paid(gateway.paymentNotification(headers(r),new String(raw,java.nio.charset.StandardCharsets.UTF_8)));return ResponseEntity.noContent().build();}
  @PostMapping("/api/payments/wechat/refund-notify")
  public ResponseEntity<Void> refundNotify(@RequestBody byte[] raw,HttpServletRequest r){if(!gateway.enabled())throw new Fault(503,"WECHAT_NOT_CONFIGURED");payments.refunded(gateway.refundNotification(headers(r),new String(raw,java.nio.charset.StandardCharsets.UTF_8)));return ResponseEntity.noContent().build();}
  @PostMapping("/api/admin/payments/wechat/recheck")
  public Object recheck(@RequestBody JsonNode b,HttpServletRequest r){sessions.auth(r.getHeader("Authorization")).admin();Input.fields(b,"orderKind","orderId");return payments.adminRecheck(Input.text(b,"orderKind",4,7),Input.uuid(Input.text(b,"orderId",36,36)));}
  @GetMapping("/api/admin/payments/wechat")
  public Object admin(HttpServletRequest r){sessions.auth(r.getHeader("Authorization")).admin();return payments.adminList();}
}
