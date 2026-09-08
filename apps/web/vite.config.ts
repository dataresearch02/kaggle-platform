import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', 'ARENA_');
  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': env.ARENA_API_PROXY || 'http://127.0.0.1:8000',
        // The Compose gateway checks Arena sessions on HTTP and WebSockets.
        '/jupyter': { target: 'http://127.0.0.1:8080', ws: true },
      },
    },
  };
});
