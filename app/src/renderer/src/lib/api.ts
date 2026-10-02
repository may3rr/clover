let cachedInfo: Promise<{
  baseUrl: string
  token: string
  backendError: string | null
}> | null = null

export function getInfo() {
  if (!cachedInfo) cachedInfo = window.citecheck.getInfo()
  return cachedInfo
}

export async function apiFetch(
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  const { baseUrl, token } = await getInfo()
  const headers = new Headers(init.headers)
  if (token) headers.set('X-Citecheck-Token', token)
  return fetch(`${baseUrl}${path}`, { ...init, headers })
}

export async function apiJson<T>(path: string): Promise<T> {
  const r = await apiFetch(path)
  if (!r.ok) throw new Error(`${path} -> ${r.status}`)
  return r.json() as Promise<T>
}

export async function eventsUrl(jobId: string): Promise<string> {
  const { baseUrl, token } = await getInfo()
  return `${baseUrl}/jobs/${jobId}/events?token=${token}`
}
