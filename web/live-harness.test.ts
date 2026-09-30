// @vitest-environment node
// Real configuration resolution against a fake dotenv file (esbuild needs Node).
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test, vi } from "vitest";
import { resolveConfig } from "vite";

test("live build ignores dotenv and pins the real local API proxy", async () => {
  const root = await mkdtemp(join(tmpdir(), "worldfin-vite-test-"));
  try {
    await writeFile(join(root, ".env"), "VITE_ISOLATION_SENTINEL=must-not-load\n");
    const empty = join(root, "empty-env");
    await mkdir(empty);
    vi.stubEnv("WORLDFIN_E2E_ENV_DIR", empty);
    const { default: live } = await import("./vite.live.config");
    const resolved = await resolveConfig({ ...live, root, configFile: false }, "build");
    expect(resolved.env.VITE_ISOLATION_SENTINEL).toBeUndefined();
    expect(resolved.server.proxy?.["/api"]).toMatchObject({
      target: "http://127.0.0.1:8012", ws: true,
    });
  } finally {
    vi.unstubAllEnvs();
    await rm(root, { recursive: true });
  }
});
