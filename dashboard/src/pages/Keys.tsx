import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { Plus, Trash2, Copy, Check } from 'lucide-react'
import { getKeys, createKey, revokeKey } from '../api'

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const copy = () => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000) }
  return (
    <button onClick={copy} className="ml-1 text-stone-400 dark:text-stone-500 hover:text-stone-700 dark:hover:text-stone-300">
      {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
    </button>
  )
}

export function Keys() {
  const qc = useQueryClient()
  const { data: keys = [], isLoading, error } = useQuery({ queryKey: ['keys'], queryFn: getKeys })
  const [name, setName] = useState('')
  const [rpm, setRpm] = useState(60)
  const [newKey, setNewKey] = useState<string | null>(null)

  const createMutation = useMutation({
    mutationFn: () => createKey(name.trim(), rpm),
    onSuccess: data => { setNewKey(data.raw_key); setName(''); qc.invalidateQueries({ queryKey: ['keys'] }) },
  })

  const revokeMutation = useMutation({
    mutationFn: revokeKey,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['keys'] }),
  })

  return (
    <div className="px-4 py-6 sm:px-6 space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-stone-900 dark:text-stone-100">API Keys</h1>
        <p className="mt-1 text-sm text-stone-400 dark:text-stone-500 max-w-2xl">
          These keys let external clients call Nova's LLM-compatible API at{' '}
          <code className="rounded bg-stone-100 dark:bg-stone-800 px-1 py-0.5 text-xs text-stone-600 dark:text-stone-400">/v1/chat/completions</code>.
          Any tool that speaks the OpenAI API format — IDE plugins, n8n, other AI apps — can send requests
          through Nova using one of these keys. Each key has its own rate limit and usage tracking.
          The <span className="font-medium text-stone-600 dark:text-stone-400">dev-key</span> entries are the default
          development keys created automatically on first startup.
        </p>
      </div>

      {/* New key revealed once */}
      {newKey && (
        <div className="rounded-xl border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/30 p-4">
          <p className="text-sm font-medium text-emerald-700 dark:text-emerald-400 mb-1">Key created — save it now, it won't be shown again</p>
          <div className="flex items-center gap-2 font-mono text-sm text-emerald-800 dark:text-emerald-300">
            {newKey}
            <CopyButton text={newKey} />
          </div>
          <button onClick={() => setNewKey(null)} className="mt-2 text-xs text-emerald-600 dark:text-emerald-400 hover:text-emerald-800 dark:hover:text-emerald-300">Dismiss</button>
        </div>
      )}

      {/* Create form */}
      <div className="rounded-xl border border-stone-200 dark:border-stone-800 bg-white dark:bg-stone-900 p-4">
        <p className="mb-3 text-xs font-medium text-stone-500 dark:text-stone-400 uppercase tracking-wider">Create Key</p>
        <div className="flex flex-col sm:flex-row items-stretch sm:items-end gap-3">
          <div className="flex-1">
            <label className="mb-1 block text-xs text-stone-400 dark:text-stone-500">Name</label>
            <input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. continue-dev"
              className="w-full rounded-md border border-stone-300 dark:border-stone-600 bg-stone-100 dark:bg-stone-800 px-3 py-2 text-sm text-stone-900 dark:text-stone-100 placeholder:text-stone-400 dark:placeholder:text-stone-500 outline-none focus:border-teal-600" />
          </div>
          <div className="flex gap-3 items-end">
            <div className="w-28">
              <label className="mb-1 block text-xs text-stone-400 dark:text-stone-500">RPM limit</label>
              <input type="number" value={rpm} onChange={e => setRpm(Number(e.target.value))} min={1} max={9999}
                className="w-full rounded-md border border-stone-300 dark:border-stone-600 bg-stone-100 dark:bg-stone-800 px-3 py-2 text-sm text-stone-900 dark:text-stone-100 outline-none focus:border-teal-600" />
            </div>
            <button onClick={() => createMutation.mutate()} disabled={!name.trim() || createMutation.isPending}
              className="flex items-center gap-1.5 rounded-md bg-teal-700 px-4 py-2 text-sm text-white hover:bg-teal-500 disabled:opacity-40 shrink-0">
              <Plus size={14} /> Create
            </button>
          </div>
        </div>
        {createMutation.isError && <p className="mt-2 text-xs text-red-600 dark:text-red-400">{String(createMutation.error)}</p>}
      </div>

      {/* Keys table */}
      <div className="rounded-xl border border-stone-200 dark:border-stone-800 bg-white dark:bg-stone-900 overflow-hidden">
        {isLoading && <p className="p-4 text-sm text-stone-400 dark:text-stone-500">Loading…</p>}
        {error && <p className="p-4 text-sm text-red-600 dark:text-red-400">{String(error)}</p>}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-stone-200 dark:border-stone-800 text-xs text-stone-400 dark:text-stone-500">
                <th className="px-3 sm:px-4 py-3 text-left font-medium">Name</th>
                <th className="hidden sm:table-cell px-4 py-3 text-left font-medium">Prefix</th>
                <th className="px-3 sm:px-4 py-3 text-left font-medium">RPM</th>
                <th className="hidden md:table-cell px-4 py-3 text-left font-medium">Created</th>
                <th className="hidden lg:table-cell px-4 py-3 text-left font-medium">Last used</th>
                <th className="px-3 sm:px-4 py-3 text-left font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {keys.map(k => (
                <tr key={k.id} className="border-b border-stone-200/50 dark:border-stone-800/50 hover:bg-stone-100/30 dark:hover:bg-stone-800/30">
                  <td className="px-3 sm:px-4 py-3 font-medium text-stone-900 dark:text-stone-100">{k.name}</td>
                  <td className="hidden sm:table-cell px-4 py-3 font-mono text-xs text-stone-500 dark:text-stone-400">{k.key_prefix}…</td>
                  <td className="px-3 sm:px-4 py-3 text-stone-500 dark:text-stone-400">{k.rate_limit_rpm}/min</td>
                  <td className="hidden md:table-cell px-4 py-3 text-stone-400 dark:text-stone-500 text-xs">
                    {formatDistanceToNow(new Date(k.created_at), { addSuffix: true })}
                  </td>
                  <td className="hidden lg:table-cell px-4 py-3 text-stone-400 dark:text-stone-500 text-xs">
                    {k.last_used_at ? formatDistanceToNow(new Date(k.last_used_at), { addSuffix: true }) : 'never'}
                  </td>
                  <td className="px-3 sm:px-4 py-3">
                    <button onClick={() => { if (confirm(`Revoke "${k.name}"?`)) revokeMutation.mutate(k.id) }}
                      className="text-stone-400 dark:text-stone-500 hover:text-red-600 dark:hover:text-red-400 transition-colors">
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
              {keys.length === 0 && !isLoading && (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-sm text-stone-400 dark:text-stone-500">No API keys yet</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
