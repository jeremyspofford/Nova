import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Plus, RefreshCw, ChevronDown, ChevronRight, Trash2, Lock, Wand2, Pencil,
} from 'lucide-react'
import clsx from 'clsx'
import { getSkills, createSkill, updateSkill, deleteSkill } from '../api'
import { PageHeader } from '../components/layout/PageHeader'
import {
  Card, Badge, Toggle, Metric, Button, Input, Textarea, Select, Modal, ConfirmDialog,
  EmptyState, Skeleton,
} from '../components/ui'

// ── Category badge colors ───────────────────────────────────────────────────

const CATEGORY_BADGE_COLOR: Record<string, 'accent' | 'info' | 'warning' | 'danger' | 'neutral' | 'success'> = {
  workflow: 'accent',
  coding:   'info',
  review:   'success',
  safety:   'danger',
  custom:   'neutral',
}

const CATEGORY_OPTIONS = [
  { value: 'workflow', label: 'Workflow' },
  { value: 'coding',  label: 'Coding' },
  { value: 'review',  label: 'Review' },
  { value: 'safety',  label: 'Safety' },
  { value: 'custom',  label: 'Custom' },
]

// ── Skill card ──────────────────────────────────────────────────────────────

function SkillCard({
  skill,
  onDelete,
}: {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  skill: any
  onDelete: (skill: any) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [editing, setEditing] = useState(false)
  const qc = useQueryClient()

  // Edit state
  const [editName, setEditName] = useState(skill.name)
  const [editDesc, setEditDesc] = useState(skill.description ?? '')
  const [editContent, setEditContent] = useState(skill.content ?? '')
  const [editCategory, setEditCategory] = useState(skill.category ?? 'custom')
  const [editPriority, setEditPriority] = useState(String(skill.priority ?? 0))

  const toggleEnabled = useMutation({
    mutationFn: () => updateSkill(skill.id, { enabled: !skill.enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['skills'] }),
  })

  const save = useMutation({
    mutationFn: () => updateSkill(skill.id, {
      name: editName,
      description: editDesc || null,
      content: editContent,
      category: editCategory,
      priority: parseInt(editPriority) || 0,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['skills'] })
      setEditing(false)
    },
  })

  const cancelEdit = () => {
    setEditName(skill.name)
    setEditDesc(skill.description ?? '')
    setEditContent(skill.content ?? '')
    setEditCategory(skill.category ?? 'custom')
    setEditPriority(String(skill.priority ?? 0))
    setEditing(false)
  }

  const isSystem = skill.is_system === true

  return (
    <Card
      variant={skill.enabled ? 'default' : 'outlined'}
      className={clsx(!skill.enabled && 'opacity-60')}
    >
      {/* Collapsed header */}
      <div className="flex items-center gap-3 px-5 py-4">
        <button
          onClick={() => setExpanded(e => !e)}
          className="flex shrink-0 items-center gap-3 min-w-0 flex-1 text-left"
        >
          <span className="shrink-0 text-content-tertiary">
            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </span>

          {isSystem && (
            <Lock size={14} className="shrink-0 text-content-tertiary" />
          )}

          <div className="min-w-0 flex-1">
            <span className="text-compact font-semibold text-content-primary">{skill.name}</span>
            {skill.description && (
              <p className="truncate text-caption text-content-secondary mt-0.5">{skill.description}</p>
            )}
          </div>
        </button>

        {/* Category badge */}
        <Badge
          color={CATEGORY_BADGE_COLOR[skill.category] ?? 'neutral'}
          size="sm"
        >
          {skill.category ?? 'custom'}
        </Badge>

        {/* Scope badge */}
        {skill.scope && (
          <Badge color="neutral" size="sm">
            {skill.scope}
          </Badge>
        )}

        {/* Priority */}
        <span className="hidden text-caption text-content-tertiary sm:inline tabular-nums">
          pri {skill.priority ?? 0}
        </span>

        {/* Enable toggle */}
        <Toggle
          checked={skill.enabled !== false}
          onChange={() => toggleEnabled.mutate()}
          disabled={toggleEnabled.isPending}
          size="sm"
        />
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="border-t border-border-subtle px-5 pb-5 pt-4 space-y-4">
          {editing ? (
            <div className="space-y-4">
              <Input
                label="Name"
                value={editName}
                onChange={e => setEditName(e.target.value)}
                autoFocus
              />
              <Input
                label="Description"
                value={editDesc}
                onChange={e => setEditDesc(e.target.value)}
                placeholder="Brief description of this skill..."
              />
              <div>
                <label className="block text-caption font-medium text-content-secondary mb-1">Content</label>
                <Textarea
                  rows={8}
                  value={editContent}
                  onChange={e => setEditContent(e.target.value)}
                  placeholder="Prompt template content..."
                  autoResize={false}
                />
                <span className="text-micro text-content-tertiary">{editContent.length} chars</span>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Select
                  label="Category"
                  value={editCategory}
                  onChange={e => setEditCategory(e.target.value)}
                  items={CATEGORY_OPTIONS}
                />
                <Input
                  label="Priority"
                  type="number"
                  min="0"
                  value={editPriority}
                  onChange={e => setEditPriority(e.target.value)}
                />
              </div>
              <div className="flex items-center justify-end gap-2">
                <Button variant="ghost" size="sm" onClick={cancelEdit} disabled={save.isPending}>Cancel</Button>
                <Button size="sm" onClick={() => save.mutate()} loading={save.isPending}>Save</Button>
              </div>
              {save.isError && (
                <p className="text-caption text-danger">Save failed -- check console</p>
              )}
            </div>
          ) : (
            <>
              {/* Content display */}
              {skill.content ? (
                <div>
                  <p className="text-micro font-medium uppercase tracking-wider text-content-tertiary mb-1.5">Content</p>
                  <pre className="max-h-60 overflow-y-auto whitespace-pre-wrap break-words rounded-sm bg-surface-elevated border border-border-subtle px-3 py-2 font-mono text-caption text-content-secondary leading-relaxed">
                    {skill.content}
                  </pre>
                </div>
              ) : (
                <p className="text-caption italic text-content-tertiary">No content defined</p>
              )}

              {/* Actions */}
              <div className="flex items-center justify-end gap-2 pt-2">
                {!isSystem && (
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<Pencil size={12} />}
                    onClick={() => setEditing(true)}
                  >
                    Edit
                  </Button>
                )}
                <Button
                  variant="danger"
                  size="sm"
                  icon={<Trash2 size={12} />}
                  onClick={() => onDelete(skill)}
                  disabled={isSystem}
                >
                  Delete
                </Button>
              </div>
            </>
          )}
        </div>
      )}
    </Card>
  )
}

