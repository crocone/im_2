import { defineConfig } from 'vite';

// Armored Flight - fully client side. Rapier ships as base64-embedded WASM
// (`@dimforge/rapier3d-compat`), so no WASM plugin is required.
export default defineConfig({
  base: './',
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: false,
  },
  build: {
    target: 'es2022',
    chunkSizeWarningLimit: 5200,
    rollupOptions: {
      output: {
        manualChunks: {
          rapier: ['@dimforge/rapier3d-compat'],
          three: ['three'],
        },
      },
    },
    assetsInlineLimit: 0,
  },
  optimizeDeps: {
    exclude: ['@dimforge/rapier3d-compat'],
  },
});
