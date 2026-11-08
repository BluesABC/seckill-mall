package com.seckillmall.order.business;

import java.util.*;
import java.util.concurrent.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import org.springframework.transaction.support.TransactionTemplate;
import com.fasterxml.jackson.databind.ObjectMapper;

/** 显式测试进程：在Python创建的独立MySQL库中验证状态机，不启动HTTP模拟支付网关。 */
public class WechatDatabaseProbe {
  static Store store;static Retail retail;static Orders orders;static WechatPayments engine;static Fake gateway;
  static long user;static final List<String> checks=new ArrayList<>();
  record Fixture(String kind,String id,long sku,Long activity){}
  static void check(boolean condition,String message){if(!condition)throw new AssertionError(message);}
  static void fault(int code,Runnable f){try{f.run();throw new AssertionError("Fault expected");}catch(Fault e){check(e.status==code,"Unexpected fault "+e.code);}}
  static Map<String,Object> wx(Fixture f){return store.one("SELECT * FROM wx_payments WHERE order_kind=? AND order_id=?",f.kind,f.id);}
  static String trade(Fixture f){return wx(f).get("out_trade_no").toString();}
  static String state(Fixture f){return wx(f).get("state").toString();}
  static String local(Fixture f){return store.one("SELECT status FROM "+(f.kind.equals("SHOP")?"shop_orders":"orders")+" WHERE id=?",f.id).get("status").toString();}
  static long stock(Fixture f){return f.kind.equals("SHOP")?store.db.queryForObject("SELECT unallocated_stock FROM skus WHERE id=?",Long.class,f.sku):store.db.queryForObject("SELECT available_stock FROM activity_stock WHERE activity_id=? AND sku_id=?",Long.class,f.activity,f.sku);}
  static Fixture fixture(String kind){
    long now=store.now(),goods=store.insert("INSERT INTO goods(title,description,image_url) VALUES('微信状态机夹具','不对外出售','/assets/shoe-run-v1.webp')");
    long sku=store.insert("INSERT INTO skus(goods_id,price_fen,unallocated_stock,size_eu) VALUES(?,1990,99,'42')",goods);
    String id=UUID.randomUUID().toString();Long activity=null;
    if(kind.equals("SHOP")){
      store.db.update("INSERT INTO shop_orders(id,user_id,retry_key,fingerprint,recipient,phone,address,amount_fen,status,created_at_ms,expires_at_ms) VALUES(?,?,?,'test','测试','13800138000','测试地址',1990,'PENDING_PAYMENT',?,?)",id,user,UUID.randomUUID().toString(),now,now+600000);
      store.db.update("INSERT INTO shop_items VALUES(?,?,'测试鞋','42','/assets/shoe-run-v1.webp',1,1990)",id,sku);
    }else{
      activity=store.insert("INSERT INTO activities(name,starts_at_ms,ends_at_ms,status) VALUES('测试',?,?,'ACTIVE')",now-60000,now+600000);
      store.db.update("INSERT INTO activity_stock VALUES(?,?,10,9,1990,1,0)",activity,sku);
      String rid=UUID.randomUUID().toString();store.db.update("INSERT INTO seckill_requests(reservation_id,request_id,activity_id,sku_id,user_id,epoch,price_fen,status,created_at_ms) VALUES(?,?,?,?,?,1,1990,'ORDER_CREATED',?)",rid,UUID.randomUUID().toString(),activity,sku,user,now);
      store.db.update("INSERT INTO orders(id,reservation_id,activity_id,sku_id,user_id,quantity,amount_fen,status,created_at_ms,expires_at_ms) VALUES(?,?,?,?,?,1,1990,'PENDING_PAYMENT',?,?)",id,rid,activity,sku,user,now,now+600000);
    }
    return new Fixture(kind,id,sku,activity);
  }
  static WechatGateway.Payment success(Fixture f){return new WechatGateway.Payment(trade(f),"wx_"+trade(f),"SUCCESS",1990,"CNY",gateway.mchid(),gateway.appid());}
  static WechatGateway.Refund refundSuccess(Fixture f){var row=wx(f);return new WechatGateway.Refund(trade(f),row.get("transaction_id").toString(),row.get("out_refund_no").toString(),"rf_"+trade(f),"SUCCESS",1990,1990,"CNY");}
  static void parallel(Runnable action)throws Exception{var pool=Executors.newFixedThreadPool(4);try{var list=new ArrayList<Future<?>>();for(int i=0;i<4;i++)list.add(pool.submit(action));for(var future:list)future.get();}finally{pool.shutdownNow();}}
  static class Fake implements WechatGateway {
    final Map<String,Payment> trades=new ConcurrentHashMap<>();final Map<String,Refund> refunds=new ConcurrentHashMap<>();
    boolean prepayUnknown,closeUnknown;java.util.function.Consumer<String> onPrepay;
    public boolean enabled(){return true;}public String mchid(){return "1900000001";}public String appid(){return "wx1234567890123456";}
    public String prepay(String n,long a,long e){trades.putIfAbsent(n,new Payment(n,"","NOTPAY",a,"CNY",mchid(),appid()));if(onPrepay!=null)onPrepay.accept(n);if(prepayUnknown)throw new IllegalStateException("simulated timeout");return "weixin://wxpay/bizpayurl?pr="+n;}
    public Payment query(String n){return Objects.requireNonNull(trades.get(n));}
    public void close(String n){if(closeUnknown)throw new IllegalStateException("simulated timeout");if(query(n).state().equals("SUCCESS"))throw new IllegalStateException("paid");trades.put(n,new Payment(n,"","CLOSED",1990,"CNY",mchid(),appid()));}
    public Refund refund(String n,String number,long a){return refunds.computeIfAbsent(number,k->new Refund(n,"wx_"+n,k,"rf_"+n,"PROCESSING",a,a,"CNY"));}
    public Refund queryRefund(String n){return Objects.requireNonNull(refunds.get(n));}
    public Payment paymentNotification(Map<String,String> h,String b){throw new UnsupportedOperationException("No test HTTP callbacks");}
    public Refund refundNotification(Map<String,String> h,String b){throw new UnsupportedOperationException("No test HTTP callbacks");}
  }
  public static void main(String[] args)throws Exception{
    String db=System.getenv("T060_DB_NAME");if(db==null||!db.matches("mall_wx_[a-f0-9]{32}"))throw new IllegalStateException("Owned test database required");
    var ds=new DriverManagerDataSource("jdbc:mysql://127.0.0.1:13306/"+db+"?useSSL=false&allowPublicKeyRetrieval=true&characterEncoding=UTF-8",System.getenv("MALL_DB_USER"),System.getenv("MALL_DB_PASSWORD"));
    store=new Store(new JdbcTemplate(ds),new TransactionTemplate(new DataSourceTransactionManager(ds)));retail=new Retail(store,null,900000);orders=new Orders(store,null,900000);orders.retail(retail);gateway=new Fake();engine=new WechatPayments(store,orders,retail,gateway,false);
    user=store.insert("INSERT INTO users(username,password_hash,created_at_ms) VALUES('probe','not-a-login-hash',?)",store.now());
    var f=fixture("SHOP");var prepay=engine.nativePay(user,f.kind,f.id);check(prepay.get("qrImage")!=null,"Native QR missing");java.nio.file.Files.writeString(java.nio.file.Path.of("build/wsl/t060-test-qr.txt"),prepay.get("qrImage").toString());check(state(f).equals("PREPAY"),"prepay not persisted");fault(404,()->engine.query(user+1,f.kind,f.id));fault(409,()->PaymentGuard.mockPay(store,f.kind,f.id));fault(409,()->PaymentGuard.noIntent(store,f.kind,f.id));checks.add("native intent/ownership/MOCK bypass guard");
    store.db.update("UPDATE shop_orders SET expires_at_ms=1 WHERE id=?",f.id);retail.expireAll();check(local(f).equals("PENDING_PAYMENT")&&stock(f)==99,"Unconfirmed remote order released inventory");checks.add("expiry waits for channel closure");
    var valid=success(f);fault(409,()->engine.paid(new WechatGateway.Payment(valid.tradeNo(),valid.transactionId(),"SUCCESS",1,"CNY",valid.mchid(),valid.appid())));
    fault(409,()->engine.paid(new WechatGateway.Payment(valid.tradeNo(),valid.transactionId(),"SUCCESS",1990,"USD",valid.mchid(),valid.appid())));
    fault(409,()->engine.paid(new WechatGateway.Payment(valid.tradeNo(),valid.transactionId(),"SUCCESS",1990,"CNY","other",valid.appid())));check(local(f).equals("PENDING_PAYMENT"),"Mismatch credited");checks.add("amount/currency/merchant validation");
    parallel(()->engine.paid(valid));check(local(f).equals("PAID")&&state(f).equals("SUCCESS")&&stock(f)==99,"Duplicate success changed inventory");check(store.db.queryForObject("SELECT COUNT(*) FROM shop_orders WHERE id=? AND provider='WECHAT' AND payment_id IS NOT NULL",Integer.class,f.id)==1,"payment missing");checks.add("parallel duplicate success idempotency");
    engine.refund(user,f.kind,f.id);check(state(f).equals("REFUNDING")&&stock(f)==99,"Refund accepted incorrectly released stock");fault(409,()->PaymentGuard.mayShip(store,f.kind,f.id));parallel(()->engine.refunded(refundSuccess(f)));check(state(f).equals("REFUNDED")&&local(f).equals("REFUNDED")&&stock(f)==100,"Full refund not applied exactly once");checks.add("processing refund and repeated refund notifications");
    var lost=fixture("SHOP");engine.nativePay(user,lost.kind,lost.id);gateway.trades.put(trade(lost),success(lost));store.db.update("UPDATE wx_payments SET next_check_at_ms=0 WHERE order_id=?",lost.id);engine.query(user,lost.kind,lost.id);check(local(lost).equals("PAID"),"Active query failed to recover lost notification");checks.add("active query recovers lost callback");
    var closed=fixture("SHOP");engine.nativePay(user,closed.kind,closed.id);gateway.closeUnknown=true;fault(503,()->engine.cancel(user,closed.kind,closed.id));check(local(closed).equals("PENDING_PAYMENT")&&stock(closed)==99,"Close timeout released inventory");gateway.closeUnknown=false;engine.cancel(user,closed.kind,closed.id);engine.cancel(user,closed.kind,closed.id);check(local(closed).equals("CLOSED")&&stock(closed)==100,"Close not idempotent");checks.add("close unknown and confirmed closure");
    engine.paid(success(closed));check(state(closed).equals("REFUNDING")&&local(closed).equals("CLOSED")&&stock(closed)==100,"Late payment revived a closed order");engine.reconcile();engine.refunded(refundSuccess(closed));check(local(closed).equals("CLOSED")&&stock(closed)==100&&state(closed).equals("REFUNDED"),"Late refund duplicated inventory");checks.add("late payment persists compensation without reviving stock");
    var unknown=fixture("SHOP");gateway.prepayUnknown=true;fault(503,()->engine.nativePay(user,unknown.kind,unknown.id));gateway.prepayUnknown=false;check(state(unknown).equals("CREATING")&&!PaymentGuard.mayClose(store,unknown.kind,unknown.id),"Unknown prepay forgotten");store.db.update("UPDATE wx_payments SET next_check_at_ms=? WHERE order_id=?",store.now()+60000,unknown.id);check(engine.nativePay(user,unknown.kind,unknown.id).containsKey("qrImage"),"Query lease blocked native QR recovery");engine.cancel(user,unknown.kind,unknown.id);check(stock(unknown)==100,"Unknown prepay not recovered");checks.add("unknown prepay stays durably tracked");
    var sec=fixture("SECKILL");engine.nativePay(user,sec.kind,sec.id);parallel(()->engine.paid(success(sec)));check(local(sec).equals("PAID")&&stock(sec)==9,"Seckill payment stock mismatch");check(store.db.queryForObject("SELECT COUNT(*) FROM payments WHERE order_id=? AND provider='WECHAT'",Integer.class,sec.id)==1,"Seckill duplicate payment");
    check(store.db.queryForObject("SELECT COUNT(*) FROM outbox_events WHERE reservation_id=(SELECT reservation_id FROM orders WHERE id=?) AND kind='ORDER_PAID'",Integer.class,sec.id)==1,"Seckill outbox missing");engine.refund(user,sec.kind,sec.id);parallel(()->engine.refunded(refundSuccess(sec)));check(local(sec).equals("PAID")&&stock(sec)==9,"Seckill financial refund changed qualification/stock");fault(409,()->PaymentGuard.mayShip(store,sec.kind,sec.id));checks.add("seckill payment/outbox/refund invariants");
    var early=fixture("SHOP");gateway.onPrepay=n->{if(n.equals(trade(early)))engine.paid(success(early));};var response=engine.nativePay(user,early.kind,early.id);gateway.onPrepay=null;check(response.get("state").equals("SUCCESS")&&!response.containsKey("qrImage"),"Prepay response downgraded earlier callback");checks.add("callback before prepay response");
    var review=fixture("SHOP");engine.nativePay(user,review.kind,review.id);engine.paid(success(review));engine.refund(user,review.kind,review.id);
    var rf=refundSuccess(review);engine.refunded(new WechatGateway.Refund(rf.tradeNo(),rf.transactionId(),rf.refundNo(),rf.refundId(),"ABNORMAL",1990,1990,"CNY"));check(state(review).equals("REVIEW")&&stock(review)==99,"Abnormal refund released stock");
    gateway.refunds.put(rf.refundNo(),rf);engine.adminRecheck(review.kind,review.id);check(state(review).equals("REFUNDED")&&stock(review)==100,"Admin channel recheck failed");checks.add("abnormal refund holds stock until verified admin recheck");
    var demo=fixture("SHOP");store.db.update("UPDATE shop_orders SET status='PAID' WHERE id=?",demo.id);fault(409,()->PaymentGuard.mayShip(store,demo.kind,demo.id));checks.add("WECHAT mode refuses legacy MOCK fulfillment without channel proof");
    engine.close();System.out.println(new ObjectMapper().writeValueAsString(Map.of("passed",true,"scope","owned real MySQL, in-process fake channel; not WeChat merchant integration","checks",checks)));
  }
}
