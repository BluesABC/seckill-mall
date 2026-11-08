package com.seckillmall.order.business;
/**
 * 可对外表达的业务异常，携带HTTP状态与稳定业务错误码。
 *
 * <p>业务链路与阅读顺序见 docs/CODE-READING.md。
 */
public final class Fault extends RuntimeException {
  public final int status;
  public final String code;
  public Fault(int status, String code) {
    super(code);
    this.status = status;
    this.code = code;
  }
}
