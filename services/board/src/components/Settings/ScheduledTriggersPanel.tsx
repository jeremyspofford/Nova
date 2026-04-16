import { useEffect, useState } from "react"
import { getTriggers, type Trigger } from "../../api/triggers"
import { cronToHuman } from "../../lib/cron-to-nl"

export function ScheduledTriggersPanel() {
  const [triggers, setTriggers] = useState<Trigger[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    getTriggers()
      .then(data => {
        setTriggers(data.triggers)
        setLoading(false)
      })
      .catch(() => {
        setError(true)
        setLoading(false)
      })
  }, [])

  if (loading) return <section><h3>Scheduled Triggers</h3><p>Loading…</p></section>
  if (error) return <section><h3>Scheduled Triggers</h3><p>Failed to load triggers.</p></section>

  return (
    <section className="triggers-panel">
      <h3>Scheduled Triggers</h3>
      {triggers.length === 0 ? (
        <p>No triggers configured.</p>
      ) : (
        <ul className="triggers-panel__list">
          {triggers.map(t => {
            const p = t.payload_template || {}
            const kind = "tool" in p ? "tool" : "goal"
            const payloadLabel = kind === "tool"
              ? `runs: ${String((p as Record<string, unknown>).tool)}`
              : `goal: ${String((p as Record<string, unknown>).goal)}`
            return (
              <li key={t.id} className="triggers-panel__item">
                <div className="triggers-panel__name"><strong>{t.name}</strong></div>
                <div className="triggers-panel__schedule">
                  {cronToHuman(t.cron_expression)} · {t.enabled ? "enabled" : "disabled"}
                </div>
                <div className="triggers-panel__payload">{payloadLabel}</div>
                {t.last_fired_at && (
                  <div className="triggers-panel__fired">
                    last fired: {new Date(t.last_fired_at).toLocaleString()}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
      <p className="triggers-panel__hint"><em>To add, edit, or remove triggers, ask Nova in chat.</em></p>
    </section>
  )
}
