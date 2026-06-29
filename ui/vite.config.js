import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://ownedpulse-api:8001',
        changeOrigin: true,
      },
    },
    allowedHosts: ['rp.ownedai.dev'],
    hmr: process.env.VITE_HMR_DISABLED === 'true' ? false : { overlay: false },
  },
});
