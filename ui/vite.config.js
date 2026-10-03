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
    // Comma-separated hostnames the dev server will answer for. Empty by
    // default, which means Vite accepts only localhost — set
    // VITE_ALLOWED_HOSTS when serving the UI through a proxy or tunnel.
    allowedHosts: process.env.VITE_ALLOWED_HOSTS
      ? process.env.VITE_ALLOWED_HOSTS.split(',')
      : [],
    hmr: process.env.VITE_HMR_DISABLED === 'true' ? false : { overlay: false },
  },
});
