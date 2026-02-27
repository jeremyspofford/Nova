import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { Plus, Trash2, Copy, Check } from 'lucide-react'
import { getKeys, createKey, revokeKey } from '../api'

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const copy = () => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000) }
  return (
    <button onClick={copy} className="ml-1 text-stone-400 hover:text-stone-700">
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
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-stone-900">API Keys</h1>
        <p className="mt-1 text-sm text-stone-400 max-w-2xl">
          These keys let external clients call Nova's LLM-compatible API at{' '}
          <code className="rounded bg-stone-100 px-1 py-0.5 text-xs text-stone-600">/v1/chat/completions</code>.
          Any tool that speaks the OpenAI API format — IDE plugins, n8n, other AI apps — can send requests
          through Nova using one of these keys. Each key has its own rate limit and usage tracking.
          The <span className="font-medium text-stone-600">dev-key</span> entries are the default
          development keys created automatically on first startup.
        </p>
      </div>

      {/* New key revealed once */}
      {newKey && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
          <p className="text-sm font-medium text-emerald-700 mb-1">Key created — save it now, it won't be shown again</p>
          <div className="flex items-center gap-2 font-mono text-sm text-emerald-800">
            {newKey}
            <CopyButton text={newKey} />
          </div>
          <button onClick={() => setNewKey(null)} className="mt-2 text-xs text-emerald-600 hover:text-emerald-800">Dismiss</button>
        </div>
      )}

      {/* Create form */}
      <div className="rounded-xl border border-stone-200 bg-white p-4">
        <p className="mb-3 text-xs font-medium text-stone-500 uppercase tracking-wider">Create Key</p>
        <div className="flex items-end gap-3">
          <div className="flex-1">
            <label className="mb-1 block text-xs text-stone-400">Name</label>
            <input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. continue-dev"
              className="w-full rounded-md border border-stone-300 bg-stone-100 px-3 py-2 text-sm text-stone-900 placeholder:text-stone-400 outline-none focus:border-teal-600" />
          </div>
          <div className="w-28">
            <label className="mb-1 block text-xs text-stone-400">RPM limit</label>
            <input type="number" value={rpm} onChange={e => setRpm(Number(e.target.value))} min={1} max={9999}
              className="w-full rounded-md border border-stone-300 bg-stone-100 px-3 py-2 text-sm text-stone-900 outline-none focus:border-teal-600" />
          </div>
          <button onClick={() => createMutation.mutate()} disabled={!name.trim() || createMutation.isPending}
            className="flex items-center gap-1.5 rounded-md bg-teal-700 px-4 py-2 text-sm text-white hover:bg-teal-500 disabled:opacity-40">
            <Plus size={14} /> Create
          </button>
        </div>
        {createMutation.isError && <p className="mt-2 text-xs text-red-600">{String(createMutation.error)}</p>}
      </div>

      {/* Keys table */}
      <div className="rounded-xl border border-stone-200 bg-white overflow-hidden">
        {isLoading && <p className="p-4 text-sm text-stone-400">Loading…</p>}
        {error && <p className="p-4 text-sm text-red-600">{String(error)}</p>}
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-stone-200 text-xs text-stone-400">
              {['Name', 'Prefix', 'RPM', 'Created', 'Last used', ''].map(h => (
                <th key={h} className="px-4 py-3 text-left font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {keys.map(k => (
              <tr key={k.id} className="border-b border-stone-200/50 hover:bg-stone-100/30">
                <td className="px-4 py-3 font-medium text-stone-900">{k.name}</td>
                <td className="px-4 py-3 font-mono text-xs text-stone-500">{k.key_prefix}…</td>
                <td className="px-4 py-3 text-stone-500">{k.rate_limit_rpm}/min</td>
                <td className="px-4 py-3 text-stone-400 text-xs">
                  {formatDistanceToNow(new Date(k.created_at), { addSuffix: true })}
                </td>
                <td className="px-4 py-3 text-stone-400 text-xs">
                  {k.last_used_at ? formatDistanceToNow(new Date(k.last_used_at), { addSuffix: true }) : 'never'}
                </td>
                <td className="px-4 py-3">
                  <button onClick={() => { if (confirm(`Revoke "${k.name}"?`)) revokeMutation.mutate(k.id) }}
                    className="text-stone-400 hover:text-red-600 transition-colors">
                    <Trash2 size={14} />
                  </button>
                </td>
              </tr>
            ))}
            {keys.length === 0 && !isLoading && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-sm text-stone-400">No API keys yet</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
