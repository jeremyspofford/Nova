/**
 * Browser-side Tailscale API client.
 *
 * Note: If Tailscale API blocks browser CORS, these calls will be proxied
 * through the recovery service. The user's TS API key stays in browser memory.
 */

const TS_API = 'https://api.tailscale.com/api/v2'

async function tsFetch<T>(apiKey: string, path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${TS_API}${path}`, {
    ...init,
    headers: {
      Authorization: `Basic ${btoa(apiKey + ':')}`,
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })
  if (!resp.ok) {
    const text = await resp.text().catch(() => resp.statusText)
    throw new Error(`Tailscale API ${resp.status}: ${text}`)
  }
  if (resp.status === 204) return undefined as T
  return resp.json() as Promise<T>
}

export interface TsAuthKey {
  id: string
  key: string
  created: string
  expires: string
}

export async function verifyApiKey(apiKey: string): Promise<boolean> {
  try {
    // List devices as a verification check
    await tsFetch(apiKey, '/tailnet/-/devices?fields=default')
    return true
  } catch {
    return false
  }
}

export async function createAuthKey(
  apiKey: string,
  tailnet: string = '-',
): Promise<TsAuthKey> {
  return tsFetch<TsAuthKey>(apiKey, `/tailnet/${tailnet}/keys`, {
    method: 'POST',
    body: JSON.stringify({
      capabilities: {
        devices: {
          create: {
            reusable: false,
            ephemeral: false,
            preauthorized: true,
            tags: ['tag:nova'],
          },
        },
      },
      expirySeconds: 86400, // 24h — only needs to last for initial auth
      description: 'Nova remote access setup',
    }),
  })
}
