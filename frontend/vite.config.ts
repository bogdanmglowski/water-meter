import { existsSync } from "node:fs";
import { resolve } from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const repoRootEnvDir = resolve(__dirname, "..");
const envDir =
  existsSync(resolve(repoRootEnvDir, ".env")) ||
  existsSync(resolve(repoRootEnvDir, ".env.example"))
  ? repoRootEnvDir
  : __dirname;

export default defineConfig({
  envDir,
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8080",
        changeOrigin: true,
      },
    },
  },
});
