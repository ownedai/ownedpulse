import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { readFileSync } from 'fs';

const { version } = JSON.parse(readFileSync('./package.json', 'utf-8'));

export default defineConfig({
  define: {
    'import.meta.env.VITE_APP_VERSION': JSON.stringify(version),
  },
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://regpulse-api:8001',
        changeOrigin: true,
      },
    },
    allowedHosts: ['rp.ownedai.dev'],
    hmr: process.env.VITE_HMR_DISABLED === 'true' ? false : { overlay: false },
  },
});
