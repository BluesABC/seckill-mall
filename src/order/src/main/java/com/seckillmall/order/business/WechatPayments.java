package com.seckillmall.order.business;

import java.util.*;
import java.util.concurrent.*;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import javax.imageio.ImageIO;
import com.google.zxing.*;
import com.google.zxing.qrcode.QRCodeWriter;

/**
 * 微信支付意图状态机。先提交本地意图，再调用渠道；外部RPC绝不放在DB事务里。
 * 回调和主动查单复用同一落账函数；关单确认前禁止释放库存，退款确认前禁止发货。
 */
public final class WechatPayments implements AutoCloseable {
  private final Store store;private final Orders orders;private final Retail retail;private final WechatGateway gateway;
  private final boolean jobs;
  private final ScheduledExecutorService worker=Executors.newSingleThreadScheduledExecutor(r->{Thread t=new Thread(r,"wechat-reconcile");t.setDaemon(true);return t;});
  public WechatPayments(Store s,Orders o,Retail retail,WechatGateway gateway,boolean jobs){store=s;orders=o;this.retail=retail;this.gateway=gateway;this.jobs=jobs;}
  public boolean enabled(){return gateway.enabled();}
  public void start(){if(jobs&&enabled())worker.scheduleWithFixedDelay(()->{try{reconcile();}catch(RuntimeException e){System.err.println("wechat-reconcile error="+e.getClass().getSimpleName());}},5,5,TimeUnit.SECONDS);}
  public void close(){worker.shutdownNow();}
  private void configured(){if(!enabled())throw new Fault(503,"WECHAT_NOT_CONFIGURED");}
  private void kind(String kind){if(!Set.of("SHOP","SECKILL").contains(kind))throw new Fault(400,"INVALID_ARGUMENT");}
  private String table(String kind){kind(kind);return kind.equals("SHOP")?"shop_orders":"orders";}
  private Map<String,Object> order(String kind,String id,boolean lock){
    String table=table(kind);Input.uuid(id);
    if(lock&&kind.equals("SECKILL")){var seed=store.one("SELECT activity_id,sku_id FROM orders WHERE id=?",id);if(seed!=null)store.one("SELECT sku_id FROM activity_stock WHERE activity_id=? AND sku_id=? FOR UPDATE",seed.get("activity_id"),seed.get("sku_id"));}
    return store.one("SELECT * FROM "+table+" WHERE id=?"+(lock?" FOR UPDATE":""),id);
  }
  private void own(long u,String kind,String id){var o=order(kind,id,false);if(o==null||Store.number(o,"user_id")!=u)throw new Fault(404,"NOT_FOUND");}
  private Map<String,Object> intent(String kind,String id){return store.one("SELECT * FROM wx_payments WHERE order_kind=? AND order_id=?",kind,id);}
  private Map<String,Object> byTrade(String number){var p=store.one("SELECT * FROM wx_payments WHERE out_trade_no=?",number);if(p==null)throw new Fault(404,"PAYMENT_NOT_FOUND");return p;}
  private String text(Map<String,Object> row,String key){return Objects.toString(row.get(key),"");}
  /** 统一二维码只对本人提供，且只在渠道预下单成功、未过期时展示。 */
  public Map<String,Object> view(long u,String kind,String id){own(u,kind,id);var p=intent(kind,id);if(p==null)return Map.of("state","NOT_STARTED","provider","WECHAT","configured",enabled());return view(p);}
  private Map<String,Object> view(Map<String,Object> p){
    var result=new LinkedHashMap<String,Object>();
    for(String key:List.of("order_kind","order_id","state","amount_fen","expires_at_ms","transaction_id","refund_id","last_error"))result.put(key,p.get(key));
    result.put("provider","WECHAT");result.put("configured",enabled());
    if("PREPAY".equals(p.get("state"))&&Store.number(p,"expires_at_ms")>store.now()&&!text(p,"code_url").isEmpty())result.put("qrImage",qr(text(p,"code_url")));
    return Store.wire(result);
  }
  static String qr(String code){
    if(!code.startsWith("weixin://wxpay/bizpayurl?")||code.length()>2048)throw new Fault(502,"INVALID_WECHAT_CODE_URL");
    return encodeQr(code);
  }
  /** 通用二维码编码；模拟收银只编码明确的演示文字，不生成微信收款链接。 */
  static String encodeQr(String code){
    try{var matrix=new QRCodeWriter().encode(code,BarcodeFormat.QR_CODE,280,280,Map.of(EncodeHintType.CHARACTER_SET,"UTF-8"));var image=new BufferedImage(280,280,BufferedImage.TYPE_INT_RGB);
      for(int x=0;x<280;x++)for(int y=0;y<280;y++)image.setRGB(x,y,matrix.get(x,y)?0:0xffffff);
      var out=new ByteArrayOutputStream();ImageIO.write(image,"png",out);return "data:image/png;base64,"+Base64.getEncoder().encodeToString(out.toByteArray());
    }catch(Exception e){throw new Fault(502,"QR_GENERATION_FAILED");}
  }
  public Map<String,Object> nativePay(long u,String kind,String id){
    configured();own(u,kind,id);
    var p=store.transaction(()->{
      var o=order(kind,id,true);var existing=intent(kind,id);if(existing!=null)return existing;
      if(!"PENDING_PAYMENT".equals(o.get("status"))||Store.number(o,"expires_at_ms")<=store.now())throw new Fault(409,"ORDER_CLOSED");
      long amount=Store.number(o,"amount_fen");if(amount>Integer.MAX_VALUE)throw new Fault(400,"AMOUNT_OUT_OF_RANGE");
      String local=UUID.randomUUID().toString(),number=local.replace("-","");
      store.db.update("INSERT INTO wx_payments(id,order_kind,order_id,user_id,amount_fen,mchid,appid,out_trade_no,state,expires_at_ms,created_at_ms) VALUES(?,?,?,?,?,?,?,?,'CREATING',?,?)",local,kind,id,u,amount,gateway.mchid(),gateway.appid(),number,o.get("expires_at_ms"),store.now());return intent(kind,id);
    });
    if(!Set.of("CREATING","PREPAY").contains(text(p,"state"))||Store.number(p,"expires_at_ms")<=store.now())return view(p);
    if(!text(p,"code_url").isEmpty())return view(p);
    long lease=store.now()+15000;
    if(store.db.update("UPDATE wx_payments SET prepay_lease_until_ms=? WHERE id=? AND prepay_lease_until_ms<=? AND state IN ('CREATING','PREPAY')",lease,p.get("id"),store.now())==0)return view(p);
    try{
      String code=gateway.prepay(text(p,"out_trade_no"),Store.number(p,"amount_fen"),Store.number(p,"expires_at_ms"));qr(code);
      store.db.update("UPDATE wx_payments SET code_url=?,state='PREPAY',last_error=NULL WHERE id=? AND state IN ('CREATING','PREPAY')",code,p.get("id"));
    }catch(RuntimeException e){error(p,e);throw new Fault(503,"WECHAT_RESULT_UNKNOWN");}
    finally{store.db.update("UPDATE wx_payments SET prepay_lease_until_ms=0 WHERE id=? AND prepay_lease_until_ms=?",p.get("id"),lease);}
    return view(intent(kind,id));
  }
  private void error(Map<String,Object> p,RuntimeException e){
    String code=e instanceof Fault f?f.code:"CHANNEL_UNAVAILABLE";
    if(e instanceof com.wechat.pay.java.core.exception.ServiceException service && service.getErrorCode()!=null && service.getErrorCode().matches("[A-Z0-9_]{1,64}"))code=service.getErrorCode();
    store.db.update("UPDATE wx_payments SET last_error=? WHERE id=?",code,p.get("id"));
  }
  /** 网关成功交易必须匹配商户、AppID、币种和服务端金额，不能相信扫码页跳转。 */
  public void paid(WechatGateway.Payment payment){
    if(!"SUCCESS".equals(payment.state()))throw new Fault(400,"NOT_SUCCESS_NOTIFICATION");
    var p=byTrade(payment.tradeNo());
    if(payment.total()!=Store.number(p,"amount_fen")||!"CNY".equals(payment.currency())||!text(p,"mchid").equals(payment.mchid())||!text(p,"appid").equals(payment.appid())||!gateway.mchid().equals(payment.mchid())||!gateway.appid().equals(payment.appid())||payment.transactionId()==null||payment.transactionId().isBlank())throw new Fault(409,"WECHAT_PAYMENT_MISMATCH");
    store.transaction(()->{
      String kind=text(p,"order_kind"),id=text(p,"order_id");var o=order(kind,id,true);var current=store.one("SELECT * FROM wx_payments WHERE id=? FOR UPDATE",p.get("id"));
      if(!text(current,"transaction_id").isEmpty()&&!text(current,"transaction_id").equals(payment.transactionId()))throw new Fault(409,"WECHAT_TRANSACTION_CONFLICT");
      store.db.update("UPDATE wx_payments SET transaction_id=?,last_error=NULL WHERE id=?",payment.transactionId(),p.get("id"));
      if(Set.of("REFUNDING","REFUNDED","REVIEW").contains(text(current,"state")))return null;
      if("CLOSED".equals(o.get("status"))){
        // 异常迟到真实收款：不复活已释放库存订单，先持久登记原路退款意图再应答回调。
        refundIntent(current);return null;
      }
      if("PENDING_PAYMENT".equals(o.get("status"))){
        if(kind.equals("SHOP"))store.db.update("UPDATE shop_orders SET status='PAID',provider='WECHAT',payment_id=?,paid_at_ms=? WHERE id=?",p.get("id"),store.now(),id);
        else{
          store.db.update("UPDATE orders SET status='PAID',version=version+1 WHERE id=?",id);
          store.db.update("INSERT INTO payments(id,order_id,idempotency_key,amount_fen,status,provider,provider_transaction_id,created_at_ms) VALUES(?,?,?,?,'SUCCEEDED','WECHAT',?,?)",p.get("id"),id,p.get("id"),p.get("amount_fen"),payment.transactionId(),store.now());
          orders.paidOutbox(text(o,"reservation_id"));
        }
      }
      store.db.update("UPDATE wx_payments SET state='SUCCESS' WHERE id=?",p.get("id"));return null;
    });
  }
  private void closeLocal(String kind,String id){if(kind.equals("SHOP"))retail.closeWechat(id);else orders.closeWechat(id);}
  /** 渠道确认关闭才能关本地单；支付中、超时/网络失败不会假装关单成功。 */
  private void closeConfirmed(Map<String,Object> p){
    store.transaction(()->{String kind=text(p,"order_kind"),id=text(p,"order_id");order(kind,id,true);
      store.db.update("UPDATE wx_payments SET state='CLOSED',code_url=NULL,last_error=NULL WHERE id=? AND state IN ('CREATING','PREPAY')",p.get("id"));
      if(PaymentGuard.mayClose(store,kind,id))closeLocal(kind,id);return null;});
  }
  private void syncPayment(Map<String,Object> p,boolean cancel){
    WechatGateway.Payment tx=gateway.query(text(p,"out_trade_no"));
    if(!text(p,"out_trade_no").equals(tx.tradeNo()))throw new Fault(409,"WECHAT_TRADE_MISMATCH");
    if(!text(p,"mchid").equals(tx.mchid())||!text(p,"appid").equals(tx.appid()))throw new Fault(409,"WECHAT_MERCHANT_MISMATCH");
    switch(tx.state()){
      case "SUCCESS" -> paid(tx);
      case "CLOSED" -> closeConfirmed(p);
      case "NOTPAY","USERPAYING" -> {if(cancel||Store.number(p,"expires_at_ms")<=store.now()){gateway.close(tx.tradeNo());closeConfirmed(p);}}
      case "REFUND" -> store.db.update("UPDATE wx_payments SET state='REVIEW',last_error='EXTERNAL_REFUND_REVIEW' WHERE id=? AND state='SUCCESS'",p.get("id"));
      default -> throw new Fault(503,"WECHAT_RECONCILING");
    }
  }
  public Map<String,Object> query(long u,String kind,String id){
    own(u,kind,id);var p=intent(kind,id);if(p==null)return view(u,kind,id);
    if(enabled()&&!Set.of("CLOSED","REFUNDED","REVIEW").contains(text(p,"state"))&&store.db.update("UPDATE wx_payments SET next_check_at_ms=? WHERE id=? AND next_check_at_ms<=?",store.now()+5000,p.get("id"),store.now())==1){
      try{if("REFUNDING".equals(p.get("state")))syncRefund(p);else syncPayment(p,false);}catch(RuntimeException e){error(p,e);}
    }
    return view(intent(kind,id));
  }
  public Map<String,Object> cancel(long u,String kind,String id){configured();own(u,kind,id);var p=intent(kind,id);if(p==null)throw new Fault(409,"NO_WECHAT_INTENT");
    if(Set.of("SUCCESS","REFUNDING","REFUNDED","REVIEW").contains(text(p,"state")))throw new Fault(409,"PAYMENT_ALREADY_SETTLED");
    if("CLOSED".equals(p.get("state")))closeLocal(kind,id);
    else try{syncPayment(p,true);}catch(RuntimeException e){error(p,e);throw new Fault(503,"WECHAT_CLOSE_UNKNOWN");}
    return view(intent(kind,id));
  }
  private void refundIntent(Map<String,Object> p){
    String key=text(p,"refund_key");if(key.isEmpty())key=UUID.randomUUID().toString();
    store.db.update("UPDATE wx_payments SET state='REFUNDING',refund_key=?,out_refund_no=?,code_url=NULL,next_check_at_ms=0 WHERE id=?",key,key.replace("-",""),p.get("id"));
  }
  public Map<String,Object> refund(long u,String kind,String id){
    configured();own(u,kind,id);
    var p=store.transaction(()->{
      var o=order(kind,id,true);var i=intent(kind,id);if(i==null)throw new Fault(409,"NO_WECHAT_PAYMENT");
      if(Set.of("REFUNDING","REFUNDED").contains(text(i,"state")))return i;
      if(!"SUCCESS".equals(i.get("state"))||!"PAID".equals(o.get("status")))throw new Fault(409,"REFUND_NOT_ALLOWED");
      if(kind.equals("SECKILL")){var d=store.one("SELECT status FROM shop_seckill_delivery WHERE order_id=?",id);if(d!=null&&!"READY".equals(d.get("status")))throw new Fault(409,"REFUND_NOT_ALLOWED");}
      refundIntent(i);return intent(kind,id);
    });
    if(!"REFUNDED".equals(p.get("state")))try{refunded(gateway.refund(text(p,"out_trade_no"),text(p,"out_refund_no"),Store.number(p,"amount_fen")));}catch(RuntimeException e){error(p,e);throw new Fault(503,"WECHAT_REFUND_UNKNOWN");}
    return view(intent(kind,id));
  }
  private void syncRefund(Map<String,Object> p){
    WechatGateway.Refund r;
    try{r=gateway.queryRefund(text(p,"out_refund_no"));}catch(RuntimeException e){r=gateway.refund(text(p,"out_trade_no"),text(p,"out_refund_no"),Store.number(p,"amount_fen"));}
    refunded(r);
  }
  /** PROCESSING只代表受理，只有渠道SUCCESS才完成本地退款和未发货普通库存恢复。 */
  public void refunded(WechatGateway.Refund r){
    var p=byTrade(r.tradeNo());
    if(!text(p,"out_refund_no").equals(r.refundNo())||!text(p,"transaction_id").equals(r.transactionId())||r.total()!=Store.number(p,"amount_fen")||r.amount()!=Store.number(p,"amount_fen")||!"CNY".equals(r.currency())||!gateway.mchid().equals(p.get("mchid"))||!gateway.appid().equals(p.get("appid")))throw new Fault(409,"WECHAT_REFUND_MISMATCH");
    if("SUCCESS".equals(r.state())&&(r.refundId()==null||r.refundId().isBlank()||r.refundId().length()>64))throw new Fault(409,"WECHAT_REFUND_ID_MISSING");
    if(!Set.of("SUCCESS","PROCESSING","CLOSED","ABNORMAL").contains(r.state()))throw new Fault(400,"INVALID_REFUND_STATE");
    store.transaction(()->{
      String kind=text(p,"order_kind"),id=text(p,"order_id");var o=order(kind,id,true);var current=store.one("SELECT state FROM wx_payments WHERE id=? FOR UPDATE",p.get("id"));
      if("REFUNDED".equals(current.get("state")))return null;
      if(!Set.of("REFUNDING","REVIEW").contains(text(current,"state")))throw new Fault(409,"REFUND_NOT_REQUESTED");
      if(r.state().equals("PROCESSING"))return null;
      if(!r.state().equals("SUCCESS")){store.db.update("UPDATE wx_payments SET state='REVIEW',last_error='REFUND_REVIEW_REQUIRED' WHERE id=?",p.get("id"));return null;}
      if(kind.equals("SHOP")&&"PAID".equals(o.get("status"))){
        store.db.update("UPDATE shop_orders SET status='REFUNDED',refund_id=?,refunded_at_ms=? WHERE id=?",p.get("refund_key"),store.now(),id);retail.release(id);
      }else if(!Set.of("PAID","CLOSED").contains(text(o,"status")))throw new Fault(409,"REFUND_FULFILLMENT_CONFLICT");
      store.db.update("UPDATE wx_payments SET state='REFUNDED',refund_id=?,code_url=NULL,last_error=NULL WHERE id=?",r.refundId(),p.get("id"));return null;
    });
  }
  public void reconcile(){
    if(!enabled())return;
    for(var p:store.db.queryForList("SELECT * FROM wx_payments WHERE state IN ('CREATING','PREPAY','REFUNDING') AND next_check_at_ms<=? ORDER BY next_check_at_ms LIMIT 10",store.now())){
      try{query(Store.number(p,"user_id"),text(p,"order_kind"),text(p,"order_id"));}catch(RuntimeException e){error(p,e);}
    }
  }
  /** 异常退款可由管理员重新查渠道；没有任何强制置成功或绕过验签的入口。 */
  public Map<String,Object> adminRecheck(String kind,String id){
    configured();table(kind);Input.uuid(id);var p=intent(kind,id);if(p==null)throw new Fault(404,"PAYMENT_NOT_FOUND");
    try{
      if("CLOSED".equals(p.get("state")))closeLocal(kind,id);
      else if(!"REFUNDED".equals(p.get("state"))){
        if(!text(p,"out_refund_no").isEmpty())syncRefund(p);else syncPayment(p,false);
      }
    }catch(RuntimeException e){error(p,e);throw new Fault(503,"WECHAT_RECHECK_PENDING");}
    return view(intent(kind,id));
  }
  public Object adminList(){return Map.of("items",store.db.queryForList("SELECT order_kind,order_id,out_trade_no,amount_fen,state,expires_at_ms,last_error FROM wx_payments ORDER BY created_at_ms DESC LIMIT 100").stream().map(Store::wire).toList());}
}
