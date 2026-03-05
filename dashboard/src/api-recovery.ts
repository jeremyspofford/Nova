/**
 * Recovery Service API client.
 *
 * Talks to the recovery sidecar (/recovery-api prefix) which stays alive
 * even when other Nova services are down.
 */

import { getAdminSecret } from './api'

const BASE = '/recovery-api'

async function recoveryFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Admin-Secret': getAdminSecret(),
      ...(options.headers ?? {}),
    },
  })
  if (!resp.ok) {
    const text = await resp.text().catch(() => resp.statusText)
    throw new Error(`${resp.status}: ${text}`)
  }
  if (resp.status === 204) return undefined as T
  return resp.json() as Promise<T>
}

// ── Health ────────────────────────────────────────────────────────────────────

export const getRecoveryHealth = () =>
  recoveryFetch<{ status: string; db?: string }>('/health/ready')

// ── Overview ─────────────────────────────────────────────────────────────────

export interface RecoveryOverview {
  services: {
    up: number
    down: number
    total: number
    details: ServiceStatus[]
  }
  database: {
    connected: boolean
    size?: string
    table_count?: number
    error?: string
  }
  backups: {
    count: number
    latest: BackupInfo | null
    total_size_bytes: number
  }
}

export const getRecoveryOverview = () =>
  recoveryFetch<RecoveryOverview>('/api/v1/recovery/status')

// ── Service Status ───────────────────────────────────────────────────────────

export interface ServiceStatus {
  service: string
  container_name: string | null
  status: string
  health: string
}

export const getServiceStatus = () =>
  recoveryFetch<ServiceStatus[]>('/api/v1/recovery/services')

export const restartService = (serviceName: string) =>
  recoveryFetch<{ service: string; action: string; ok: boolean }>(
    `/api/v1/recovery/services/${serviceName}/restart`,
    { method: 'POST' },
  )

export const restartAllServices = () =>
  recoveryFetch<{ service: string; action: string; ok: boolean }[]>(
    '/api/v1/recovery/services/restart-all',
    { method: 'POST' },
  )

// ── Backups ──────────────────────────────────────────────────────────────────

export interface BackupInfo {
  filename: string
  size_bytes: number
  created_at: string
}

export const getBackups = () =>
  recoveryFetch<BackupInfo[]>('/api/v1/recovery/backups')

export const createBackup = () =>
  recoveryFetch<BackupInfo>('/api/v1/recovery/backups', { method: 'POST' })

export const restoreBackup = (filename: string) =>
  recoveryFetch<{ filename: string; restored: boolean }>(
    `/api/v1/recovery/backups/${encodeURIComponent(filename)}/restore`,
    { method: 'POST' },
  )

export const deleteBackup = (filename: string) =>
  recoveryFetch<{ filename: string; deleted: boolean }>(
    `/api/v1/recovery/backups/${encodeURIComponent(filename)}`,
    { method: 'DELETE' },
  )

// ── Factory Reset ────────────────────────────────────────────────────────────

export interface ResetCategory {
  key: string
  label: string
  default_keep: boolean
}

export const getResetCategories = () =>
  recoveryFetch<ResetCategory[]>('/api/v1/recovery/factory-reset/categories')

export const factoryReset = (keep: string[], confirm: string) =>
  recoveryFetch<{ wiped: string[]; kept: string[]; errors: string[] | null }>(
    '/api/v1/recovery/factory-reset',
    { method: 'POST', body: JSON.stringify({ keep, confirm }) },
  )

// ── Env Management ──────────────────────────────────────────────────────────

export const getEnvVars = () =>
  recoveryFetch<Record<string, string>>('/api/v1/recovery/env')

export const patchEnv = (updates: Record<string, string>) =>
  recoveryFetch<Record<string, string>>(
    '/api/v1/recovery/env',
    { method: 'PATCH', body: JSON.stringify({ updates }) },
  )

// ── Compose Profiles ────────────────────────────────────────────────────────

export const manageComposeProfile = (profile: string, action: 'start' | 'stop') =>
  recoveryFetch<{ profile: string; service: string; action: string; ok: boolean }>(
    '/api/v1/recovery/compose-profiles',
    { method: 'POST', body: JSON.stringify({ profile, action }) },
  )

// ── Remote Access ───────────────────────────────────────────────────────────

export interface RemoteAccessStatus {
  cloudflare: {
    configured: boolean
    container: { name: string; container_name: string | null; status: string; health: string; running: boolean }
  }
  tailscale: {
    configured: boolean
    container: { name: string; container_name: string | null; status: string; health: string; running: boolean }
  }
}

export const getRemoteAccessStatus = () =>
  recoveryFetch<RemoteAccessStatus>('/api/v1/recovery/remote-access/status')
