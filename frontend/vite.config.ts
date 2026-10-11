/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// Dev and preview servers forward /api/* to the FastAPI backend (the /api prefix is removed), so the browser only ever talks to its own origin
// and the backend needs no CORS configuration. Override the target with VITE_API_PROXY_TARGET. Both servers bind to 127.0.0.1 only.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000";
  const proxy = { "/api": { target, changeOrigin: false, rewrite: (p: string) => p.replace(/^\/api/, "") } };
  return {
    plugins: [react()],
    server: { host: "127.0.0.1", port: 5173, proxy },
    preview: { host: "127.0.0.1", port: 4173, proxy },
    test: { environment: "jsdom", globals: true, setupFiles: ["./src/test/setup.ts"], css: false },
  };
});
