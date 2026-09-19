import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The console API (FastAPI) serves the built app from web/dist in the demo.
// During development this proxies /api to it so SSE and fetches share an origin.
const api = process.env.TESSERA_API ?? "http://localhost:8765";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { "/api": { target: api, changeOrigin: true } },
  },
  build: { outDir: "dist", sourcemap: false },
});
