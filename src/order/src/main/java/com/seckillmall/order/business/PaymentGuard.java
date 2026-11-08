package com.seckillmall.order.business;

/** 防止模式切换或旧MOCK接口绕过真实支付意图；关单必须先获得渠道CLOSED事实。 */
public final class PaymentGuard {
  private PaymentGuard() {}
  public static boolean realMode(){return "WECHAT".equals(System.getenv("MALL_PAYMENT_PROVIDER"));}
  public static void mockPay(Store store,String kind,String id){if(realMode())throw new Fault(409,"USE_WECHAT_PAYMENT");noIntent(store,kind,id);}
  public static void noIntent(Store store,String kind,String id){if(store.one("SELECT id FROM wx_payments WHERE order_kind=? AND order_id=?",kind,id)!=null)throw new Fault(409,"WECHAT_PAYMENT_MANAGED");}
  public static boolean mayClose(Store store,String kind,String id){var row=store.one("SELECT state FROM wx_payments WHERE order_kind=? AND order_id=?",kind,id);return row==null||"CLOSED".equals(row.get("state"));}
  public static void mayShip(Store store,String kind,String id){var row=store.one("SELECT state FROM wx_payments WHERE order_kind=? AND order_id=?",kind,id);if((row==null&&realMode())||(row!=null&&!"SUCCESS".equals(row.get("state"))))throw new Fault(409,"PAYMENT_NOT_SETTLED");}
}
