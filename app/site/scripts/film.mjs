// The narrated cut, end to end.
//
//   npm run site:film -- --voice <dir of 01.wav ...> [--music song.mp3]
//                        [--template frame|desk] [--skip-record]
//
// 1. record the 'film' tour paced by the clip lengths (record.mjs --film),
//    which also logs the video time each line starts (film.timeline.json)
// 2. put it in the landing-page frame (frame.mjs), 3840 x 2160 @ 60
// 3. lay every clip at its logged time; with --music, mix the song under
//    the voice (ducked while someone speaks) and fade it out at the end
//
// Output in site-videos/06-成片/: 成片-无声.mp4, 旁白音轨.wav, 成片-旁白.mp4
// and, with --music, 成片-旁白-配乐.mp4.
import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const appDir = path.resolve(here, '../..')
const argv = process.argv.slice(2)
const opt = (k) => {
  const i = argv.indexOf(`--${k}`)
  return i >= 0 ? argv[i + 1] : undefined
}
const voice = path.resolve(opt('voice') ?? path.join(appDir, 'site-videos/voice'))
const music = opt('music') && path.resolve(opt('music'))
const template = opt('template') ?? 'frame'
const tag = template === 'desk' ? '桌面-' : ''
const out = path.join(appDir, 'site-videos/06-成片')
const rawDir = path.join(out, 'raw')
fs.mkdirSync(rawDir, { recursive: true })
const run = (cmd, args) => {
  const r = spawnSync(cmd, args, { stdio: ['ignore', 'inherit', 'inherit'] })
  if (r.status !== 0) throw new Error(`${cmd} ${args.slice(0, 3).join(' ')} failed`)
}
const dur = (f) =>
  Number(spawnSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', f], { encoding: 'utf8' }).stdout.trim())

// 1. record
const raw = path.join(rawDir, 'film.mp4')
if (!argv.includes('--skip-record'))
  run('node', [path.join(here, 'record.mjs'), '--film', voice, '--fps', '60', '--out', rawDir])

// 2. frame
run('node', [path.join(here, 'frame.mjs'), '--template', template, raw])
const framed = path.join(appDir, `site-videos/05-成片-${template === 'desk' ? '桌面' : '主页框'}/film.mp4`)
const silent = path.join(out, `成片-${tag}无声.mp4`)
fs.copyFileSync(framed, silent)
const total = dur(silent)

// 3. narration track: each clip delayed to its line's start
const { lines } = JSON.parse(fs.readFileSync(path.join(rawDir, 'film.timeline.json'), 'utf8'))
const clips = fs.readdirSync(voice).filter((f) => /^\d+\.(wav|mp3)$/.test(f)).sort()
const ins = []
const parts = []
lines.forEach((l, i) => {
  ins.push('-i', path.join(voice, clips[l.line - 1]))
  parts.push(`[${i}:a]aresample=48000,aformat=channel_layouts=stereo,adelay=${Math.round(l.t * 1000)}:all=1[a${i}]`)
})
const narr = path.join(out, '旁白音轨.wav')
run('ffmpeg', ['-y', '-v', 'error', ...ins, '-filter_complex',
  `${parts.join(';')};${lines.map((_, i) => `[a${i}]`).join('')}amix=inputs=${lines.length}:normalize=0,apad,atrim=0:${total}[out]`,
  '-map', '[out]', '-c:a', 'pcm_s16le', narr])
run('ffmpeg', ['-y', '-v', 'error', '-i', silent, '-i', narr, '-map', '0:v', '-map', '1:a',
  '-c:v', 'copy', '-c:a', 'aac', '-b:a', '256k', '-shortest', path.join(out, `成片-${tag}旁白.mp4`)])

// 4. optional music, ducked under the voice
if (music) {
  const fade = Math.max(0, total - 4)
  run('ffmpeg', ['-y', '-v', 'error', '-i', silent, '-i', narr, '-stream_loop', '-1', '-i', music, '-filter_complex',
    `[2:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:${total},volume=0.32,afade=t=in:d=1.5,afade=t=out:st=${fade}:d=4[m];` +
    `[1:a]asplit[v][key];[m][key]sidechaincompress=threshold=0.02:ratio=6:attack=80:release=600[duck];` +
    `[v][duck]amix=inputs=2:normalize=0[a]`,
    '-map', '0:v', '-map', '[a]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '256k', '-shortest', path.join(out, `成片-${tag}旁白-配乐.mp4`)])
}
console.log(`\n${path.relative(appDir, out)}  ${total.toFixed(1)}s`)
for (const l of lines) console.log(`  ${l.t.toFixed(2).padStart(6)}s  line ${l.line}`)
