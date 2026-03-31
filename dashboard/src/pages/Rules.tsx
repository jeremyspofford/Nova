import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, RefreshCw, ChevronDown, ChevronRight, Trash2, Lock, ShieldAlert } from 'lucide-react'
import clsx from 'clsx'
import { getRules, createRule, updateRule, deleteRule, apiFetch } from '../api'
import {
  Card, Badge, Toggle, Metric, Button, Input, Textarea, Modal, ConfirmDialog, EmptyState, Skeleton,
} from '../components/ui'

// ── Types ───────────────────────────────────────────────────────────────────

interface Rule {
  id: string
  name: string
  description: string
  rule_text: string
  enforcement: string
  pattern: string | null
  target_tools: string[] | null
  action: string
  category: string
  severity: string
  enabled: boolean
  is_system: boolean
  created_at: string
  updated_at: string
}

interface ToolCatalogEntry {
  category: string
  tools: { name: string; description: string }[]
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function useToolCatalog() {
  return useQuery({
    queryKey: ['tool-catalog'],
    queryFn: () => apiFetch<ToolCatalogEntry[]>('/api/v1/tools'),
    staleTime: 60_000,
    select: (data) => data.flatMap(cat => cat.tools.map(t => t.name)).sort(),
  })
}

// ── Tool multi-select ───────────────────────────────────────────────────────

function ToolSelector({
  selected,
  onChange,
}: {
  selected: string[]
  onChange: (tools: string[]) => void
}) {
  const { data: allTools = [] } = useToolCatalog()
  const [search, setSearch] = useState('')

  const filtered = allTools.filter(t =>
    !selected.includes(t) && t.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div>
      <p className="text-micro font-medium text-content-secondary mb-1">
        Applies to tools <span className="text-content-tertiary">(empty = all tools)</span>
      </p>

      {/* Selected tools */}
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {selected.map(tool => (
            <button key={tool} onClick={() => onChange(selected.filter(t => t !== tool))}>
              <Badge color="accent" size="sm" className="cursor-pointer">
                {tool} &times;
              </Badge>
            </button>
          ))}
        </div>
      )}

