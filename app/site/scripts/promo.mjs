// The captioned product cut on the Chinese demo paper: no narration, the
// captions under the window tell the story over a slow flowing backdrop;
// no audio (music is added in the editor).
//
//   node site/scripts/promo.mjs [--skip-record]       (PYTHON=<python with numpy>)
//
// 1. silent clips set each caption's reading time; record.mjs --film plays
//    the film-zh tour (tour.ts FILM_ZH) on the redacted Chinese report and
//    logs when each caption starts
// 2. the window (promo slot from frame.mjs) goes over a flowing backdrop
//    (promo-bg.py) with a soft shadow
// 3. captions (rsvg-convert, PingFang SC) fade in under the window; the
//    landing cover closes the cut
//
// Output: site-videos/07-宣传/宣传-无配乐.mp4
import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const appDir = path.resolve(here, '../..')
const argv = process.argv.slice(2)
const out = path.join(appDir, 'site-videos/07-宣传')
const work = path.join(out, 'work')
fs.mkdirSync(work, { recursive: true })
const run = (cmd, args) => {
  const r = spawnSync(cmd, args, { stdio: ['ignore', 'inherit', 'inherit'] })
  if (r.status !== 0) throw new Error(`${cmd} ${args.slice(0, 4).join(' ')} failed`)
}
const dur = (f) =>
  Number(spawnSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', f], { encoding: 'utf8' }).stdout.trim())

// [kicker, caption]; one per `speak` mark in FILM_ZH
const CAPTIONS = [
  ['', '投稿前，每一条引用你都核对过吗'],
  ['', 'Clover，投稿前的引用体检'],
  ['', '拖入论文，四项检查同时进行'],
  ['', '一篇已发表的期刊综述，查出 43 个问题'],
  ['文献真实性', '这条参考文献在 Crossref、OpenAlex、arXiv 都查不到'],
  ['论断支持度', '被引文献讲的是另一项工作，可能引错了'],
  ['论断支持度', '每条判断都附被引原文，证据逐字可查'],
  ['格式规范', '错别字直接写成 Word 修订：制 改为 置'],
  ['期刊对标', '对照《电子学报》3 篇范文，近三年文献占比 0%，范文为 75% 至 91%'],
  ['导出', '一键导出 Word，问题写成批注，修订由你逐条接受'],
  ['隐私', '发往云端的每一段内容，都能逐条查看'],
  ['隐私', '打开隐私模式，题目、摘要和章节标题不出本机'],
  ['', '核对交给 Clover，判断留给作者'],
]
const reading = (t) => Math.max(2.4, 1.2 + [...t].length * 0.17)

// 1. record
const durDir = path.join(work, 'durs')
const raw = path.join(work, 'film-zh.mp4')
if (!argv.includes('--skip-record')) {
  fs.rmSync(durDir, { recursive: true, force: true })
  fs.mkdirSync(durDir)
  CAPTIONS.forEach(([, t], i) =>
    run('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
      '-t', reading(t).toFixed(2), path.join(durDir, `${String(i + 1).padStart(2, '0')}.wav`)]))
  run('node', [path.join(here, 'record.mjs'), '--film', durDir, '--tour', 'film-zh',
    '--query', 'data=zh&redact=blur', '--fps', '60', '--out', work])
}

// 2. layout: the promo slot (desk.html?cap=1) and its rounded mask
const slotFile = path.join(appDir, 'site-videos/frame/promo.slot.json')
const maskFile = path.join(appDir, 'site-videos/frame/promo.mask.png')
if (!fs.existsSync(slotFile) || !fs.existsSync(maskFile))
  run('node', [path.join(here, 'frame.mjs'), '--template', 'promo', raw])
const slot = JSON.parse(fs.readFileSync(slotFile, 'utf8'))
const filmLen = dur(raw)

// flowing backdrop (promo-bg.py) and the window's soft shadow
const bg = path.join(work, 'bg.mp4')
run(process.env.PYTHON ?? 'python3', [path.join(here, 'promo-bg.py'), bg, String(Math.ceil(filmLen) + 1)])
const shadow = path.join(work, 'shadow.png')
spawnSync('rsvg-convert', ['-o', shadow], {
  input: `<svg xmlns="http://www.w3.org/2000/svg" width="3840" height="2160">
  <filter id="b" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="72"/></filter>
  <rect x="${slot.x}" y="${slot.y + 40}" width="${slot.w}" height="${slot.h}" rx="${slot.radius}" fill="#1e2440" fill-opacity="0.22" filter="url(#b)"/>
</svg>`,
})

