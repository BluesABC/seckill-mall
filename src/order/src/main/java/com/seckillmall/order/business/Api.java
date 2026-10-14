package com.seckillmall.order.business;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.servlet.http.HttpServletRequest;
import java.util.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.*;

@RestController
@ConditionalOnProperty(name = "mall.business-enabled", havingValue = "true")
public class Api {
  private final Store store;
  private final Sessions sessions;
  private final Catalog catalog;
  private final Orders orders;
  private final Workers workers;
  public Api(Store s, Sessions a, Catalog c, Orders o, Workers w) {
    store = s;
    sessions = a;
    catalog = c;
    orders = o;
    workers = w;
  }
  private Sessions.Identity identity(HttpServletRequest r) {
    return sessions.auth(r.getHeader("Authorization"));
  }
  private void admin(HttpServletRequest r) {
    identity(r).admin();
  }
  @PostMapping("/api/auth/register")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  public Object register(@RequestBody JsonNode b, HttpServletRequest r) {
    return sessions.register(b, r.getRemoteAddr());
  }
  @PostMapping("/api/auth/login")
  public Object login(@RequestBody JsonNode b, HttpServletRequest r) {
    return sessions.login(b, r.getRemoteAddr());
  }
  @PostMapping("/api/auth/logout")
  public Object logout(HttpServletRequest r) {
    identity(r);
    sessions.logout(r.getHeader("Authorization"));
    return Map.of("status", "LOGGED_OUT");
  }
  @GetMapping("/api/auth/me")
  public Object me(HttpServletRequest r) {
    var i = identity(r);
    return Map.of("userId", Long.toString(i.userId()), "role", i.role());
  }
  @GetMapping("/api/goods")
  public Object goods() {
    return Map.of("items", catalog.products());
  }
  @GetMapping("/api/goods/catalog")
  public Object goodsPage(@RequestParam Map<String, String> p) {
    if (!Set.of("q", "category", "maxPriceFen", "sort", "page", "size")
            .containsAll(p.keySet())) {
      throw new Fault(400, "INVALID_ARGUMENT");
    }
    return catalog.productPage(p.getOrDefault("q", ""), p.getOrDefault("category", ""),
        p.get("maxPriceFen"), p.getOrDefault("sort", "featured"), p.get("page"), p.get("size"));
  }
  @GetMapping("/api/goods/{id}")
  public Object good(@PathVariable String id) {
    return catalog.product(Input.id(id));
  }
  @GetMapping("/api/activities")
  public Object activities() {
    return Map.of("items", catalog.activities());
  }
  @GetMapping("/api/orders")
  public Object orders(HttpServletRequest r) {
    return Map.of("items", orders.list(identity(r).userId()));
  }
  @GetMapping("/api/order/status")
  public Object status(@RequestParam Map<String, String> p, HttpServletRequest r) {
    if (!Set.of("orderId", "activityId", "skuId", "requestId").containsAll(p.keySet()))
      throw new Fault(400, "INVALID_ARGUMENT");
    return orders.query(identity(r).userId(), p.get("orderId"),
        p.containsKey("activityId") ? Input.id(p.get("activityId")) : null,
        p.containsKey("skuId") ? Input.id(p.get("skuId")) : null, p.get("requestId"));
  }
  @PostMapping("/api/order/pay")
  public Object pay(@RequestBody JsonNode b, HttpServletRequest r) {
    return orders.pay(identity(r).userId(), b);
  }
  @GetMapping("/api/admin/users")
  public Object users(HttpServletRequest r) {
    admin(r);
    return Map.of("items",
        store.db
            .queryForList("SELECT id AS userId,username,role,enabled,created_at_ms AS createdAtMs "
                          + "FROM users ORDER BY id LIMIT 100")
            .stream()
            .map(Store::wire)
            .toList());
  }
  @PatchMapping("/api/admin/users/{id}")
  public Object user(@PathVariable String id, @RequestBody JsonNode b, HttpServletRequest r) {
    Input.fields(b, "enabled");
    if (!b.get("enabled").isBoolean())
      throw new Fault(400, "INVALID_ARGUMENT");
    sessions.enable(identity(r), Input.id(id), b.get("enabled").booleanValue());
    return Map.of("status", "UPDATED");
  }
  @PostMapping("/api/admin/goods")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  public Object createGoods(@RequestBody JsonNode b, HttpServletRequest r) {
    admin(r);
    return catalog.createProduct(b);
  }
  @PostMapping("/api/admin/goods/{id}/skus")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  public Object createSku(@PathVariable String id, @RequestBody JsonNode b,
      HttpServletRequest r) {
    admin(r);
    return catalog.createSku(Input.id(id), b);
  }
  @GetMapping("/api/admin/goods")
  public Object adminGoods(HttpServletRequest r) {
    admin(r);
    return Map.of("items", store.db.queryForList(
        "SELECT g.id AS goodsId,g.title,g.description,g.image_url AS imageUrl,g.enabled,"
        + "s.id AS skuId,s.size_eu AS sizeEu,s.category,s.colorway,s.price_fen AS priceFen,s.unallocated_stock AS unallocatedStock "
        + "FROM goods g JOIN skus s ON s.goods_id=g.id ORDER BY g.id DESC,s.id ASC LIMIT 100")
        .stream().map(Store::wire).toList());
  }
  @PatchMapping("/api/admin/skus/{id}")
  public Object skuAttributes(@PathVariable String id,@RequestBody JsonNode b,HttpServletRequest r){
    admin(r);Input.fields(b,"sizeEu","category","colorway");
    String size=Input.text(b,"sizeEu",0,8),category=Input.text(b,"category",0,16),color=Input.text(b,"colorway",0,64);
    if(!size.isEmpty()&&!size.matches("(?:3[5-9]|4[0-9]|50)(?:\\.5)?"))throw new Fault(400,"INVALID_ARGUMENT");
    if(!Set.of("","跑步","篮球","休闲","训练").contains(category))throw new Fault(400,"INVALID_ARGUMENT");
    long sku=Input.id(id);
    store.transaction(()->{
      var existing=store.one("SELECT goods_id FROM skus WHERE id=? FOR UPDATE",sku);
      if(existing==null)throw new Fault(404,"NOT_FOUND");
      long goodsId=Store.number(existing,"goods_id");
      store.one("SELECT id FROM goods WHERE id=? FOR UPDATE",goodsId);
      if(store.db.queryForObject("SELECT COUNT(*) FROM activity_stock WHERE sku_id=?",Long.class,sku)>0)throw new Fault(409,"SKU_IN_USE");
      if(!size.isEmpty()&&store.db.queryForObject("SELECT COUNT(*) FROM skus WHERE goods_id=? AND size_eu=? AND id<>?",Long.class,goodsId,size,sku)>0)throw new Fault(409,"SKU_SIZE_EXISTS");
      store.db.update("UPDATE skus SET size_eu=?,category=?,colorway=? WHERE id=?",size,category,color,sku);return null;
    });
    return Map.of("status","UPDATED");
  }
  @PatchMapping("/api/admin/goods/{id}")
  public Object updateGoods(
      @PathVariable String id, @RequestBody JsonNode b, HttpServletRequest r) {
    admin(r);
    catalog.updateProduct(Input.id(id), b);
    return Map.of("status", "UPDATED");
  }
  @PostMapping("/api/admin/activities")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  public Object activity(@RequestBody JsonNode b, HttpServletRequest r) {
    admin(r);
    return catalog.createActivity(b);
  }
  @PostMapping("/api/admin/activities/{id}/activate")
  public Object activate(@PathVariable String id, @RequestBody JsonNode b, HttpServletRequest r) {
    admin(r);
    Input.fields(b, "skuId");
    catalog.activate(Input.id(id), Input.id(b, "skuId"));
    return Map.of("status", "ACTIVE");
  }
  @PostMapping("/api/admin/activities/{id}/end")
  public Object end(@PathVariable String id, @RequestBody JsonNode b, HttpServletRequest r) {
    admin(r);
    Input.fields(b, "skuId");
    catalog.end(Input.id(id), Input.id(b, "skuId"));
    return Map.of("status", "ENDED");
  }
  @GetMapping("/api/admin/orders")
  public Object adminOrders(HttpServletRequest r) {
    admin(r);
    return Map.of("items",
        store.db
            .queryForList("SELECT id AS orderId,user_id AS userId,status AS orderState,amount_fen "
                          + "AS amountFen,created_at_ms AS createdAtMs FROM orders ORDER BY "
                          + "created_at_ms DESC LIMIT 100")
            .stream()
            .map(Store::wire)
            .toList());
  }
  @GetMapping("/api/admin/recovery")
  public Object recovery(HttpServletRequest r) {
    admin(r);
    return Map.of("items",
        store.db
            .queryForList("SELECT message_hash AS messageHash,status,attempts,reason,updated_at_ms "
                          + "AS updatedAtMs FROM mq_failures ORDER BY updated_at_ms DESC LIMIT 100")
            .stream()
            .map(Store::wire)
            .toList(),
        "metrics", workers.metrics());
  }
  @PostMapping("/api/admin/recovery/{hash}/replay")
  public Object replay(@PathVariable String hash, HttpServletRequest r) {
    admin(r);
    return workers.replay(hash);
  }
  @PostMapping("/api/admin/recovery/run")
  public Object run(HttpServletRequest r) {
    admin(r);
    workers.tick();
    return workers.metrics();
  }
}
