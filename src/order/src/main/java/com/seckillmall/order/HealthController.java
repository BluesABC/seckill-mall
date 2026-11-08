package com.seckillmall.order;

import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 区分进程存活与业务就绪；只有数据库、Redis及消费者检查通过才报告ready。
 *
 * <p>业务链路与阅读顺序见 docs/CODE-READING.md。
 */
@RestController
public class HealthController {
    private final org.springframework.beans.factory.ObjectProvider<com.seckillmall.order.business.Workers> workers;
    public HealthController(org.springframework.beans.factory.ObjectProvider<com.seckillmall.order.business.Workers> workers){this.workers=workers;}
    @GetMapping("/health/live")
    public Map<String, Object> live() {
        return Map.of("service", "order", "status", "UP", "stage", "S4");
    }

    @GetMapping("/health/ready")
    public ResponseEntity<Map<String, Object>> ready() {
        var runtime=workers.getIfAvailable();
        if(runtime!=null&&runtime.ready())return ResponseEntity.ok(Map.of("ready",true,"scope","order-db-redis-consumer"));
        return ResponseEntity.status(503).body(Map.of("ready", false,
            "reason", "Business dependencies are not integrated"));
    }
}
