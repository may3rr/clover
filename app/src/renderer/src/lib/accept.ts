/** Which dropped / opened paths the backend can analyze: a .docx, or a
 *  LaTeX project as a .zip/.tar.gz/.tgz/.gz archive, a folder, or the
 *  main .tex file. */
export const ACCEPT_EXTS = ['.docx', '.tex', '.zip', '.tar.gz', '.tgz', '.gz']

export const ACCEPT_ERROR =
  '无法读取这个文件。请拖入 .docx 文件，或 LaTeX 项目的 .zip 压缩包、文件夹。'

export function isPaperPath(p: string): boolean {
  const name = (p.split('/').pop() ?? p).toLowerCase()
  return ACCEPT_EXTS.some((e) => name.endsWith(e))
}

/** Last path segment has no extension: most likely a folder (Finder
 *  "Open With" and Dock drops don't say). The backend validates it. */
export function looksLikeFolder(p: string): boolean {
  const name = p.replace(/\/+$/, '').split('/').pop() ?? ''
  return name.length > 0 && !name.includes('.')
}

/** "sections/intro.tex:42" → "sections/intro.tex 第 42 行" */
export function formatLoc(loc: string | null | undefined): string | null {
  if (!loc) return null
  const m = loc.match(/^(.*):(\d+)$/)
  return m ? `${m[1]} 第 ${m[2]} 行` : loc
}
