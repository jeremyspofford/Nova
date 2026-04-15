import { Link } from "react-router-dom"
import { useShallow } from "zustand/react/shallow"
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
  const { theme, layoutMode, chatSide, setTheme, setLayoutMode, setChatSide } = useSettingsStore(
    useShallow(s => ({
      theme: s.theme,
      layoutMode: s.layoutMode,
      chatSide: s.chatSide,
      setTheme: s.setTheme,
      setLayoutMode: s.setLayoutMode,
      setChatSide: s.setChatSide,
    }))
  )

  return (
    <div className="settings-page">
      <Link to="/" className="settings-page__back">← Back to board</Link>
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
                { label: "Light", value: "light" },
                { label: "Dark",  value: "dark"  },
                { label: "System", value: "system" },
              ]}
              value={theme}
              onChange={setTheme}
            />
          </div>
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section__label">Layout</div>
        <div className="settings-group">
          <div className="settings-row">
            <div>
              <div className="settings-row__label">Mode</div>
              <div className="settings-row__desc">Side-by-side or full-screen tabs</div>
            </div>
            <SegControl
              options={[
                { label: "Split",  value: "split"  },
                { label: "Tabbed", value: "tabbed" },
              ]}
              value={layoutMode}
              onChange={setLayoutMode}
            />
          </div>

          <div className={`settings-row${layoutMode === "tabbed" ? " settings-row--dimmed" : ""}`}>
            <div>
              <div className="settings-row__label">Chat side</div>
              <div className="settings-row__desc">Which side of the split</div>
            </div>
            <SegControl
              options={[
                { label: "Left",  value: "left"  },
                { label: "Right", value: "right" },
              ]}
              value={chatSide}
              onChange={setChatSide}
            />
          </div>
        </div>
      </section>
    </div>
  )
}
