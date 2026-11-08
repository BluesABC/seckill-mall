package com.seckillmall.order.business;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.servlet.http.HttpServletRequest;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.*;

/**
 * 普通商城事务边界。独立订单/明细快照，只消费SKU未分配库存，绝不借用活动库存。
 * 同一订单操作先锁订单，再按skuId升序锁SKU；创建按用户行串行幂等与地址/购物车变更。
 * 金额单位为分，模拟支付不产生外部资金，物流号为管理员手工登记。
 */
@RestController
@ConditionalOnProperty(name="mall.business-enabled",havingValue="true")
public class Retail {
  private final Store store;
  private final Sessions sessions;
  private final long ttl;
  public Retail(Store store, Sessions sessions,@Value("${mall.payment-ttl-ms}") long ttl) {
    this.store=store; this.sessions=sessions; this.ttl=ttl;
  }
  private long user(HttpServletRequest r) { return sessions.auth(r.getHeader("Authorization")).userId(); }
  private void admin(HttpServletRequest r) { sessions.auth(r.getHeader("Authorization")).admin(); }
  private void lockUser(long u) { store.one("SELECT id FROM users WHERE id=? FOR UPDATE",u); }
  private List<Map<String,Object>> wire(List<Map<String,Object>> rows) { return rows.stream().map(Store::wire).toList(); }
  @GetMapping("/api/shop/addresses")
  public Object addresses(HttpServletRequest r) {
    return Map.of("items",wire(store.db.queryForList("SELECT id,recipient,phone,address FROM shop_addresses WHERE user_id=? ORDER BY id DESC",user(r))));
  }
  /** 收货地址最多20条；删除不修改订单中已保存的收货快照。 */
  @PostMapping("/api/shop/addresses")
  public Object address(@RequestBody JsonNode b,HttpServletRequest r) {
    long u=user(r);Input.fields(b,"recipient","phone","address");
    String name=Input.text(b,"recipient",1,60).trim(),phone=Input.text(b,"phone",5,30),address=Input.text(b,"address",5,400).trim();
    if(name.isEmpty() || address.length()<5 || !phone.matches("[+0-9 ()-]{5,30}"))throw new Fault(400,"INVALID_ARGUMENT");
    return store.transaction(()->{lockUser(u);
      if(store.db.queryForObject("SELECT COUNT(*) FROM shop_addresses WHERE user_id=?",Integer.class,u)>=20)throw new Fault(409,"ADDRESS_LIMIT");
      return Map.of("id",Long.toString(store.insert("INSERT INTO shop_addresses(user_id,recipient,phone,address) VALUES(?,?,?,?)",u,name,phone,address)));
    });
  }
  @DeleteMapping("/api/shop/addresses/{id}")
  public Object deleteAddress(@PathVariable String id,HttpServletRequest r) {
    long u=user(r);long address=Input.id(id);
    return store.transaction(()->{lockUser(u);store.db.update("DELETE FROM shop_addresses WHERE id=? AND user_id=?",address,u);return Map.of("status","DELETED");});
  }
  @GetMapping("/api/shop/cart")
  public Object cart(HttpServletRequest r) {
    return Map.of("items",wire(store.db.queryForList("SELECT c.sku_id AS skuId,c.quantity,s.price_fen AS priceFen,s.size_eu AS sizeEu,s.unallocated_stock AS stock,g.title,g.image_url AS imageUrl,g.enabled FROM shop_cart c JOIN skus s ON s.id=c.sku_id JOIN goods g ON g.id=s.goods_id WHERE c.user_id=? ORDER BY c.sku_id",user(r))));
  }
  /** 设置绝对数量，不在网络重试时重复累加；购物车不锁库存。 */
  @PutMapping("/api/shop/cart")
  public Object putCart(@RequestBody JsonNode b,HttpServletRequest r) {
    long u=user(r);Input.fields(b,"skuId","quantity");long sku=Input.id(b,"skuId"),q=Input.id(b,"quantity");
    if(q>10)throw new Fault(400,"INVALID_ARGUMENT");
    return store.transaction(()->{lockUser(u);
      if(store.one("SELECT s.id FROM skus s JOIN goods g ON g.id=s.goods_id WHERE s.id=? AND g.enabled=1",sku)==null)throw new Fault(404,"NOT_FOUND");
      if(store.one("SELECT sku_id FROM shop_cart WHERE user_id=? AND sku_id=?",u,sku)==null && store.db.queryForObject("SELECT COUNT(*) FROM shop_cart WHERE user_id=?",Integer.class,u)>=20)throw new Fault(409,"CART_LIMIT");
      store.db.update("INSERT INTO shop_cart VALUES(?,?,?) ON DUPLICATE KEY UPDATE quantity=?",u,sku,q,q);return Map.of("status","SAVED");
    });
  }
  @DeleteMapping("/api/shop/cart/{id}")
  public Object deleteCart(@PathVariable String id,HttpServletRequest r) {
    long u=user(r),sku=Input.id(id);
    return store.transaction(()->{lockUser(u);store.db.update("DELETE FROM shop_cart WHERE user_id=? AND sku_id=?",u,sku);return Map.of("status","DELETED");});
  }
  private TreeMap<Long,Long> items(JsonNode b) {
    if(!b.isArray() || b.isEmpty() || b.size()>20)throw new Fault(400,"INVALID_ARGUMENT");
    TreeMap<Long,Long> map=new TreeMap<>();
    for(JsonNode v:b){Input.fields(v,"skuId","quantity");long q=Input.id(v,"quantity");
      if(q>10 || map.put(Input.id(v,"skuId"),q)!=null)throw new Fault(400,"INVALID_ARGUMENT");}
    return map;
  }
  /** 全部明细同一事务，价格从加锁SKU读取；任一库存不足整单回滚。 */
  @PostMapping("/api/shop/checkout")
  public Object checkout(@RequestBody JsonNode b,HttpServletRequest r) {
    long u=user(r);Input.fields(b,"items","addressId","idempotencyKey");
    var quantities=items(b.get("items"));long aid=Input.id(b,"addressId");String retry=Input.uuid(Input.text(b,"idempotencyKey",36,36));
    String fingerprint=Cache.hash(quantities.toString()+":"+aid);
    return store.transaction(()->{
      lockUser(u);var prior=store.one("SELECT id,fingerprint FROM shop_orders WHERE user_id=? AND retry_key=?",u,retry);
      if(prior!=null){if(!fingerprint.equals(prior.get("fingerprint")))throw new Fault(409,"IDEMPOTENCY_CONFLICT");return detail(u,prior.get("id").toString());}
      var address=store.one("SELECT * FROM shop_addresses WHERE id=? AND user_id=?",aid,u);
      if(address==null)throw new Fault(404,"ADDRESS_NOT_FOUND");
      List<Map<String,Object>> snapshots=new ArrayList<>();long amount=0;
      for(var entry:quantities.entrySet()){
        var sku=store.one("SELECT s.*,g.title,g.image_url,g.enabled FROM skus s JOIN goods g ON g.id=s.goods_id WHERE s.id=? FOR UPDATE",entry.getKey());
        if(sku==null || !Store.flag(sku,"enabled"))throw new Fault(409,"PRODUCT_UNAVAILABLE");
        if(store.db.update("UPDATE skus SET unallocated_stock=unallocated_stock-?,version=version+1 WHERE id=? AND unallocated_stock>=?",entry.getValue(),entry.getKey(),entry.getValue())!=1)throw new Fault(409,"INSUFFICIENT_STOCK");
        amount=Math.addExact(amount,Math.multiplyExact(Store.number(sku,"price_fen"),entry.getValue()));snapshots.add(sku);
      }
      String id=UUID.randomUUID().toString();long now=store.now();
      store.db.update("INSERT INTO shop_orders(id,user_id,retry_key,fingerprint,recipient,phone,address,amount_fen,status,created_at_ms,expires_at_ms) VALUES(?,?,?,?,?,?,?,?,'PENDING_PAYMENT',?,?)",id,u,retry,fingerprint,address.get("recipient"),address.get("phone"),address.get("address"),amount,now,now+ttl);
      for(var sku:snapshots){long sid=Store.number(sku,"id");
        store.db.update("INSERT INTO shop_items VALUES(?,?,?,?,?,?,?)",id,sid,sku.get("title"),Objects.toString(sku.get("size_eu"),""),sku.get("image_url"),quantities.get(sid),sku.get("price_fen"));
        // 仅清除数量仍与提交快照一致的购物车行，避免误删后来的数量调整。
        store.db.update("DELETE FROM shop_cart WHERE user_id=? AND sku_id=? AND quantity=?",u,sid,quantities.get(sid));}
      return detail(u,id);
    });
  }
  private Map<String,Object> detail(long u,String id) {
    var row=store.one("SELECT * FROM shop_orders WHERE id=? AND user_id=?",id,u);
    if(row==null)throw new Fault(404,"NOT_FOUND");
    var out=new LinkedHashMap<String,Object>(Store.wire(row));out.remove("fingerprint");out.remove("retry_key");
    out.put("items",wire(store.db.queryForList("SELECT * FROM shop_items WHERE order_id=? ORDER BY sku_id",id)));out.put("provider",row.get("provider"));return out;
  }
  @GetMapping("/api/shop/orders")
  public Object list(HttpServletRequest r) {
    long u=user(r);expire(u);
    return Map.of("items",store.db.queryForList("SELECT id FROM shop_orders WHERE user_id=? AND NOT EXISTS (SELECT 1 FROM order_deletions d WHERE d.order_kind='SHOP' AND d.order_id=shop_orders.id AND d.user_id=shop_orders.user_id) ORDER BY created_at_ms DESC LIMIT 100",u).stream().map(v->detail(u,v.get("id").toString())).toList());
  }
  @GetMapping("/api/shop/orders/{id}")
  public Object get(@PathVariable String id,HttpServletRequest r) {long u=user(r);Input.uuid(id);expire(u);return detail(u,id);}
  /** 释放订单占用的普通库存，明细按SKU排序；仅状态转换成功时调用一次。 */
  void release(String id) {
    for(var item:store.db.queryForList("SELECT sku_id,quantity FROM shop_items WHERE order_id=? ORDER BY sku_id",id))
      store.db.update("UPDATE skus SET unallocated_stock=unallocated_stock+?,version=version+1 WHERE id=?",item.get("quantity"),item.get("sku_id"));
  }
  private void expire(long u) {
    for(var row:store.db.queryForList("SELECT id FROM shop_orders WHERE user_id=? AND status='PENDING_PAYMENT' AND expires_at_ms<=? ORDER BY id LIMIT 100",u,store.now()))
      store.transaction(()->{String id=row.get("id").toString();var order=store.one("SELECT status,expires_at_ms FROM shop_orders WHERE id=? FOR UPDATE",id);
        if(PaymentGuard.mayClose(store,"SHOP",id) && "PENDING_PAYMENT".equals(order.get("status")) && Store.number(order,"expires_at_ms")<=store.now()){
          store.db.update("UPDATE shop_orders SET status='CLOSED' WHERE id=?",id);release(id);}
        return null;});
  }
  /** 由现有后台维护任务周期调用，崩溃后仍以数据库状态重新扫描。 */
  void closeWechat(String id){store.transaction(()->{var o=store.one("SELECT status FROM shop_orders WHERE id=? FOR UPDATE",id);
    if(!PaymentGuard.mayClose(store,"SHOP",id))throw new Fault(409,"WECHAT_CLOSE_REQUIRED");
    if("PENDING_PAYMENT".equals(o.get("status"))){store.db.update("UPDATE shop_orders SET status='CLOSED' WHERE id=?",id);release(id);}return null;});}
  public void expireAll() {
    for(var row:store.db.queryForList("SELECT DISTINCT user_id FROM shop_orders WHERE status='PENDING_PAYMENT' AND expires_at_ms<=? LIMIT 100",store.now()))expire(Store.number(row,"user_id"));
  }
  @PostMapping("/api/shop/orders/{id}/{action}")
  public Object action(@PathVariable String id,@PathVariable String action,@RequestBody JsonNode b,HttpServletRequest r) {
    long u=user(r);Input.uuid(id);Input.fields(b,"idempotencyKey");Input.uuid(Input.text(b,"idempotencyKey",36,36));
    if(!Set.of("pay","cancel","refund","receive").contains(action))throw new Fault(404,"NOT_FOUND");
    expire(u);
    return store.transaction(()->{
      var order=store.one("SELECT * FROM shop_orders WHERE id=? AND user_id=? FOR UPDATE",id,u);
      if(order==null)throw new Fault(404,"NOT_FOUND");String state=order.get("status").toString();
      if(action.equals("pay")){
        PaymentGuard.mockPay(store,"SHOP",id);
        if(!Set.of("PAID","SHIPPED","DELIVERED","REFUNDED").contains(state)){
          if(!state.equals("PENDING_PAYMENT") || Store.number(order,"expires_at_ms")<=store.now())throw new Fault(409,"ORDER_CLOSED");
          store.db.update("UPDATE shop_orders SET status='PAID',payment_id=?,paid_at_ms=? WHERE id=?",UUID.randomUUID().toString(),store.now(),id);}
      } else if(action.equals("cancel")){
        if(!PaymentGuard.mayClose(store,"SHOP",id))throw new Fault(409,"USE_WECHAT_CLOSE");
        if(!state.equals("CLOSED")){if(!state.equals("PENDING_PAYMENT"))throw new Fault(409,"STATE_CONFLICT");store.db.update("UPDATE shop_orders SET status='CLOSED' WHERE id=?",id);release(id);}
      } else if(action.equals("refund")){
        PaymentGuard.noIntent(store,"SHOP",id);
        if(!state.equals("REFUNDED")){if(!state.equals("PAID"))throw new Fault(409,"REFUND_NOT_ALLOWED");store.db.update("UPDATE shop_orders SET status='REFUNDED',refund_id=?,refunded_at_ms=? WHERE id=?",UUID.randomUUID().toString(),store.now(),id);release(id);}
      } else if(!state.equals("DELIVERED")){
        if(!state.equals("SHIPPED"))throw new Fault(409,"STATE_CONFLICT");store.db.update("UPDATE shop_orders SET status='DELIVERED',delivered_at_ms=? WHERE id=?",store.now(),id);
      }
      return detail(u,id);
    });
  }
  /** 受审计的普通库存补货；只增未分配库存，未知响应沿用原幂等键重试。 */
  @PostMapping("/api/admin/shop/restock")
  public Object restock(@RequestBody JsonNode b,HttpServletRequest r) {
    admin(r);long actor=user(r);Input.fields(b,"skuId","quantity","idempotencyKey");
    long sku=Input.id(b,"skuId"),q=Input.id(b,"quantity");String retry=Input.uuid(Input.text(b,"idempotencyKey",36,36));
    if(q>1000000)throw new Fault(400,"INVALID_ARGUMENT");
    return store.transaction(()->{
      // 以管理员行串行其补货键，再锁SKU；结算同样先用户、后SKU，不引入反序。
      lockUser(actor);var prior=store.one("SELECT * FROM shop_restocks WHERE id=?",retry);
      if(prior!=null){if(Store.number(prior,"sku_id")!=sku || Store.number(prior,"quantity")!=q || Store.number(prior,"actor_id")!=actor)throw new Fault(409,"IDEMPOTENCY_CONFLICT");return Map.of("restockId",retry);}
      if(store.db.update("UPDATE skus SET unallocated_stock=unallocated_stock+?,version=version+1 WHERE id=? AND unallocated_stock<=100000000-?",q,sku,q)!=1)throw new Fault(409,"STOCK_LIMIT_OR_NOT_FOUND");
      store.db.update("INSERT INTO shop_restocks VALUES(?,?,?,?,?)",retry,sku,q,actor,store.now());return Map.of("restockId",retry);
    });
  }
  /** 秒杀订单履约视图：原PAID库存事实不变，物流/退款状态单独合并展示。 */
  private List<Map<String,Object>> seckillOrders(Long user) {
    var rows=store.db.queryForList("SELECT o.id,o.user_id,o.amount_fen,o.status,o.created_at_ms,o.expires_at_ms,p.id AS payment_id,p.provider,r.id AS refund_id,d.recipient,d.phone,d.address,d.status AS delivery_status,d.carrier,d.tracking,g.title,g.image_url,s.size_eu,o.sku_id,o.quantity FROM orders o JOIN skus s ON s.id=o.sku_id JOIN goods g ON g.id=s.goods_id LEFT JOIN payments p ON p.order_id=o.id LEFT JOIN mock_refunds r ON r.payment_id=p.id LEFT JOIN shop_seckill_delivery d ON d.order_id=o.id " + (user==null?"":"WHERE o.user_id=? AND NOT EXISTS (SELECT 1 FROM order_deletions x WHERE x.order_kind='SECKILL' AND x.order_id=o.id AND x.user_id=o.user_id) ") + "ORDER BY o.created_at_ms DESC LIMIT 100",user==null?new Object[]{}:new Object[]{user});
    List<Map<String,Object>> out=new ArrayList<>();
    for(var row:rows){var copy=new LinkedHashMap<String,Object>(Store.wire(row));copy.put("source","SECKILL");
      var wx=store.one("SELECT state,refund_id FROM wx_payments WHERE order_kind='SECKILL' AND order_id=?",row.get("id"));
      if(wx!=null&&"REFUNDED".equals(wx.get("state"))){copy.put("status","REFUNDED");copy.put("refund_id",wx.get("refund_id"));}
      if(row.get("refund_id")!=null)copy.put("status","REFUNDED");
      else if(Set.of("SHIPPED","DELIVERED").contains(Objects.toString(row.get("delivery_status"),"")))copy.put("status",row.get("delivery_status"));
      Map<String,Object> item=new LinkedHashMap<>();for(String key:List.of("sku_id","title","size_eu","image_url","quantity"))item.put(key,copy.get(key));
      item.put("price_fen",copy.get("amount_fen"));copy.put("items",List.of(item));out.add(copy);}
    return out;
  }
  @GetMapping("/api/shop/seckill/orders")
  public Object seckillList(HttpServletRequest r) {return Map.of("items",seckillOrders(user(r)));}
  @GetMapping("/api/admin/shop/seckill/orders")
  public Object seckillAdminList(HttpServletRequest r) {admin(r);return Map.of("items",seckillOrders(null));}
  /** 只允许本人已付款未退款、未发货订单设置地址；快照不随地址簿删除而变化。 */
  @PostMapping("/api/shop/seckill/{id}/address")
  public Object seckillAddress(@PathVariable String id,@RequestBody JsonNode b,HttpServletRequest r) {
    long u=user(r);Input.uuid(id);Input.fields(b,"addressId");long aid=Input.id(b,"addressId");
    return store.transaction(()->{lockUser(u);var order=store.one("SELECT status FROM orders WHERE id=? AND user_id=? FOR UPDATE",id,u);
      if(order==null)throw new Fault(404,"NOT_FOUND");
      if(!"PAID".equals(order.get("status")) || store.one("SELECT r.id FROM mock_refunds r JOIN payments p ON p.id=r.payment_id WHERE p.order_id=?",id)!=null)throw new Fault(409,"STATE_CONFLICT");
      PaymentGuard.mayShip(store,"SECKILL",id);
      var delivery=store.one("SELECT status FROM shop_seckill_delivery WHERE order_id=?",id);
      if(delivery!=null && !"READY".equals(delivery.get("status")))throw new Fault(409,"STATE_CONFLICT");
      var a=store.one("SELECT * FROM shop_addresses WHERE id=? AND user_id=?",aid,u);if(a==null)throw new Fault(404,"ADDRESS_NOT_FOUND");
      store.db.update("INSERT INTO shop_seckill_delivery(order_id,recipient,phone,address) VALUES(?,?,?,?) ON DUPLICATE KEY UPDATE recipient=?,phone=?,address=?",id,a.get("recipient"),a.get("phone"),a.get("address"),a.get("recipient"),a.get("phone"),a.get("address"));return Map.of("status","SAVED");});
  }
  @PostMapping("/api/admin/shop/seckill/{id}/ship")
  public Object seckillShip(@PathVariable String id,@RequestBody JsonNode b,HttpServletRequest r) {
    admin(r);Input.uuid(id);Input.fields(b,"carrier","tracking");String carrier=Input.text(b,"carrier",1,60).trim(),tracking=Input.text(b,"tracking",1,100);
    if(carrier.isEmpty() || !tracking.matches("[A-Za-z0-9-]{1,100}"))throw new Fault(400,"INVALID_ARGUMENT");
    return store.transaction(()->{var order=store.one("SELECT status FROM orders WHERE id=? FOR UPDATE",id);if(order==null)throw new Fault(404,"NOT_FOUND");
      if(!"PAID".equals(order.get("status")) || store.one("SELECT r.id FROM mock_refunds r JOIN payments p ON p.id=r.payment_id WHERE p.order_id=?",id)!=null)throw new Fault(409,"STATE_CONFLICT");
      PaymentGuard.mayShip(store,"SECKILL",id);
      var d=store.one("SELECT * FROM shop_seckill_delivery WHERE order_id=?",id);if(d==null)throw new Fault(409,"ADDRESS_REQUIRED");
      if(!"READY".equals(d.get("status"))){if(!carrier.equals(d.get("carrier")) || !tracking.equals(d.get("tracking")))throw new Fault(409,"SHIPMENT_CONFLICT");}
      else store.db.update("UPDATE shop_seckill_delivery SET status='SHIPPED',carrier=?,tracking=?,shipped_at_ms=? WHERE order_id=?",carrier,tracking,store.now(),id);
      return Map.of("status","SHIPPED");});
  }
  @PostMapping("/api/shop/seckill/{id}/receive")
  public Object seckillReceive(@PathVariable String id,@RequestBody JsonNode b,HttpServletRequest r) {
    long u=user(r);Input.uuid(id);Input.fields(b,"idempotencyKey");Input.uuid(Input.text(b,"idempotencyKey",36,36));
    return store.transaction(()->{if(store.one("SELECT id FROM orders WHERE id=? AND user_id=? FOR UPDATE",id,u)==null)throw new Fault(404,"NOT_FOUND");
      var d=store.one("SELECT status FROM shop_seckill_delivery WHERE order_id=?",id);if(d==null || "READY".equals(d.get("status")))throw new Fault(409,"STATE_CONFLICT");
      store.db.update("UPDATE shop_seckill_delivery SET status='DELIVERED',delivered_at_ms=? WHERE order_id=? AND status='SHIPPED'",store.now(),id);return Map.of("status","DELIVERED");});
  }
  @GetMapping("/api/admin/shop/orders")
  public Object adminOrders(HttpServletRequest r) {admin(r);return Map.of("items",store.db.queryForList("SELECT user_id,id FROM shop_orders ORDER BY created_at_ms DESC LIMIT 100").stream().map(v->detail(Store.number(v,"user_id"),v.get("id").toString())).toList());}
  /** 手工演示发货；订单一旦已发货，重试不得覆盖已登记的单号。 */
  @PostMapping("/api/admin/shop/orders/{id}/ship")
  public Object ship(@PathVariable String id,@RequestBody JsonNode b,HttpServletRequest r) {
    admin(r);Input.uuid(id);Input.fields(b,"carrier","tracking");String carrier=Input.text(b,"carrier",1,60).trim(),tracking=Input.text(b,"tracking",1,100).trim();
    if(carrier.isEmpty() || !tracking.matches("[A-Za-z0-9-]{1,100}"))throw new Fault(400,"INVALID_ARGUMENT");
    return store.transaction(()->{var order=store.one("SELECT * FROM shop_orders WHERE id=? FOR UPDATE",id);if(order==null)throw new Fault(404,"NOT_FOUND");String state=order.get("status").toString();
      PaymentGuard.mayShip(store,"SHOP",id);
      if(state.equals("SHIPPED") || state.equals("DELIVERED")){
        if(!carrier.equals(order.get("carrier")) || !tracking.equals(order.get("tracking")))throw new Fault(409,"SHIPMENT_CONFLICT");
      }else{if(!state.equals("PAID"))throw new Fault(409,"STATE_CONFLICT");store.db.update("UPDATE shop_orders SET status='SHIPPED',carrier=?,tracking=?,shipped_at_ms=? WHERE id=?",carrier,tracking,store.now(),id);}
      return detail(Store.number(order,"user_id"),id);
    });
  }
}
