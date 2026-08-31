import { defineConfig } from 'vite';

export default defineConfig({
  // Dev server config
  server: {
    port: 5173,
    open: true, // Auto-open browser

    // Proxy /api requests to backend (FastAPI on port 8000)
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // Không rewrite — giữ nguyên /api prefix
      },
    },
  },

  // Build output
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
