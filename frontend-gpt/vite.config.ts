import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5178,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:8666" },
  },
  preview: {
    port: 4178,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:8666" },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("/node_modules/zrender/")) return "chart-renderer";
          if (id.includes("/node_modules/echarts/")) return "chart";
          if (
            id.includes("/node_modules/gsap/") ||
            id.includes("/node_modules/@gsap/")
          )
            return "motion";
        },
      },
    },
  },
});