      {/* Search + dropdown */}
      <Input
        value={search}
        onChange={e => setSearch(e.target.value)}
        placeholder="Search tools to add..."
      />
      {search && filtered.length > 0 && (
        <div className="mt-1 max-h-32 overflow-y-auto rounded border border-border-subtle bg-surface-elevated">
          {filtered.slice(0, 10).map(tool => (
            <button
              key={tool}
              className="block w-full px-3 py-1.5 text-left text-caption hover:bg-surface-hover"
              onClick={() => { onChange([...selected, tool]); setSearch('') }}
            >
              {tool}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Rule card ───────────────────────────────────────────────────────────────

function RuleCard({ rule, onDelete }: { rule: Rule; onDelete: (r: Rule) => void }) {
  const [expanded, setExpanded] = useState(false)
  const [editing, setEditing] = useState(false)
  const qc = useQueryClient()

  const toggleEnabled = useMutation({
    mutationFn: () => updateRule(rule.id, { enabled: !rule.enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['rules'] }),
  })

  const [editName, setEditName] = useState(rule.name)
  const [editRuleText, setEditRuleText] = useState(rule.rule_text)
  const [editAction, setEditAction] = useState(rule.action)
  const [editTargetTools, setEditTargetTools] = useState<string[]>(rule.target_tools ?? [])
  const [editPattern, setEditPattern] = useState(rule.pattern ?? '')

  const resetEdit = () => {
    setEditName(rule.name)
    setEditRuleText(rule.rule_text)
    setEditAction(rule.action)
    setEditTargetTools(rule.target_tools ?? [])
    setEditPattern(rule.pattern ?? '')
    setEditing(false)
  }

  const save = useMutation({
    mutationFn: () =>
      updateRule(rule.id, {
        name: editName,
        rule_text: editRuleText,
        action: editAction,
        target_tools: editTargetTools.length > 0 ? editTargetTools : null,
        pattern: editPattern.trim() || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['rules'] })
      setEditing(false)
    },
  })

  return (
    <Card
      variant={rule.enabled ? 'default' : 'outlined'}
      className={clsx(!rule.enabled && 'opacity-60')}
    >
      {/* Collapsed */}
      <div className="flex items-center gap-3 px-5 py-4">
        <button
          onClick={() => setExpanded(e => !e)}
          className="flex shrink-0 items-center gap-3 min-w-0 flex-1 text-left"
        >
          <span className="shrink-0 text-content-tertiary">
            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </span>
          {rule.is_system && <Lock size={12} className="shrink-0 text-content-tertiary" />}
          <div className="min-w-0 flex-1">
            <span className="text-compact font-semibold text-content-primary">{rule.name}</span>
            <span className="ml-2 text-caption text-content-tertiary">{rule.rule_text.slice(0, 60)}{rule.rule_text.length > 60 ? '...' : ''}</span>
          </div>
        </button>

        <Badge color={rule.action === 'block' ? 'danger' : 'warning'} size="sm">
          {rule.action}
        </Badge>

        {rule.target_tools && rule.target_tools.length > 0 && (
          <span className="text-micro text-content-tertiary">
            {rule.target_tools.length} tool{rule.target_tools.length !== 1 ? 's' : ''}
          </span>
        )}

        <Toggle
          checked={rule.enabled}
          onChange={() => toggleEnabled.mutate()}
          disabled={toggleEnabled.isPending}
          size="sm"
        />
      </div>

      {/* Expanded */}
      {expanded && (
        <div className="border-t border-border-subtle px-5 pb-5 pt-4 space-y-4">
          {editing ? (
            <div className="space-y-4">
              <Input label="Name" value={editName} onChange={e => setEditName(e.target.value)} />
              <Textarea
                label="What should be prevented?"
                rows={3}
                value={editRuleText}
                onChange={e => setEditRuleText(e.target.value)}
              />
              <div className="flex gap-4">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="radio" name="action" value="block" checked={editAction === 'block'}
                    onChange={() => setEditAction('block')}
                    className="accent-red-500"
                  />
                  <span className="text-compact font-medium text-danger">Block</span>
                  <span className="text-caption text-content-tertiary">prevent the action</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="radio" name="action" value="warn" checked={editAction === 'warn'}
                    onChange={() => setEditAction('warn')}
                    className="accent-amber-500"
                  />
                  <span className="text-compact font-medium text-warning">Warn</span>
                  <span className="text-caption text-content-tertiary">allow but log</span>
                </label>
              </div>
              <ToolSelector selected={editTargetTools} onChange={setEditTargetTools} />
              <details className="text-caption text-content-tertiary">
                <summary className="cursor-pointer">Advanced: regex pattern</summary>
                <Input
                  value={editPattern}
                  onChange={e => setEditPattern(e.target.value)}
                  placeholder="Regex pattern (auto-generated if empty)"
                  className="mt-2 font-mono"
                />
              </details>
              <div className="flex items-center justify-end gap-2">
                <Button variant="ghost" size="sm" onClick={resetEdit} disabled={save.isPending}>Cancel</Button>
                <Button size="sm" onClick={() => save.mutate()} loading={save.isPending}
                  disabled={!editName.trim() || !editRuleText.trim()}>Save</Button>
              </div>
              {save.isError && <p className="text-caption text-danger">Save failed</p>}
            </div>
          ) : (
            <div className="space-y-3">
              <div>
                <p className="text-micro font-medium uppercase tracking-wider text-content-tertiary mb-1">What it prevents</p>
                <p className="text-compact text-content-secondary">{rule.rule_text}</p>
              </div>

              {rule.target_tools && rule.target_tools.length > 0 && (
                <div>
                  <p className="text-micro font-medium uppercase tracking-wider text-content-tertiary mb-1">Applies to</p>
                  <div className="flex flex-wrap gap-1">
                    {rule.target_tools.map(tool => (
                      <Badge key={tool} color="neutral" size="sm">{tool}</Badge>
                    ))}
                  </div>
                </div>
              )}

              {!rule.target_tools && (
                <div>
                  <p className="text-micro font-medium uppercase tracking-wider text-content-tertiary mb-1">Applies to</p>
                  <p className="text-caption text-content-tertiary">All tools</p>
                </div>
              )}

              {rule.pattern && (
                <details className="text-caption text-content-tertiary">
                  <summary className="cursor-pointer">Pattern</summary>
                  <code className="block mt-1 rounded-sm bg-surface-elevated border border-border-subtle px-3 py-2 font-mono text-caption text-content-primary">
                    {rule.pattern}
                  </code>
                </details>
              )}

              <div className="flex items-center justify-end gap-2 pt-2">
                {!rule.is_system && (
                  <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>Edit</Button>
                )}
                <Button
                  variant="danger" size="sm" icon={<Trash2 size={12} />}
                  onClick={() => onDelete(rule)} disabled={rule.is_system}
                >Delete</Button>
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  )
}

// ── Create rule modal ───────────────────────────────────────────────────────

function CreateRuleModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [ruleText, setRuleText] = useState('')
  const [action, setAction] = useState('block')
  const [targetTools, setTargetTools] = useState<string[]>([])
  const [pattern, setPattern] = useState('')

  const reset = () => {
    setName('')
    setRuleText('')
    setAction('block')
    setTargetTools([])
    setPattern('')
  }

  const create = useMutation({
    mutationFn: () =>
      createRule({
        name,
        rule_text: ruleText,
        enforcement: 'hard',
        action,
        target_tools: targetTools.length > 0 ? targetTools : null,
        pattern: pattern.trim() || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['rules'] })
      reset()
      onClose()
    },
  })

  return (
    <Modal open={open} onClose={onClose} title="New Rule" size="md"
      footer={<>
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button onClick={() => create.mutate()} loading={create.isPending}
          disabled={!name.trim() || !ruleText.trim()}>Create Rule</Button>
      </>}
    >
      <div className="space-y-4">
        <Input label="Name" value={name} onChange={e => setName(e.target.value)}
          placeholder="e.g. no-production-deletes" autoFocus />
        <Textarea label="What should be prevented?" rows={3} value={ruleText}
          onChange={e => setRuleText(e.target.value)}
          placeholder="Describe the constraint in plain language" />
        <div className="flex gap-4">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="radio" name="create-action" value="block" checked={action === 'block'}
              onChange={() => setAction('block')} className="accent-red-500" />
            <span className="text-compact font-medium text-danger">Block</span>
            <span className="text-caption text-content-tertiary">prevent the action</span>
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="radio" name="create-action" value="warn" checked={action === 'warn'}
              onChange={() => setAction('warn')} className="accent-amber-500" />
            <span className="text-compact font-medium text-warning">Warn</span>
            <span className="text-caption text-content-tertiary">allow but log</span>
          </label>
        </div>
        <ToolSelector selected={targetTools} onChange={setTargetTools} />
        <details className="text-caption text-content-tertiary">
          <summary className="cursor-pointer">Advanced: regex pattern</summary>
          <Input value={pattern} onChange={e => setPattern(e.target.value)}
            placeholder="Regex pattern (optional — Nova can help generate this)"
            className="mt-2 font-mono" />
        </details>
        {create.isError && <p className="text-caption text-danger">Failed to create rule</p>}
      </div>
    </Modal>
  )
}

// ── Help entries ─────────────────────────────────────────────────────────────

const HELP_ENTRIES = [
  { term: 'Rule', definition: 'A constraint on what agents can do. Rules check tool calls before execution and either block or warn.' },
  { term: 'Block vs Warn', definition: 'Block prevents the tool call entirely. Warn allows it but logs a warning for review.' },
  { term: 'Target Tools', definition: 'Which tools this rule applies to. Empty means all tools are checked.' },
  { term: 'System Rule', definition: 'Built-in rules that cannot be deleted. You can disable them if needed.' },
  { term: 'Chat', definition: 'You can ask Nova to create or modify rules in the Chat page. Say "create a rule that prevents X" and Nova will handle it.' },
]

// ── Rules body (shared between standalone page and Settings section) ────────

export function RulesContent() {
  const qc = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [deletingRule, setDeletingRule] = useState<Rule | null>(null)

  const { data: rules = [], isLoading, isFetching, isError } = useQuery({
    queryKey: ['rules'],
    queryFn: getRules,
    staleTime: 15_000,
  })

  const removeRule = useMutation({
    mutationFn: (ruleId: string) => deleteRule(ruleId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['rules'] })
      setDeletingRule(null)
    },
  })

  const active = rules.filter((r: Rule) => r.enabled)
  const system = rules.filter((r: Rule) => r.is_system)

  return (
    <div className="space-y-5">
      {/* Actions + metrics */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex flex-wrap gap-6">
          <Metric label="Total Rules" value={rules.length} icon={<ShieldAlert size={12} />} />
          <Metric label="Active" value={active.length} />
          <Metric label="System" value={system.length} />
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm"
            icon={<RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} />}
            onClick={() => qc.invalidateQueries({ queryKey: ['rules'] })}
            disabled={isFetching} />
          <Button size="sm" icon={<Plus size={14} />} onClick={() => setCreateOpen(true)}>New Rule</Button>
        </div>
      </div>

      {isLoading && (
        <div className="space-y-3">
          <Skeleton variant="rect" height="80px" />
          <Skeleton variant="rect" height="80px" />
        </div>
      )}

      {isError && (
        <Card variant="outlined" className="p-4">
          <p className="text-compact text-danger">Failed to load rules.</p>
        </Card>
      )}

      {!isLoading && rules.length > 0 && (
        <div className="space-y-2">
          {rules.map((rule: Rule) => (
            <RuleCard key={rule.id} rule={rule} onDelete={setDeletingRule} />
          ))}
        </div>
      )}

      {!isLoading && rules.length === 0 && (
        <EmptyState
          icon={ShieldAlert}
          title="No rules"
          description="Rules constrain agent behavior. Create one or ask Nova in Chat."
          action={{ label: 'Create Rule', onClick: () => setCreateOpen(true) }}
        />
      )}

      <CreateRuleModal open={createOpen} onClose={() => setCreateOpen(false)} />

      <ConfirmDialog
        open={!!deletingRule}
        onClose={() => setDeletingRule(null)}
        title="Delete Rule"
        description={`Delete "${deletingRule?.name}"? This cannot be undone.`}
        confirmLabel="Delete"
        onConfirm={() => deletingRule && removeRule.mutate(deletingRule.id)}
        destructive
        confirmText={deletingRule?.name}
      />
    </div>
  )
}

