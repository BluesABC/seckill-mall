# SNKR//DROP · 运动鞋秒杀商城

Vue 3 / TypeScript / Tailwind 前端，C++ 秒杀服务，RocketMQ 官方 C++/Java SDK，Spring Boot 订单服务，Redis Lua 原子预扣、MySQL 事务库存与幂等订单。

![运动鞋商城](tests/reports/wsl/sports-ui/home-1440.png)

支持商品浏览、真实 SKU 尺码、用户认证、图片验证码抢购、异步订单查询、模拟支付、超时关闭与幂等回补、商品/活动管理。项目使用原创演示品牌和图片，Nike/Adidas 仅作为用户指定的视觉参考。

## 启动（WSL2 / Linux）

安装 Docker Engine 或启用 Docker Desktop 的 WSL 集成，确认 `docker info` 和 `docker compose version` 可用。

```bash
python3 scripts/prepare-deploy.py
bash scripts/stack.sh up
```

浏览器访问 <http://localhost:18080>。管理账号为 `admin`，密码位于本机生成的 `deploy/.env.stack`，请自行保管；它不会提交到仓库。首次构建包含官方 RocketMQ C++ SDK，耗时取决于网络与机器资源。完整配置、持久化和排障见 [部署说明](docs/DEPLOYMENT.md)。

## 导航

- [项目总览与目录](docs/README.md) · [架构](docs/ARCHITECTURE.md) · [API](docs/API.md) · [决策记录](docs/DECISIONS.md)
- [唯一阶段进度记录](docs/PROGRESS.md) · [待办](docs/TODO.md) · [已知问题](docs/BUGS.md)
- [WSL 测试](docs/TESTING.md) · [验收报告](tests/reports/) · [项目 Skill](.agents/skills/seckill-mall/SKILL.md) · [UI Skill](.agents/skills/seckill-mall/UI_Skill.md)

部署面向本机演示，只有 Nginx 绑定回环地址。支付提供者为 MOCK；RocketMQ 单 Broker，未验证高可用。高并发容量指标、对账和完整故障/压测收尾属于 S7，不能把当前功能验收当作生产容量承诺。
