import { Link } from "react-router-dom"
import { useSettingsStore } from "../../stores/settingsStore"

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
    </div>
  )
}
