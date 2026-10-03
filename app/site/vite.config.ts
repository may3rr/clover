// Landing page + web replica of the app (GitHub Pages).
//   npm run site:dev      dev server on :5180
//   npm run site:build    -> site-dist/ (relative paths, any sub-path works)
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'

const root = __dirname

export default defineConfig({
  root,
  base: './',
  plugins: [react()],
  server: { port: 5180 },
  preview: { port: 5181 },
  build: {
    outDir: resolve(root, '../site-dist'),
    emptyOutDir: true,
    rollupOptions: {
      input: {
        index: resolve(root, 'index.html'),
        app: resolve(root, 'app.html'),
      },
    },
  },
})
