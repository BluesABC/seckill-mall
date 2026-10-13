package com.seckillmall.order.messaging;

import java.time.Duration;
import java.util.Map;
import java.util.function.Function;
import org.apache.rocketmq.client.apis.ClientConfiguration;
import org.apache.rocketmq.client.apis.ClientException;
import org.apache.rocketmq.client.apis.ClientServiceProvider;
import org.apache.rocketmq.client.apis.consumer.ConsumeResult;
import org.apache.rocketmq.client.apis.consumer.FilterExpression;
import org.apache.rocketmq.client.apis.consumer.FilterExpressionType;
import org.apache.rocketmq.client.apis.consumer.PushConsumer;
import org.apache.rocketmq.client.apis.message.MessageView;

/** Push transport. S4 supplies a handler that returns SUCCESS only after DB commit. */
public final class RocketPushReceiver implements AutoCloseable {
    private final PushConsumer consumer;

    public RocketPushReceiver(String endpoint, String topic, String group,
                              Function<MessageView, ConsumeResult> handler) throws ClientException {
        this(endpoint, topic, group, handler, 0);
    }

    public RocketPushReceiver(String endpoint, String topic, String group,
                              Function<MessageView, ConsumeResult> handler, int threads) throws ClientException {
        if (threads < 0 || threads > 64) throw new IllegalArgumentException("Consumer threads out of range");
        ClientServiceProvider provider = ClientServiceProvider.loadService();
        ClientConfiguration configuration = ClientConfiguration.newBuilder()
            .setEndpoints(endpoint).enableSsl(false).setRequestTimeout(Duration.ofSeconds(20)).build();
        var builder = provider.newPushConsumerBuilder()
            .setClientConfiguration(configuration)
            .setConsumerGroup(group)
            .setSubscriptionExpressions(Map.of(topic, new FilterExpression("*", FilterExpressionType.TAG)))
            .setMessageListener(handler::apply);
        if (threads > 0) builder.setConsumptionThreadCount(threads)
            .setMaxCacheMessageCount(256).setMaxCacheMessageSizeInBytes(4 * 1024 * 1024);
        consumer = builder.build();
    }

    @Override public void close() throws Exception { consumer.close(); }
}
