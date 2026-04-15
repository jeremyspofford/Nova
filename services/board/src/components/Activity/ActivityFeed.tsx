import { useState, useEffect } from "react"
import { getActivity } from "../../api/activity"
import type { ActivityEntry } from "../../api/types"

function relativeTime(iso: string): string {
  const diffMin = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (diffMin < 1) return "just now"
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  return `${Math.floor(diffHr / 24)}d ago`
}

function EntryRow({ entry }: { entry: ActivityEntry }) {
  const [expanded, setExpanded] = useState(false)
  const isTruncated = entry.output?.endsWith("... [truncated]") ?? false

  return (
    <div className={`activity-entry activity-entry--${entry.status}`}>
      <div className="activity-entry__row">
        <span className="activity-entry__dot" />
        <span className="activity-entry__name">{entry.tool_name}</span>
        <span className="activity-entry__badge">{entry.trigger_type}</span>
        <span className="activity-entry__status">{entry.status}</span>
        <span className="activity-entry__time">
          {entry.started_at ? relativeTime(entry.started_at) : ""}
        </span>
      </div>

      {entry.summary && (
        <div className="activity-entry__summary">{entry.summary}</div>
      )}

      <button
        className="activity-entry__details-toggle"
        onClick={() => setExpanded(e => !e)}
        aria-label={expanded ? "hide details" : "show details"}
      >
        {expanded ? "▼ Details" : "▶ Details"}
      </button>

      {expanded && (
        <div className="activity-entry__details">
          <div className="activity-entry__detail-row">
            <span className="activity-entry__detail-label">Input</span>
            <pre className="activity-entry__detail-value">
              {entry.input ? JSON.stringify(entry.input, null, 2) : "—"}
            </pre>
          </div>
          <div className="activity-entry__detail-row">
            <span className="activity-entry__detail-label">Output</span>
            <pre className="activity-entry__detail-value">
              {isTruncated
                ? entry.output!.replace(/\.\.\. \[truncated\]$/, "...")
                : (entry.output ?? "—")}
              {isTruncated && <span className="activity-entry__truncated"> (truncated)</span>}
            </pre>
          </div>
          {entry.error && (
            <div className="activity-entry__detail-row">
              <span className="activity-entry__detail-label">Error</span>
              <pre className="activity-entry__detail-value activity-entry__detail-value--error">
                {entry.error}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function ActivityFeed() {
  const [entries, setEntries] = useState<ActivityEntry[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [fetchError, setFetchError] = useState<string | null>(null)

  async function load(offset: number, append: boolean) {
    setLoading(true)
    setFetchError(null)
    try {
      const data = await getActivity(50, offset)
      setTotal(data.total)
      setEntries(prev => append ? [...prev, ...data.entries] : data.entries)
    } catch {
      setFetchError("Failed to load activity.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load(0, false) }, [])

  return (
    <div className="activity-feed">
      <div className="activity-feed__header">
        <span className="activity-feed__title">Activity</span>
        <button
          className="activity-feed__refresh"
          onClick={() => load(0, false)}
          disabled={loading}
          aria-label="Refresh"
        >
          ↺ Refresh
        </button>
      </div>

      {fetchError && (
        <div className="activity-feed__error">
          {fetchError}
          <button onClick={() => load(0, false)}>Retry</button>
        </div>
      )}

      {!loading && entries.length === 0 && !fetchError && (
        <div className="activity-feed__empty">No activity yet.</div>
      )}

      <div className="activity-feed__list">
        {entries.map(e => <EntryRow key={e.id} entry={e} />)}
      </div>

      {entries.length < total && (
        <button
          className="activity-feed__load-more"
          onClick={() => load(entries.length, true)}
          disabled={loading}
          aria-label="Load more"
        >
          {loading ? "Loading..." : "Load more"}
        </button>
      )}
    </div>
  )
}
