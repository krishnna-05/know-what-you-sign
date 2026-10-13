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
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        // With the backend down, Vite's default is a bare 500, which reads as
        // the analyser crashing. Say what is actually wrong and how to fix it.
        configure: (proxy) => {
          proxy.on("error", (_err, _req, res) => {
            if (!("writeHead" in res) || res.headersSent) return;
            res.writeHead(502, { "Content-Type": "application/json" });
            res.end(
              JSON.stringify({
                detail:
                  "the backend is not running on port 8000. Start it in " +
                  "another terminal with: python scripts/serve.py --dev",
              }),
            );
          });
        },
      },
    },
  },
});
