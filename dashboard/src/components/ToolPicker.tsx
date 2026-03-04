import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Search, Loader2 } from 'lucide-react'
import clsx from 'clsx'
import { getAvailableTools } from '../api'
import type { ToolCategory } from '../api'

interface ToolPickerProps {
  selectedTools: string[] | null
  onChange: (tools: string[] | null) => void
}

export function ToolPicker({ selectedTools, onChange }: ToolPickerProps) {
  const [search, setSearch] = useState('')
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})

  const { data: categories = [], isLoading, isError } = useQuery({
    queryKey: ['available-tools'],
    queryFn: getAvailableTools,
    staleTime: 60_000,
  })

  const allToolNames = categories.flatMap(c => c.tools.map(t => t.name))

  const toggleAllowAll = () => {
    if (selectedTools === null) {
      // Switching to restricted — pre-select ALL tools
      onChange([...allToolNames])
    } else {
      onChange(null)
    }
  }

  const isSelected = (name: string) => selectedTools?.includes(name) ?? false

  const toggleTool = (name: string) => {
    if (selectedTools === null) return
    if (selectedTools.includes(name)) {
      onChange(selectedTools.filter(t => t !== name))
    } else {
      onChange([...selectedTools, name])
    }
  }

  const toggleCategory = (cat: ToolCategory) => {
    if (selectedTools === null) return
    const catNames = cat.tools.map(t => t.name)
    const allSelected = catNames.every(n => selectedTools.includes(n))
    if (allSelected) {
      onChange(selectedTools.filter(t => !catNames.includes(t)))
    } else {
      const merged = new Set([...selectedTools, ...catNames])
      onChange([...merged])
    }
  }

  const toggleCollapse = (category: string) =>
    setCollapsed(prev => ({ ...prev, [category]: !prev[category] }))

  const lowerSearch = search.toLowerCase()

  const filteredCategories = categories
    .map(cat => ({
      ...cat,
      tools: cat.tools.filter(
        t =>
          t.name.toLowerCase().includes(lowerSearch) ||
          t.description.toLowerCase().includes(lowerSearch),
      ),
    }))
    .filter(cat => cat.tools.length > 0)

  return (
    <div className="space-y-2">
      {/* Allow-all toggle */}
      <div className="flex items-center justify-between">
        <label className="text-[10px] font-medium uppercase tracking-wide text-neutral-500 dark:text-neutral-400">
          Allowed Tools
        </label>
        <button
          onClick={toggleAllowAll}
          className="text-[10px] text-accent-700 dark:text-accent-400 hover:underline"
        >
          {selectedTools === null ? 'Restrict to list' : 'Allow all tools'}
        </button>
      </div>

      {selectedTools === null ? (
        <p className="text-xs italic text-neutral-500 dark:text-neutral-400">
          All tools allowed (no restriction)
        </p>
      ) : isLoading ? (
        <div className="flex items-center gap-2 py-3 text-xs text-neutral-500 dark:text-neutral-400">
          <Loader2 size={12} className="animate-spin" /> Loading tools…
        </div>
      ) : isError ? (
        <p className="text-xs text-red-600 dark:text-red-400">
          Failed to load tools — check orchestrator connectivity
        </p>
      ) : (
        <div className="space-y-2">
          {/* Search */}
          <div className="relative">
            <Search
              size={12}
              className="absolute left-2 top-1/2 -translate-y-1/2 text-neutral-400 dark:text-neutral-500"
            />
            <input
              type="text"
              placeholder="Filter tools…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-card dark:bg-neutral-900 pl-7 pr-2 py-1.5 text-xs text-neutral-800 dark:text-neutral-200 outline-none focus:border-accent-600 placeholder:text-neutral-400 dark:placeholder:text-neutral-500"
            />
          </div>

          {/* Categories */}
          <div className="max-h-64 overflow-y-auto space-y-1 rounded-md border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800/50 p-1.5">
            {filteredCategories.map(cat => {
              const catNames = cat.tools.map(t => t.name)
              const selectedCount = catNames.filter(n => selectedTools.includes(n)).length
              const isCollapsed = collapsed[cat.category] ?? false
              const allSelected = selectedCount === cat.tools.length

              return (
                <div key={cat.category}>
                  {/* Category header */}
                  <div className="flex items-center gap-1.5 rounded px-1.5 py-1 hover:bg-neutral-100 dark:hover:bg-neutral-700/50">
                    <button
                      onClick={() => toggleCollapse(cat.category)}
                      className="flex flex-1 items-center gap-1.5 text-left"
                    >
                      <span className="text-neutral-500 dark:text-neutral-400">
                        {isCollapsed ? <ChevronRight size={11} /> : <ChevronDown size={11} />}
                      </span>
                      <span className="text-[11px] font-semibold text-neutral-700 dark:text-neutral-300">
                        {cat.category}
                      </span>
                      <span className="text-[10px] text-neutral-500 dark:text-neutral-400">
                        {selectedCount}/{cat.tools.length}
                      </span>
                      {cat.source === 'mcp' && (
                        <span className="rounded bg-violet-100 dark:bg-violet-900/30 px-1 py-px text-[9px] font-medium text-violet-600 dark:text-violet-400">
                          MCP
                        </span>
                      )}
                    </button>
                    <button
                      onClick={() => toggleCategory(cat)}
                      className="text-[10px] text-accent-700 dark:text-accent-400 hover:underline whitespace-nowrap"
                    >
                      {allSelected ? 'deselect all' : 'select all'}
                    </button>
                  </div>

                  {/* Tool rows */}
                  {!isCollapsed &&
                    cat.tools.map(tool => (
                      <label
                        key={tool.name}
                        className="flex items-start gap-2 rounded px-1.5 py-1 ml-3 cursor-pointer hover:bg-neutral-100 dark:hover:bg-neutral-700/50"
                      >
                        <input
                          type="checkbox"
                          checked={isSelected(tool.name)}
                          onChange={() => toggleTool(tool.name)}
                          className="mt-0.5 accent-accent-700"
                        />
                        <div className="min-w-0 flex-1">
                          <span className="font-mono text-[11px] text-neutral-800 dark:text-neutral-200">
                            {tool.name}
                          </span>
                          <p className="truncate text-[10px] text-neutral-500 dark:text-neutral-400 leading-tight">
                            {tool.description}
                          </p>
                        </div>
                      </label>
                    ))}
                </div>
              )
            })}

            {filteredCategories.length === 0 && (
              <p className="py-3 text-center text-xs text-neutral-500 dark:text-neutral-400">
                {categories.length === 0
                  ? 'No tools available — is the orchestrator running?'
                  : `No tools match "${search}"`}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
