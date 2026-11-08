package com.seckillmall.order.business;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.servlet.http.HttpServletRequest;
import java.time.Duration;
import java.util.Map;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.*;

/** 秒杀收货信息前置：先提交不可变SQL快照，再发无个人信息的Redis入场标记。 */
@RestController
@ConditionalOnProperty(name="mall.business-enabled",havingValue="true")
public class SeckillCheckout {
  private final Store store; private final Cache cache; private final Sessions sessions;
  public SeckillCheckout(Store store,Cache cache,Sessions sessions){this.store=store;this.cache=cache;this.sessions=sessions;}

  @PostMapping("/api/shop/seckill/checkout")
  public Object prepare(@RequestBody JsonNode b,HttpServletRequest r){
    long user=sessions.auth(r.getHeader("Authorization")).userId();
    Input.fields(b,"activityId","skuId","requestId","addressId");
    long activity=Input.id(b,"activityId"),sku=Input.id(b,"skuId"),aid=Input.id(b,"addressId");
    String request=Input.uuid(Input.text(b,"requestId",36,36));
    store.transaction(()->{
      store.one("SELECT id FROM users WHERE id=? FOR UPDATE",user);
      var prior=store.one("SELECT address_id FROM seckill_checkouts WHERE user_id=? AND activity_id=? AND sku_id=? AND request_id=?",user,activity,sku,request);
      if(prior!=null){if(Store.number(prior,"address_id")!=aid)throw new Fault(409,"CHECKOUT_CONFLICT");return null;}
      var address=store.one("SELECT recipient,phone,address FROM shop_addresses WHERE id=? AND user_id=?",aid,user);
      if(address==null)throw new Fault(404,"ADDRESS_NOT_FOUND");
      if(address.get("recipient").toString().isBlank()||address.get("phone").toString().trim().length()<5||address.get("address").toString().trim().length()<5)throw new Fault(409,"ADDRESS_REQUIRED");
      if(store.one("SELECT activity_id FROM activity_stock WHERE activity_id=? AND sku_id=?",activity,sku)==null)throw new Fault(404,"UNKNOWN_ACTIVITY");
      store.db.update("INSERT INTO seckill_checkouts(user_id,activity_id,sku_id,request_id,address_id,recipient,phone,address,created_at_ms) VALUES(?,?,?,?,?,?,?,?,?)",user,activity,sku,request,aid,address.get("recipient"),address.get("phone"),address.get("address"),store.now());
      return null;
    });
    // 在SQL提交后发布标记。Redis失败可用同一请求重试；消费者只相信SQL快照。
    cache.redis.opsForValue().set(cache.ledger(activity,sku)+":shipping:"+user+":"+request,"1",Duration.ofHours(24));
    return Map.of("requestId",request,"status","READY");
  }
}
