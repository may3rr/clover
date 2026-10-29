/** The target journal or conference typed on the home screen ('' = no
 *  benchmarking). One value for the whole app: the confirmation page
 *  starts from it and writes its changes back. */
export const VENUE_KEY = 'clover.venue'

// before F34 the home screen stored a menu id; nothing stored meant EMNLP
// was preselected, which now means blank: benchmarking is opt-in
const LEGACY: Record<string, string> = {
  emnlp: 'EMNLP',
  acl: 'ACL',
  naacl: 'NAACL',
  'findings-emnlp': 'Findings of EMNLP',
}

export function migrateVenue(stored: string | null): string {
  if (stored === null) return ''
  return LEGACY[stored] ?? stored.trim()
}

export function readVenue(): string {
  try {
    return migrateVenue(localStorage.getItem(VENUE_KEY))
  } catch {
    return ''
  }
}

export function saveVenue(v: string): void {
  try {
    localStorage.setItem(VENUE_KEY, v)
  } catch {
    /* private mode: the choice just lasts for this session */
  }
}
