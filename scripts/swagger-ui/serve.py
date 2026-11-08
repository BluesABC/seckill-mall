#!/usr/bin/env python3
"""
本地 Swagger UI + 同源反向代理，用于在浏览器里查看并调试秒杀商城接口。

无第三方依赖，Python 3 标准库即可（Windows 与 WSL 通用）。
它做两件事：
  1. 在本地端口（默认 8090）提供 Swagger UI 页面与 docs/openapi/openapi.json；
  2. 把 /api/*、/health/*、/metrics 原样转发到目标网关（默认 http://localhost:18080）。

为什么要同源代理：后端（C++/Java/Nginx）没有 CORS 头，Swagger UI 直接跨域调用
会被浏览器拦截；本脚本让「Try it out」请求走同源，再由服务端转发，绕过 CORS。

用法：
  python scripts/swagger-ui/serve.py [--target http://localhost:18080] [--port 8090]

然后浏览器打开 http://localhost:8090 。
目标网关需要已启动（Docker: bash scripts/stack.sh up，见 docs/DEPLOYMENT.md）。
"""
import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.normpath(os.path.join(ROOT, "..", "..", "docs", "openapi", "openapi.json"))

# 转发时剔除这些头，避免破坏代理语义 / 触发 gzip 解码问题。
EXCLUDE_REQ_HEADERS = {
    "host", "content-length", "connection", "accept-encoding", "cookie", "origin", "referer",
}
PROXY_PREFIXES = ("/api/", "/health/", "/metrics")


class Handler(BaseHTTPRequestHandler):
    target = "http://localhost:18080"

    def log_message(self, fmt, *args):  # 精简访问日志
        sys.stderr.write("[swagger-ui] %s %s\n" % (self.command, self.path))

    def _send_bytes(self, status, body, ctype):
        self.send_response(status)
        if ctype:
            self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, path):
        if path in ("/", "/index.html"):
            with open(os.path.join(ROOT, "index.html"), "rb") as f:
                self._send_bytes(200, f.read(), "text/html; charset=utf-8")
            return
        if path == "/openapi.json":
            with open(SPEC, "rb") as f:
                self._send_bytes(200, f.read(), "application/json; charset=utf-8")
            return
        self._send_bytes(404, b"not found", "text/plain")

    def _forward(self):
        target = self.target.rstrip("/")
        url = target + self.path
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None

        headers = {}
        for k, v in self.headers.items():
            if k.lower() not in EXCLUDE_REQ_HEADERS:
                headers[k] = v
        headers.setdefault("Accept-Encoding", "identity")

        req = Request(url, data=body, headers=headers, method=self.command)
        try:
            resp = urlopen(req, timeout=60)
        except HTTPError as e:
            resp = e
        except URLError as e:
            self._send_bytes(502, ("无法连接后端 %s：%s" % (target, e.reason)).encode("utf-8"), "text/plain; charset=utf-8")
            return

        data = resp.read()
        self._send_bytes(resp.getcode(), data, resp.headers.get("Content-Type"))

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path.startswith(PROXY_PREFIXES):
            self._forward()
        else:
            self._serve_static(path)

    def do_POST(self):
        self._forward()

    def do_PATCH(self):
        self._forward()

    def do_PUT(self):
        self._forward()

    def do_DELETE(self):
        self._forward()


def main():
    ap = argparse.ArgumentParser(description="本地 Swagger UI + 同源反向代理")
    ap.add_argument("--target", default="http://localhost:18080", help="后端网关地址（默认 http://localhost:18080）")
    ap.add_argument("--port", type=int, default=8090, help="本地监听端口（默认 8090）")
    args = ap.parse_args()

    if not os.path.exists(SPEC):
        sys.exit("未找到 OpenAPI 规范：%s" % SPEC)
    if not os.path.exists(os.path.join(ROOT, "index.html")):
        sys.exit("未找到 index.html")

    Handler.target = args.target
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("Swagger UI:  http://localhost:%d  （目标后端 %s）" % (args.port, args.target))
    print("按 Ctrl+C 退出。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")


if __name__ == "__main__":
    main()
