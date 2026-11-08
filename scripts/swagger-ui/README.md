# Swagger UI 接口调试

用浏览器查看并调试秒杀商城接口。规范文件在 `docs/openapi/openapi.json`（由 `docs/API.md` 归纳）。

## 运行

```bash
python scripts/swagger-ui/serve.py [--target http://localhost:18080] [--port 8090]
```

然后浏览器打开 http://localhost:8090 。

- 前置：目标网关需已启动。Docker 一键部署见 `docs/DEPLOYMENT.md`（`bash scripts/stack.sh up`，出口 `http://localhost:18080`）。
- 页面左上角 `Authorize` 填入登录返回的 64 位 hex 令牌即可调试需鉴权的接口（`/api/seckill/*`、`/api/order/*`、`/api/admin/*`）。
- 无第三方 Python 依赖，Windows 与 WSL 通用。

## 原理

后端（C++/Java/Nginx）没有 CORS 头，Swagger UI 跨域直连会被浏览器拦截。`serve.py` 用同源端口提供页面与规范，并把 `/api/*`、`/health/*`、`/metrics` 原样转发到目标网关，使「Try it out」请求走同源代理。

Swagger UI 的 JS/CSS 从 jsDelivr CDN 加载，首次打开需联网；若 CDN 不可达，可改为自托管 swagger-ui-dist。
