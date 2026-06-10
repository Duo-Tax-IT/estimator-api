import { resolve } from "path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Hashed assets are served by FastAPI's `/assets` mount; the three entry HTMLs
// land where app/main.py already serves them (`/`, `/playground`, `/learn`).
// Dev: proxy the API routes to the FastAPI server on :8000.
// "/learn/" (trailing slash) so the API subpaths proxy but the "/learn" page doesn't.
const api = ["/search", "/estimate", "/photos", "/runs", "/debug", "/learn/", "/chat", "/health"];

// Dev only: map the clean page URLs (what FastAPI serves in prod) to their HTML
// files so cross-page links work against the Vite dev server too.
const cleanUrls = () => ({
  name: "clean-urls",
  configureServer(server) {
    const map = { "/playground": "/playground.html", "/learn": "/learn.html" };
    server.middlewares.use((req, _res, next) => {
      if (map[req.url]) req.url = map[req.url];
      next();
    });
  },
});

export default defineConfig({
  plugins: [react(), tailwindcss(), cleanUrls()],
  resolve: { alias: { "@": resolve(__dirname, "src") } },
  build: {
    outDir: resolve(__dirname, "../app/static"),
    emptyOutDir: true,
    rollupOptions: {
      input: {
        index: resolve(__dirname, "index.html"),
        playground: resolve(__dirname, "playground.html"),
        learn: resolve(__dirname, "learn.html"),
      },
    },
  },
  server: {
    allowedHosts: [".ngrok-free.dev"],
    proxy: Object.fromEntries(api.map((p) => [p, "http://localhost:8000"])),
  },
});
