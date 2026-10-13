package com.seckillmall.order;

import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

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
