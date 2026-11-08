package com.seckillmall.order.business;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.servlet.http.HttpServletRequest;
import java.util.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;

/** 模拟收银展示：生成二维码不会改变订单状态，确认付款仍复用原有幂等MOCK支付事务。 */
@RestController
@ConditionalOnProperty(name="mall.business-enabled",havingValue="true")
public class MockCashierApi {
  private final Store store;private final Sessions sessions;
  public MockCashierApi(Store store,Sessions sessions){this.store=store;this.sessions=sessions;}
  @PostMapping("/api/payments/mock/session")
  public Object session(@RequestBody JsonNode b,HttpServletRequest request){
    long user=sessions.auth(request.getHeader("Authorization")).userId();
    Input.fields(b,"orderKind","orderId","method");
    String kind=Input.text(b,"orderKind",4,7),id=Input.uuid(Input.text(b,"orderId",36,36)),method=Input.text(b,"method",1,20);
    if(!Set.of("SHOP","SECKILL").contains(kind)||!Set.of("WECHAT_DEMO","DIRECT_DEMO").contains(method))throw new Fault(400,"INVALID_ARGUMENT");
    var order=store.one("SELECT amount_fen,status,expires_at_ms FROM "+(kind.equals("SHOP")?"shop_orders":"orders")+" WHERE id=? AND user_id=?",id,user);
    if(order==null)throw new Fault(404,"NOT_FOUND");
    PaymentGuard.mockPay(store,kind,id);
    if(!"PENDING_PAYMENT".equals(order.get("status"))||Store.number(order,"expires_at_ms")<=store.now())throw new Fault(409,"ORDER_CLOSED");
    var result=new LinkedHashMap<String,Object>();result.put("orderId",id);result.put("orderKind",kind);result.put("method",method);result.put("provider","MOCK");result.put("state","WAITING_CONFIRMATION");
    result.put("amountFen",order.get("amount_fen"));result.put("expiresAtMs",order.get("expires_at_ms"));
    if(method.equals("WECHAT_DEMO"))result.put("qrImage",WechatPayments.encodeQr("SNKR//DROP DEMO ONLY\n订单："+id+"\n金额："+order.get("amount_fen")+"分\n仅演示，无真实扣款。不要向任何人转账。"));
    return Store.wire(result);
  }
}
