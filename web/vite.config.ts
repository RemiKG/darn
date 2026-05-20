import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The /api proxy below exists ONLY for local development (vite dev server on 4600
// talking to the Darn server on 4601). In production the server serves the built
// web/dist itself, so the client always uses same-origin relative "/api/..." URLs
// and no proxy is involved.
// DARN_DEV_* env vars let several dev instances run side by side (port,
// proxy target, isolated cache); they have no effect on the production build.
export default defineConfig({
  plugins: [react()],
  cacheDir: process.env.DARN_DEV_CACHE || "node_modules/.vite",
  server: {
    port: Number(process.env.DARN_DEV_PORT || 4600),
    strictPort: true,
    proxy: {
      "/api": {
        target: process.env.DARN_DEV_API || "http://localhost:4601",
        changeOrigin: false,
      },
    },
  },
});
