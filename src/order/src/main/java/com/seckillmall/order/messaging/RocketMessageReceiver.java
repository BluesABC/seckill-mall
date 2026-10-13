package com.seckillmall.order.messaging;

import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.StandardCharsets;
import java.nio.charset.CodingErrorAction;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import org.apache.rocketmq.client.apis.ClientConfiguration;
import org.apache.rocketmq.client.apis.ClientException;
import org.apache.rocketmq.client.apis.ClientServiceProvider;
import org.apache.rocketmq.client.apis.consumer.FilterExpression;
import org.apache.rocketmq.client.apis.consumer.FilterExpressionType;
import org.apache.rocketmq.client.apis.consumer.SimpleConsumer;
import org.apache.rocketmq.client.apis.message.MessageView;

/** Transport only. S4 adds the transaction/idempotency handler before calling ack. */
public final class RocketMessageReceiver implements AutoCloseable {
    private final SimpleConsumer consumer;

    public RocketMessageReceiver(String endpoint, String topic, String group) throws ClientException {
        ClientServiceProvider provider = ClientServiceProvider.loadService();
        ClientConfiguration configuration = ClientConfiguration.newBuilder()
            .setEndpoints(endpoint).enableSsl(false)
            .setRequestTimeout(Duration.ofSeconds(20)).build();
        consumer = provider.newSimpleConsumerBuilder()
            .setClientConfiguration(configuration)
            .setConsumerGroup(group)
            .setAwaitDuration(Duration.ofSeconds(2))
            .setSubscriptionExpressions(Map.of(topic, new FilterExpression("*", FilterExpressionType.TAG)))
            .build();
    }

    public List<MessageView> receive(int maximum, Duration invisibleDuration) throws ClientException {
        if (maximum < 1 || maximum > 32) throw new IllegalArgumentException("Invalid batch size");
        return consumer.receive(maximum, invisibleDuration);
    }

    public void ack(MessageView message) throws ClientException { consumer.ack(message); }

    public static String body(MessageView message) throws CharacterCodingException {
        ByteBuffer bytes = message.getBody().asReadOnlyBuffer();
        return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).decode(bytes).toString();
    }

    @Override public void close() throws Exception { consumer.close(); }
}
