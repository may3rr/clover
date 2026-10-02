import { apiFetch } from './api'

export type AvatarSpec = {
  kind: 'color' | 'image'
  /** one of the --tile-* hues: indigo | blue | teal | purple | grey */
  color: string
  /** data URL (downscaled to <=128px) when kind === 'image' */
  image: string | null
}

export interface Prefs {
  name: string
  avatar: AvatarSpec
  /** author name stamped into exported Word comments; '' = use name */
  comment_author: string
  /** initials for Word comments; '' = derived from the author name */
  comment_initials: string
}

export const DEFAULT_PREFS: Prefs = {
  name: '',
  avatar: { kind: 'color', color: 'blue', image: null },
  comment_author: '',
  comment_initials: '',
}

export async function getPrefs(): Promise<Prefs> {
  try {
    const r = await apiFetch('/prefs')
    if (!r.ok) return DEFAULT_PREFS
    const p = (await r.json()) as Partial<Prefs>
    return {
      ...DEFAULT_PREFS,
      ...p,
      avatar: { ...DEFAULT_PREFS.avatar, ...(p.avatar ?? {}) },
    }
  } catch {
    return DEFAULT_PREFS
  }
}

export async function putPrefs(p: Prefs): Promise<Prefs> {
  const r = await apiFetch('/prefs', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(p),
  })
  if (!r.ok) throw new Error(`prefs -> ${r.status}`)
  return r.json() as Promise<Prefs>
}

/** Display name for the account chip / comment preview. */
export function displayName(p: Prefs): string {
  return p.name.trim() || '设置'
}

/** Word comment author shown in exports. */
export function commentAuthor(p: Prefs): string {
  return (p.comment_author || p.name).trim() || '引用体检'
}

/** Word comment initials; Word has no photo field — initials are its avatar. */
export function commentInitials(p: Prefs): string {
  const explicit = p.comment_initials.trim()
  if (explicit) return explicit
  const a = commentAuthor(p)
  if (a.length <= 4) return a
  const words = a.split(/\s+/).filter(Boolean)
  if (words.length === 1) return a.slice(0, 2).toUpperCase()
  return words
    .slice(0, 2)
    .map((w) => w[0])
    .join('')
    .toUpperCase()
}
