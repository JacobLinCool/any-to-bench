import { resolve } from 'node:path'
import { svelte } from '@sveltejs/vite-plugin-svelte'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// Real HTML entries rather than a client router: GitHub Pages serves static
// files, so another document costs nothing and needs no 404.html rewrite hack.
export default defineConfig({
  base: process.env.SITE_BASE ?? '/any-to-bench/',
  plugins: [tailwindcss(), svelte()],
  build: {
    rollupOptions: {
      input: {
        main: resolve(import.meta.dirname, 'index.html'),
        viewer: resolve(import.meta.dirname, 'viewer.html'),
        results: resolve(import.meta.dirname, 'results.html'),
      },
    },
  },
})
