package com.seckillmall.order.messaging;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicInteger;
import org.apache.rocketmq.client.apis.consumer.ConsumeResult;

/** Test-only failure callback. S4 uses an order transaction before returning SUCCESS. */
public final class RocketPushFailureProbe {
    private RocketPushFailureProbe() {}

    public static void main(String[] args) throws Exception {
        if (args.length != 4 || !args[2].startsWith("mall_s3_probe_"))
            throw new IllegalArgumentException("endpoint topic probeGroup expectedEventId");
        ObjectMapper mapper = new ObjectMapper();
        AtomicInteger failures = new AtomicInteger();
        try (RocketPushReceiver consumer = new RocketPushReceiver(args[0], args[1], args[2], message -> {
                    try {
                        String body = RocketMessageReceiver.body(message);
                        JsonNode event = mapper.readTree(body);
                        if (args[3].equals(event.path("eventId").asText())) {
                            failures.incrementAndGet();
                            System.out.println("DELIVERY " + body);
                            System.out.flush();
                            return ConsumeResult.FAILURE;
                        }
                    } catch (Exception ignored) {
                        // Malformed payload must not be acknowledged as a valid order event.
                        return ConsumeResult.FAILURE;
                    }
                    // A new probe group may first see unrelated retained fixture events.
                    return ConsumeResult.SUCCESS;
                })) {
            System.out.println("READY"); System.out.flush();
            long deadline = System.nanoTime() + Duration.ofSeconds(50).toNanos();
            while (failures.get() < 2 && System.nanoTime() < deadline) Thread.sleep(200);
            if (failures.get() < 2) throw new IllegalStateException("Push retry was not observed");
            Thread.sleep(1000);
        }
    }
}
