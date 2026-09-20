import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    // The API runs separately in development. Proxying keeps the frontend
    // calling same-origin paths, so nothing changes when it is served from the
    // FastAPI process in production.
    proxy: { "/api": "http://localhost:8000" },
  },
});
