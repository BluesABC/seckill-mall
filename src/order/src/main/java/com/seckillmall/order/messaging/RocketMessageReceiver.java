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
/**
 * SimpleConsumer传输封装及严格UTF-8解码；本类不自行决定订单事务何时完成。
 *
 * <p>业务链路与阅读顺序见 docs/CODE-READING.md。
 */
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

    /**
     * 批量获取临时不可见消息；未确认的消息可在租约后重新投递。
     */
    public List<MessageView> receive(int maximum, Duration invisibleDuration) throws ClientException {
        if (maximum < 1 || maximum > 32) throw new IllegalArgumentException("Invalid batch size");
        return consumer.receive(maximum, invisibleDuration);
    }

    /**
     * 调用方必须先完成持久业务处理；接收或JSON解析成功不是确认时机。
     */
    public void ack(MessageView message) throws ClientException { consumer.ack(message); }

    /**
     * 按严格UTF-8解码消息，非法字节报告错误，不静默替换后改变业务payload。
     */
    public static String body(MessageView message) throws CharacterCodingException {
        ByteBuffer bytes = message.getBody().asReadOnlyBuffer();
        return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).decode(bytes).toString();
    }

    @Override public void close() throws Exception { consumer.close(); }
}
