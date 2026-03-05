/**
 * Browser-side Cloudflare API client.
 *
 * CF API returns Access-Control-Allow-Origin: * so these calls work directly
 * from the browser. The user's CF API token stays in browser memory only —
 * never sent to the Nova backend.
 */

const CF_API = 'https://api.cloudflare.com/client/v4'

async function cfFetch<T>(token: string, path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${CF_API}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })
  const json = await resp.json() as { success: boolean; result: T; errors: { message: string }[] }
  if (!json.success) {
    const msg = json.errors?.map(e => e.message).join(', ') || resp.statusText
    throw new Error(msg)
  }
  return json.result
}

export interface CfAccount {
  id: string
  name: string
}

export interface CfZone {
  id: string
  name: string
  status: string
}

export interface CfTunnel {
  id: string
  name: string
  status: string
}

export async function verifyToken(token: string): Promise<boolean> {
  try {
    await cfFetch(token, '/user/tokens/verify')
    return true
  } catch {
    return false
  }
}

export async function listAccounts(token: string): Promise<CfAccount[]> {
  return cfFetch<CfAccount[]>(token, '/accounts?per_page=50')
}

export async function listZones(token: string, accountId: string): Promise<CfZone[]> {
  return cfFetch<CfZone[]>(token, `/zones?account.id=${accountId}&per_page=50&status=active`)
}

export async function createTunnel(
  token: string,
  accountId: string,
  name: string,
): Promise<CfTunnel> {
  // Generate a random tunnel secret
  const secretBytes = crypto.getRandomValues(new Uint8Array(32))
  const tunnelSecret = btoa(String.fromCharCode(...secretBytes))

  return cfFetch<CfTunnel>(token, `/accounts/${accountId}/cfd_tunnel`, {
    method: 'POST',
    body: JSON.stringify({ name, tunnel_secret: tunnelSecret, config_src: 'cloudflare' }),
  })
}

export async function configureTunnelRoute(
  token: string,
  accountId: string,
  tunnelId: string,
  hostname: string,
): Promise<void> {
  await cfFetch(token, `/accounts/${accountId}/cfd_tunnel/${tunnelId}/configurations`, {
    method: 'PUT',
    body: JSON.stringify({
      config: {
        ingress: [
          { hostname, service: 'http://dashboard:3000', originRequest: {} },
          { service: 'http_status:404' },
        ],
      },
    }),
  })
}

export async function createDnsRecord(
  token: string,
  zoneId: string,
  tunnelId: string,
  subdomain: string,
  zoneName: string,
): Promise<void> {
  const fqdn = subdomain ? `${subdomain}.${zoneName}` : zoneName
  await cfFetch(token, `/zones/${zoneId}/dns_records`, {
    method: 'POST',
    body: JSON.stringify({
      type: 'CNAME',
      name: fqdn,
      content: `${tunnelId}.cfargotunnel.com`,
      proxied: true,
    }),
  })
}

export async function getTunnelToken(
  token: string,
  accountId: string,
  tunnelId: string,
): Promise<string> {
  return cfFetch<string>(token, `/accounts/${accountId}/cfd_tunnel/${tunnelId}/token`)
}

export async function deleteTunnel(
  token: string,
  accountId: string,
  tunnelId: string,
): Promise<void> {
  // Clean up connections first
  await cfFetch(token, `/accounts/${accountId}/cfd_tunnel/${tunnelId}/connections`, {
    method: 'DELETE',
  })
  await cfFetch(token, `/accounts/${accountId}/cfd_tunnel/${tunnelId}`, {
    method: 'DELETE',
  })
}