// 3. captions: a 3840-wide strip for the band under the window (slot is in 2x px)
const band = { y: slot.y + slot.h, h: 2160 - slot.y - slot.h }
const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;')
const pngs = CAPTIONS.map(([k, t], i) => {
  const f = path.join(work, `cap-${String(i + 1).padStart(2, '0')}.png`)
  const mid = band.h / 2
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="3840" height="${band.h}">
  <style>text{font-family:'PingFang SC';text-anchor:middle}</style>
  ${k ? `<text x="1920" y="${mid - 40}" font-size="44" font-weight="500" fill="#37352f" fill-opacity="0.62">${esc(k)}</text>` : ''}
  <text x="1920" y="${k ? mid + 52 : mid + 26}" font-size="${k ? 64 : 72}" font-weight="600" fill="#37352f">${esc(t)}</text>
</svg>`
  spawnSync('rsvg-convert', ['-o', f], { input: svg })
  return f
})
const { lines } = JSON.parse(fs.readFileSync(path.join(work, 'film-zh.timeline.json'), 'utf8'))
const starts = CAPTIONS.map((_, i) => lines.find((l) => l.line === i + 1)?.t ?? 0)

// cover card at the end, crossfaded in
const cover = path.join(appDir, 'site-videos/frame/cover-zh-light.png')
run('node', [path.join(here, 'frame.mjs'), '--template', 'cover-zh'])
const HOLD = 4
const XF = 0.8

const inputs = [
  '-i', bg,
  '-loop', '1', '-t', String(filmLen), '-i', shadow,
  '-i', raw,
  '-loop', '1', '-t', String(filmLen), '-i', maskFile,
]
const parts = [
  `[0:v]trim=0:${filmLen.toFixed(3)},setpts=PTS-STARTPTS,scale=3840:2160:flags=bicubic,fps=60,noise=alls=3:allf=t,format=rgba[bg]`,
  `[bg][1:v]overlay=0:0[bs]`,
  `[2:v]scale=${slot.w}:${slot.h}:flags=lanczos,format=rgba[w]`,
  `[3:v]format=rgba,alphaextract[m]`,
  `[w][m]alphamerge[wm]`,
  `[bs][wm]overlay=${slot.x}:${slot.y}:shortest=1[base]`,
]
let last = '[base]'
pngs.forEach((f, i) => {
  const a = starts[i]
  const b = i + 1 < starts.length ? starts[i + 1] - 0.1 : filmLen - 0.2
  const n = i + 4
  inputs.push('-loop', '1', '-t', String(filmLen), '-i', f)
  parts.push(
    `[${n}:v]format=rgba,fade=in:st=${a.toFixed(3)}:d=0.25:alpha=1,fade=out:st=${(b - 0.25).toFixed(3)}:d=0.25:alpha=1[c${i}]`,
    `${last}[c${i}]overlay=0:${band.y}:enable='between(t,${a.toFixed(3)},${b.toFixed(3)})'[v${i}]`)
  last = `[v${i}]`
})
const ci = pngs.length + 4
inputs.push('-loop', '1', '-t', String(HOLD), '-r', '60', '-i', cover)
parts.push(
  `${last}fps=60,format=yuv420p,settb=AVTB[film]`,
  `[${ci}:v]scale=3840:2160,fps=60,format=yuv420p,settb=AVTB[end]`,
  `[film][end]xfade=transition=fade:duration=${XF}:offset=${(filmLen - XF).toFixed(3)}[out]`)
const vt = /h264_videotoolbox/.test(spawnSync('ffmpeg', ['-hide_banner', '-encoders'], { encoding: 'utf8' }).stdout)
const enc = vt ? ['-c:v', 'h264_videotoolbox', '-b:v', '45M'] : ['-c:v', 'libx264', '-preset', 'medium', '-crf', '16']
const dst = path.join(out, '宣传-无配乐.mp4')
run('ffmpeg', ['-y', '-loglevel', 'error', ...inputs, '-filter_complex', parts.join(';'), '-map', '[out]',
  '-r', '60', ...enc, '-movflags', '+faststart', dst])
console.log(`${path.relative(appDir, dst)}  ${dur(dst).toFixed(1)} s`)
