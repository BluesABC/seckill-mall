package com.seckillmall.order.business;
import java.util.*;
import org.springframework.dao.DataAccessException;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.annotation.*;
@RestControllerAdvice
public class Errors {
  @ExceptionHandler(Fault.class)
  public ResponseEntity<?> fault(Fault f) {
    return reply(f.status, f.code);
  }
  @ExceptionHandler(DuplicateKeyException.class)
  public ResponseEntity<?> duplicate() {
    return reply(409, "CONFLICT");
  }
  @ExceptionHandler({DataAccessException.class,
      org.springframework.data.redis.RedisConnectionFailureException.class})
  public ResponseEntity<?>
  dependency(Exception e) {
    System.err.println("dependency error=" + e.getClass().getSimpleName()
        + " cause=" + (e.getCause() == null ? "none" : e.getCause().toString()));
    return reply(503, "DEPENDENCY_UNAVAILABLE");
  }
  @ExceptionHandler({HttpMessageNotReadableException.class,
      org.springframework.web.method.annotation.MethodArgumentTypeMismatchException.class})
  public ResponseEntity<?>
  invalid() {
    return reply(400, "INVALID_ARGUMENT");
  }
  @ExceptionHandler(Exception.class)
  public ResponseEntity<?> unexpected(Exception e) {
    System.err.println("order-api error=" + e.getClass().getSimpleName());
    return reply(500, "INTERNAL_ERROR");
  }
  private static ResponseEntity<?> reply(int status, String code) {
    return ResponseEntity.status(status).body(Map.of("code", code, "message", code, "traceId",
        UUID.randomUUID().toString(), "retryable", status >= 500 || status == 429));
  }
}
