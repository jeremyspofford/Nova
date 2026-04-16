import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { useSettingsStore } from "../../stores/settingsStore"
import { getModels, setLocalModel } from "../../api/llm"

type SegOption<T extends string> = { label: string; value: T }

function SegControl<T extends string>({
  options,
  value,
  onChange,
}: {
  options: SegOption<T>[]
  value: T
  onChange: (v: T) => void
}) {
  return (
    <div className="seg-control">
      {options.map(opt => (
        <button
          key={opt.value}
          className={`seg-control__btn${value === opt.value ? " seg-control__btn--active" : ""}`}
          onClick={() => onChange(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

export function Settings() {
  const { theme, setTheme } = useSettingsStore()
  const [models, setModels] = useState<string[]>([])
  const [activeModel, setActiveModel] = useState<string>("")
  const [modelStatus, setModelStatus] = useState<"idle" | "saving" | "saved" | "error">("idle")

  useEffect(() => {
    getModels()
      .then(data => setModels(data.models))
      .catch(() => setModels([]))
  }, [])

  async function handleModelChange(model: string) {
    setModelStatus("saving")
    try {
      const result = await setLocalModel(model)
      setActiveModel(result.model_ref)
      setModelStatus("saved")
      setTimeout(() => setModelStatus("idle"), 2000)
    } catch {
      setModelStatus("error")
      setTimeout(() => setModelStatus("idle"), 3000)
    }
  }

  return (
    <div className="settings-page">
      <Link to="/" className="settings-page__back">← Back</Link>
      <h1 className="settings-page__title">Settings</h1>

      <section className="settings-section">
        <div className="settings-section__label">Appearance</div>
        <div className="settings-group">
          <div className="settings-row">
            <div>
              <div className="settings-row__label">Theme</div>
              <div className="settings-row__desc">Override your system setting</div>
            </div>
            <SegControl
              options={[
                { label: "Light",  value: "light"  },
                { label: "Dark",   value: "dark"   },
                { label: "System", value: "system" },
              ]}
              value={theme}
              onChange={setTheme}
            />
          </div>
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section__label">Model</div>
        <div className="settings-group">
          {models.length === 0 ? (
            <div className="settings-row settings-row--dimmed">
              <div>
                <div className="settings-row__label">Ollama model</div>
                <div className="settings-row__desc">No models found — is Ollama running?</div>
              </div>
            </div>
          ) : (
            <div className="settings-row">
              <div>
                <div className="settings-row__label">Ollama model</div>
                <div className="settings-row__desc">
                  {modelStatus === "saved" && "Saved"}
                  {modelStatus === "saving" && "Saving..."}
                  {modelStatus === "error" && "Failed to save"}
                  {modelStatus === "idle" && "Select the model Nova uses for chat"}
                </div>
              </div>
              <select
                className="settings-model-select"
                value={activeModel}
                onChange={e => handleModelChange(e.target.value)}
              >
                <option value="" disabled>Pick a model</option>
                {models.map(m => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
