import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// En developpement, /api est relaye vers l'API joignable sur le Dell :
// - par le tunnel SSH vers la production (ssh -N -L 8001:127.0.0.1:8001 lorakus-prod),
// - ou par la pile locale (make up).
const apiTarget = process.env["LORAKUS_API_URL"] ?? "http://localhost:8001";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    // "localhost" (et non 127.0.0.1) : le navigateur traite localhost comme un contexte
    // securise, condition pour accepter le cookie de session Secure en HTTP.
    host: "localhost",
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: apiTarget, changeOrigin: false } },
  },
  build: {
    target: "es2022",
    sourcemap: false,
    // Environ 190 Ko compresses (React et le rendu Markdown), mis en cache par le service
    // worker apres la premiere visite : acceptable, on ne decoupe pas avant d'en avoir besoin.
    chunkSizeWarningLimit: 700,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
