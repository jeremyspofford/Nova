import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Wrench, RotateCcw, AlertTriangle } from 'lucide-react'
import { getToolPermissions, updateToolPermissions, type ToolGroupStatus } from '../../api'
import { Section, Toggle, Badge, Button, Skeleton } from '../../components/ui'

export function ToolPermissionsSection() {
  const qc = useQueryClient()

  const { data: groups, isLoading } = useQuery({
    queryKey: ['tool-permissions'],
    queryFn: getToolPermissions,
    staleTime: 30_000,
  })

  const mutation = useMutation({
    mutationFn: (update: Record<string, boolean>) => updateToolPermissions(update),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['tool-permissions'] })
    },
  })

  const handleToggle = (name: string, enabled: boolean) => {
    mutation.mutate({ [name]: enabled })
  }

  const handleResetAll = () => {
    if (!groups) return
    const update: Record<string, boolean> = {}
    for (const g of groups) {
      if (!g.enabled) update[g.name] = true
    }
    if (Object.keys(update).length > 0) {
      mutation.mutate(update)
    }
  }

  const hasDisabled = groups?.some(g => !g.enabled) ?? false
  const allDisabled = groups?.every(g => !g.enabled) ?? false
  const builtinGroups = groups?.filter(g => !g.is_mcp) ?? []
  const mcpGroups = groups?.filter(g => g.is_mcp) ?? []

  return (
    <Section
      icon={Wrench}
      title="Tool Permissions"
      description="Control which tool capabilities Nova can use. Disabled groups are removed from the LLM's tool list and system prompt. Individual pods can further restrict tools in their pod settings."
    >
      {isLoading ? (
        <Skeleton lines={4} />
      ) : (
        <div role="list" aria-label="Tool permission groups" className="space-y-3">
          {/* All-disabled warning */}
          {allDisabled && (
            <div
              role="alert"
              aria-live="assertive"
              className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-caption text-amber-700 dark:text-amber-400"
            >
              <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              <span>
                All tool groups are disabled. Nova can only respond with text — no file access, web search, or shell commands.
              </span>
            </div>
          )}

          {/* Built-in groups */}
          {builtinGroups.map(g => (
            <ToolGroupRow
              key={g.name}
              group={g}
              onToggle={handleToggle}
              saving={mutation.isPending}
            />
          ))}

          {/* MCP groups */}
          {mcpGroups.length > 0 && (
            <>
              <div className="border-t border-border-subtle pt-3">
                <p className="text-micro font-semibold uppercase tracking-wider text-content-tertiary mb-2">
                  MCP Servers
                </p>
              </div>
              {mcpGroups.map(g => (
                <ToolGroupRow
                  key={g.name}
                  group={g}
                  onToggle={handleToggle}
                  saving={mutation.isPending}
                />
              ))}
            </>
          )}

          {/* Reset all */}
          {hasDisabled && (
            <div className="border-t border-border-subtle pt-3">
              <Button
                variant="ghost"
                size="sm"
                onClick={handleResetAll}
                loading={mutation.isPending}
                icon={<RotateCcw size={12} />}
              >
                Reset to defaults (enable all)
              </Button>
            </div>
          )}

          {/* Effect timing hint */}
          <p className="text-micro text-content-tertiary">
            Changes apply to new messages — no restart required.
          </p>
        </div>
      )}

      {mutation.isError && (
        <p className="mt-2 text-caption text-danger" aria-live="polite">
          {String(mutation.error)}
        </p>
      )}
    </Section>
  )
}

function ToolGroupRow({
  group,
  onToggle,
  saving,
}: {
  group: ToolGroupStatus
  onToggle: (name: string, enabled: boolean) => void
  saving: boolean
}) {
  const descId = `tool-desc-${group.name.replace(/\s+/g, '-').toLowerCase()}`
  return (
    <div role="listitem" className="flex items-center justify-between gap-4 py-1">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-compact font-medium text-content-primary">
            {group.display_name}
          </span>
          <Badge color="neutral" size="sm">
            {group.tool_count} tool{group.tool_count !== 1 ? 's' : ''}
          </Badge>
        </div>
        <p id={descId} className="text-caption text-content-tertiary mt-0.5 truncate sm:whitespace-normal">
          {group.description}
        </p>
      </div>
      <Toggle
        checked={group.enabled}
        onChange={() => onToggle(group.name, !group.enabled)}
        disabled={saving}
        size="sm"
        aria-label={group.enabled ? `Disable ${group.display_name} tools` : `Enable ${group.display_name} tools`}
        aria-describedby={descId}
      />
    </div>
  )
}
