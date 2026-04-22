import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  resolve: {
    dedupe: ['three'],
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom'],
          neo4j: ['neo4j-driver'],
          graph: ['react-force-graph-3d', 'three', 'graphology', 'graphology-communities-louvain'],
        },
      },
    },
  },
});
