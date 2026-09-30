import { defineConfig, mergeConfig } from "vite";
import base from "./vite.config";

// Vite 5 does not support envDir:false. The launcher supplies a fresh empty
// directory, so no project .env files are read and ambient VITE_* is stripped.
const envDir = process.env.WORLDFIN_E2E_ENV_DIR;
if (!envDir) throw new Error("Use the isolated tests.live_e2e web launcher");
export default mergeConfig(base, defineConfig({
  envDir,
  server: { proxy: { "/api": { target: "http://127.0.0.1:8012", changeOrigin: true, ws: true } } },
}));