// ── Create skill modal ──────────────────────────────────────────────────────

function CreateSkillModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [content, setContent] = useState('')
  const [category, setCategory] = useState('custom')
  const [priority, setPriority] = useState('0')

  const create = useMutation({
    mutationFn: () => createSkill({
      name,
      description: description || null,
      content,
      category,
      priority: parseInt(priority) || 0,
      enabled: true,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['skills'] })
      setName('')
      setDescription('')
      setContent('')
      setCategory('custom')
      setPriority('0')
      onClose()
    },
  })

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="New Skill"
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button
            onClick={() => create.mutate()}
            loading={create.isPending}
            disabled={!name.trim() || !content.trim()}
          >
            Create Skill
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Input
          label="Name"
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="e.g. Code Review Checklist"
          autoFocus
        />
        <Input
          label="Description"
          value={description}
          onChange={e => setDescription(e.target.value)}
          placeholder="What this skill does..."
        />
        <div>
          <label className="block text-caption font-medium text-content-secondary mb-1">Content</label>
          <Textarea
            rows={6}
            value={content}
            onChange={e => setContent(e.target.value)}
            placeholder="Prompt template content..."
            autoResize={false}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Select
            label="Category"
            value={category}
            onChange={e => setCategory(e.target.value)}
            items={CATEGORY_OPTIONS}
          />
          <Input
            label="Priority"
            type="number"
            min="0"
            value={priority}
            onChange={e => setPriority(e.target.value)}
          />
        </div>
        {create.isError && (
          <p className="text-caption text-danger">Failed to create skill</p>
        )}
      </div>
    </Modal>
  )
}

