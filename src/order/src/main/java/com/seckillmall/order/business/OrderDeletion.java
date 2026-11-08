package com.seckillmall.order.business;

import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.*;

/** 终态订单逻辑删除。归属校验及行锁先于写删除标记，不删除交易/回补依据。 */
@RestController
@ConditionalOnProperty(name="mall.business-enabled",havingValue="true")
public class OrderDeletion {
  private final Store store;private final Sessions sessions;private final Orders orders;
  public OrderDeletion(Store store,Sessions sessions,Orders orders){this.store=store;this.sessions=sessions;this.orders=orders;}
  @DeleteMapping("/api/shop/orders/{id}")
  public Object shop(@PathVariable String id,HttpServletRequest r){return delete("SHOP",id,r);}
  @DeleteMapping("/api/shop/seckill/{id}")
  public Object seckill(@PathVariable String id,HttpServletRequest r){return delete("SECKILL",id,r);}
  @PostMapping("/api/shop/seckill/{id}/cancel")
  public Object cancel(@PathVariable String id,HttpServletRequest r){return orders.cancel(sessions.auth(r.getHeader("Authorization")).userId(),Input.uuid(id));}

  private Object delete(String kind,String id,HttpServletRequest r){
    long user=sessions.auth(r.getHeader("Authorization")).userId();Input.uuid(id);
    return store.transaction(()->{
      var order=store.one("SELECT status FROM "+(kind.equals("SHOP")?"shop_orders":"orders")+" WHERE id=? AND user_id=? FOR UPDATE",id,user);
      if(order==null)throw new Fault(404,"NOT_FOUND");
      boolean allowed="CLOSED".equals(order.get("status"))||"DELIVERED".equals(order.get("status"))||"REFUNDED".equals(order.get("status"));
      if(kind.equals("SECKILL")){
        var delivery=store.one("SELECT status FROM shop_seckill_delivery WHERE order_id=?",id);
        var refund=store.one("SELECT r.id FROM mock_refunds r JOIN payments p ON p.id=r.payment_id WHERE p.order_id=?",id);
        var wx=store.one("SELECT state FROM wx_payments WHERE order_kind='SECKILL' AND order_id=?",id);
        allowed=allowed||(delivery!=null&&"DELIVERED".equals(delivery.get("status")))||refund!=null||(wx!=null&&"REFUNDED".equals(wx.get("state")));
      }
      if(!allowed)throw new Fault(409,"ORDER_DELETE_NOT_ALLOWED");
      store.db.update("INSERT IGNORE INTO order_deletions(order_kind,order_id,user_id,deleted_at_ms) VALUES(?,?,?,?)",kind,id,user,store.now());
      return Map.of("orderId",id,"status","DELETED");
    });
  }
}
