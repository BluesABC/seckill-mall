import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";
import tailwindcss from '@tailwindcss/vite';
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "MALL_");
  const webPort = Number(env.MALL_WEB_PORT) || 5173;
  const proxy = {
    "/api/seckill": {
      target: env.MALL_SECKILL_ORIGIN || "http://127.0.0.1:8083",
    },
    "/api": { target: env.MALL_ORDER_ORIGIN || "http://127.0.0.1:8082" },
  };
  return {
    plugins: [vue(),tailwindcss()],
    server: { host: "127.0.0.1", port: webPort, strictPort: true, proxy },
    preview: { host: "127.0.0.1", port: webPort, strictPort: true, proxy },
  };
});
