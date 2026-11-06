// One self-contained HTML per entry, for the single-file pitch deck:
//   SINGLE_ENTRY=app|pitch vite build --config site/vite.single.config.ts
// scripts/pitch-single.py runs both and nests the app inside the deck.
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'

const root = __dirname
const entry = process.env.SINGLE_ENTRY ?? 'pitch'

export default defineConfig({
  root,
  base: './',
  plugins: [react()],
  publicDir: false,
  build: {
    outDir: resolve(root, `../site-single/${entry}`),
    emptyOutDir: true,
    assetsInlineLimit: Number.MAX_SAFE_INTEGER,
    cssCodeSplit: false,
    modulePreload: false,
    rollupOptions: {
      input: resolve(root, `${entry}.html`),
      output: { inlineDynamicImports: true },
    },
  },
})
