import { defineConfig } from "vite";

// Dev server proxies /api + /ws to the FastAPI backend so the SPA talks same-origin.
export default defineConfig({
  // The globe.gl (+three.js) vendor chunk is ~1.8MB and is lazy-loaded on its own
  // (src/main.ts dynamic import), so it never blocks first paint — raise the warning
  // limit above it to keep the build output clean.
  // Multi-page: marketing landing at "/", the dashboard SPA at "/app/".
  build: {
    chunkSizeWarningLimit: 2000,
    rollupOptions: {
      input: { main: "index.html", app: "app/index.html" },
    },
  },
  server: {
    port: 8080,
    proxy: {
      "/api": {
        target: process.env.WORLDFIN_API_URL ?? "http://localhost:8010",
        changeOrigin: true,
        ws: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    // Playwright owns e2e/ — keep vitest from picking up its specs.
    exclude: ["node_modules/**", "e2e/**", "e2e-live/**"],
  },
});
