/**
 * Standalone Vite config for the renderer process.
 *
 * electron-vite 5 has a bug where it drops Svelte plugins during its
 * config resolution pipeline. This config is used directly via
 * `vite build --config vite.renderer.config.ts` as a workaround.
 */

import { resolve } from 'path';
import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  root: resolve('src/renderer'),
  plugins: [
    ...svelte({
      configFile: resolve('svelte.config.js'),
    }),
  ],
  build: {
    outDir: resolve('out/renderer'),
    emptyOutDir: true,
    target: 'chrome130',
    modulePreload: { polyfill: false },
    minify: false,
    rollupOptions: {
      input: {
        index: resolve('src/renderer/index.html'),
      },
    },
  },
  base: './',
  envDir: resolve('.'),
  envPrefix: ['RENDERER_VITE_', 'VITE_'],
});
