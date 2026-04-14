export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const base: string = import.meta.env.VITE_API_URL ?? ""
  const res = await fetch(`${base}${path}`, init)
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText)
    throw new Error(`${res.status}: ${detail}`)
  }
  return res.json() as Promise<T>
}
