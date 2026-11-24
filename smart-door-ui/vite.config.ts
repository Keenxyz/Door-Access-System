import { readFileSync } from "node:fs";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  let existing: { project_url?: string; publishable_key?: string } = {};
  try {
    existing = JSON.parse(readFileSync(new URL("../dashboard.local.json", import.meta.url), "utf8"));
  } catch { /* Standalone demo and .env.local also work. */ }
  const url = (env.VITE_SUPABASE_URL || existing.project_url || "").trim().replace(/\/$/, "");
  const key = (env.VITE_SUPABASE_PUBLISHABLE_KEY || existing.publishable_key || "").trim();
  const config = /^https:\/\/[a-z0-9]+\.supabase\.co$/.test(url) && /^sb_publishable_[\w-]+$/.test(key)
    ? { url, key } : null;
  return { define: { __DOOR_CONFIG__: JSON.stringify(config) }, server: { host: "127.0.0.1", port: 5173, strictPort: true } };
});
