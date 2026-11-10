import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// Die gebaute Oberfläche wird später vom Backend (FastAPI) unter "/" ausgeliefert, die API liegt unter "/api".
// Im Entwicklungsmodus leitet Vite "/api" an das lokal gestartete Backend weiter.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8010', changeOrigin: false },
    },
  },
  build: {
    outDir: 'dist',
    target: 'es2022',
    sourcemap: false,
    // Kleine Bilder (z. B. Leaflet-Symbole) werden als data:-URI eingebettet – von der CSP (img-src data:) gedeckt.
    assetsInlineLimit: 4096,
  },
});
