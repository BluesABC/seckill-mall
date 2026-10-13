package com.seckillmall.order.messaging;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Duration;
import java.util.List;
import org.apache.rocketmq.client.apis.message.MessageView;

/** Explicit local transport probe; S4 implements the real order consumer. */
public final class RocketTransportProbe {
    private RocketTransportProbe() {}

    public static void main(String[] args) throws Exception {
        if (args.length != 6) throw new IllegalArgumentException(
            "endpoint topic group expectedEventId count ack|no-ack");
        String endpoint = args[0], topic = args[1], group = args[2], eventId = args[3];
        int count = Integer.parseInt(args[4]);
        boolean ack = args[5].equals("ack");
        if ((!ack && !args[5].equals("no-ack")) || count < 1 || count > 32 ||
            !group.startsWith("mall_s3_probe_")) throw new IllegalArgumentException("Probe scope invalid");

        ObjectMapper mapper = new ObjectMapper();
        int matches = 0;
        try (RocketMessageReceiver receiver = new RocketMessageReceiver(endpoint, topic, group)) {
            System.out.println("READY"); System.out.flush();
            long deadline = System.nanoTime() + Duration.ofSeconds(55).toNanos();
            while (matches < count && System.nanoTime() < deadline) {
                // RocketMQ 5.3.2 rejects an invisibility window under 10 seconds.
                List<MessageView> messages = receiver.receive(16, Duration.ofSeconds(10));
                for (MessageView message : messages) {
                    String body = RocketMessageReceiver.body(message);
                    JsonNode event = mapper.readTree(body);
                    if (event == null || event.path("schemaVersion").asInt() != 1 ||
                        !"SECKILL_RESERVED".equals(event.path("eventType").asText()) ||
                        !event.path("eventId").asText().equals(event.path("reservationId").asText())) {
                        // Withhold ACK for malformed data; this probe makes no DLQ guarantee.
                        continue;
                    }
                    boolean expected = eventId.equals(event.path("eventId").asText());
                    // Only the selected fixture participates in the no-ACK fault scenario.
                    if (ack || !expected) receiver.ack(message);
                    // At-least-once delivery can include more copies in the same batch.
                    // This probe reports the requested minimum and still ACKs the full batch.
                    if (expected && matches < count) {
                        ++matches;
                        System.out.println("EVENT " + body);
                        System.out.flush();
                    }
                }
            }
        }
        if (matches != count) throw new IllegalStateException("Expected " + count + " deliveries, got " + matches);
    }
}
