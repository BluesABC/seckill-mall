package com.seckillmall.order.business;
import com.fasterxml.jackson.databind.JsonNode;
public record ReservedEvent(String reservationId, String requestId, long userId, long activityId,
    long skuId, long epoch, long priceFen, long createdAtMs, String traceId) {
  public static ReservedEvent parse(JsonNode n) {
    Input.fields(n, "schemaVersion", "eventType", "eventId", "reservationId", "requestId", "userId",
        "activityId", "skuId", "epoch", "quantity", "priceFen", "createdAtMs", "traceId");
    if (!n.get("schemaVersion").isIntegralNumber() || !n.get("schemaVersion").canConvertToInt()
        || n.get("schemaVersion").intValue() != 1 || !n.get("quantity").isIntegralNumber()
        || !n.get("quantity").canConvertToInt() || n.get("quantity").intValue() != 1
        || !n.get("eventType").isTextual()
        || !"SECKILL_RESERVED".equals(n.get("eventType").textValue()))
      throw new Fault(400, "INVALID_EVENT");
    String reservation = Input.uuid(Input.text(n, "reservationId", 36, 36));
    if (!reservation.equals(Input.uuid(Input.text(n, "eventId", 36, 36))))
      throw new Fault(400, "INVALID_EVENT");
    String trace = Input.text(n, "traceId", 1, 64);
    if (!trace.matches("[A-Za-z0-9-]+"))
      throw new Fault(400, "INVALID_EVENT");
    return new ReservedEvent(reservation, Input.uuid(Input.text(n, "requestId", 36, 36)),
        Input.id(n, "userId"), Input.id(n, "activityId"), Input.id(n, "skuId"),
        Input.id(n, "epoch"), Input.id(n, "priceFen"), Input.id(n, "createdAtMs"), trace);
  }
}
