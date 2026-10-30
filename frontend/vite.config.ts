import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'ag-grid': ['ag-grid-community', 'ag-grid-react'],
          'ag-studio': ['ag-studio', 'ag-studio-react'],
          vendor: ['react', 'react-dom', 'marked', 'dompurify'],
        },
      },
    },
    chunkSizeWarningLimit: 7000,
  },
});
