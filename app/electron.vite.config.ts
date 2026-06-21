import { resolve } from 'node:path';
import { defineConfig, externalizeDepsPlugin } from 'electron-vite';
import react from '@vitejs/plugin-react';

// electron-vite config (CONTRACTS.md §1/§7). Three build targets:
//   main    -> out/main/main.js     (Electron main process; entry = package.json "main")
//   preload -> out/preload/preload.js (contextBridge sandbox script)
//   renderer-> out/renderer/*        (React 18 app served from renderer/index.html)
//
// CONTRACT-NOTE: package.json "main" is `out/main/main.js`, so the main build
// must emit `main.js`. We name the input entry `main` and let electron-vite's
// default `out/main/<name>.js` layout produce exactly that path. Same for the
// preload (`out/preload/preload.js`), which main.ts references by relative path.
export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    build: {
      outDir: 'out/main',
      lib: {
        entry: resolve(__dirname, 'main/main.ts'),
        formats: ['es'],
      },
      rollupOptions: {
        output: {
          entryFileNames: 'main.js',
        },
      },
    },
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    build: {
      outDir: 'out/preload',
      lib: {
        entry: resolve(__dirname, 'main/preload.ts'),
        // CONTRACT-NOTE: preload runs in a sandboxed context that does not
        // support ESM imports of CommonJS Electron internals reliably across
        // versions; emit CJS for the preload so `require('electron')` works.
        formats: ['cjs'],
      },
      rollupOptions: {
        output: {
          entryFileNames: 'preload.js',
        },
      },
    },
  },
  renderer: {
    root: resolve(__dirname, 'renderer'),
    plugins: [react()],
    resolve: {
      alias: {
        '@': resolve(__dirname, 'renderer/src'),
      },
    },
    build: {
      outDir: resolve(__dirname, 'out/renderer'),
      rollupOptions: {
        input: resolve(__dirname, 'renderer/index.html'),
      },
    },
  },
});