// ── Help entries ────────────────────────────────────────────────────────────

const HELP_ENTRIES = [
  { term: 'Skill', definition: 'A reusable prompt template that gets injected into agent conversations. Skills give agents specialized capabilities and knowledge.' },
  { term: 'Scope', definition: 'Controls when a skill is active: global (always), pod-specific, or agent-specific. Narrower scopes override broader ones.' },
  { term: 'Priority', definition: 'Skills are injected in priority order (lowest number first). Higher-priority skills appear earlier in the agent context.' },
  { term: 'Category', definition: 'Organizational grouping: workflow (process), coding (development), review (quality), safety (guardrails), custom (user-defined).' },
  { term: 'System Skills', definition: 'Built-in skills marked with a lock icon. These cannot be deleted but can be disabled.' },
]

// ── Main page ───────────────────────────────────────────────────────────────

export function Skills() {
  const qc = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [deletingSkill, setDeletingSkill] = useState<any | null>(null)

  const { data: skills = [], isLoading, isFetching, isError } = useQuery({
    queryKey: ['skills'],
    queryFn: getSkills,
    staleTime: 15_000,
  })

  const removeSkill = useMutation({
    mutationFn: (id: string) => deleteSkill(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['skills'] })
      setDeletingSkill(null)
    },
  })

  const activeCount = skills.filter((s: any) => s.enabled !== false).length

  return (
    <div className="space-y-6 px-4 py-6 sm:px-6">
      <PageHeader
        title="Skills"
        description="Reusable prompt templates injected into agent conversations."
        helpEntries={HELP_ENTRIES}
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              icon={<RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} />}
              onClick={() => qc.invalidateQueries({ queryKey: ['skills'] })}
              disabled={isFetching}
            />
            <Button
              icon={<Plus size={14} />}
              onClick={() => setCreateOpen(true)}
            >
              New Skill
            </Button>
          </div>
        }
      />

      {/* Metrics row */}
      <div className="flex flex-wrap gap-6">
        <Metric label="Total Skills" value={skills.length} icon={<Wand2 size={12} />} />
        <Metric label="Active" value={activeCount} />
      </div>

      {isLoading && (
        <div className="space-y-3">
          <Skeleton variant="rect" height="80px" />
          <Skeleton variant="rect" height="80px" />
        </div>
      )}

      {isError && (
        <Card variant="outlined" className="p-4">
          <p className="text-compact text-danger">
            Failed to load skills -- check your admin secret and API connectivity.
          </p>
        </Card>
      )}

      {/* Skill cards */}
      {!isLoading && skills.length > 0 && (
        <div className="space-y-2">
          {skills
            .sort((a: any, b: any) => (a.priority ?? 0) - (b.priority ?? 0))
            .map((skill: any) => (
              <SkillCard key={skill.id} skill={skill} onDelete={setDeletingSkill} />
            ))}
        </div>
      )}

      {!isLoading && skills.length === 0 && (
        <EmptyState
          icon={Wand2}
          title="No skills found"
          description="Skills are reusable prompt templates injected into agent conversations. Create one to get started."
          action={{ label: 'Create Skill', onClick: () => setCreateOpen(true) }}
        />
      )}

      {/* Create modal */}
      <CreateSkillModal open={createOpen} onClose={() => setCreateOpen(false)} />

      {/* Delete confirm */}
      <ConfirmDialog
        open={!!deletingSkill}
        onClose={() => setDeletingSkill(null)}
        title="Delete Skill"
        description={`Are you sure you want to delete "${deletingSkill?.name}"? This action cannot be undone.`}
        confirmLabel="Delete"
        onConfirm={() => deletingSkill && removeSkill.mutate(deletingSkill.id)}
        destructive
        confirmText={deletingSkill?.name}
      />
    </div>
  )
}
