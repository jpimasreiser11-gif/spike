import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": "http://127.0.0.1:8740" },
    // Vite 6+ enforces fs.allow for ?raw imports too; src/visualChecks.test.ts imports ../spike/dev/visual_checks.js?raw
    fs: { allow: [".", "../spike/dev"] },
  },
  build: { outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 900 },
  test: { environment: "jsdom" },
});
