import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Independent of the main app's frontend (5173 -> 8123). This one talks to
// the standalone websearch backend on 8100.
const target = process.env.VITE_API_TARGET || 'http://127.0.0.1:8100';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5175,
    proxy: {
      '/api': { target, changeOrigin: true },
    },
  },
});
