// Launches the app in dev mode with CITECHECK_SHOTS=<dir>; the main
// process drives the shot-state loop and quits when done.
import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const appDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const dir = process.argv[2] ?? path.join(appDir, 'shots')

const child = spawn('npx', ['electron-vite', 'dev'], {
  cwd: appDir,
  env: { ...process.env, CITECHECK_SHOTS: dir },
  stdio: 'inherit',
})
child.on('exit', (code) => process.exit(code ?? 0))
