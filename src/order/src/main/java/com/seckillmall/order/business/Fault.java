package com.seckillmall.order.business;
public final class Fault extends RuntimeException {
  public final int status;
  public final String code;
  public Fault(int status, String code) {
    super(code);
    this.status = status;
    this.code = code;
  }
}
