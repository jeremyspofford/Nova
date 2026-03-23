import React from 'react'
import { Palette, Moon, Sun, Monitor, Type } from 'lucide-react'
import { useTheme } from '../../stores/theme-store'
import { themePresets } from '../../lib/color-palettes'
import { Section, Button } from '../../components/ui'

/** Preview swatch: accent-700 color for each preset (used for the color dot) */
const PRESET_ACCENT_PREVIEW: Record<string, string> = {
  default:          'rgb(15 118 110)',
  ocean:            'rgb(29 78 216)',
  forest:           'rgb(4 120 87)',
  sunset:           'rgb(190 18 60)',
  nord:             'rgb(94 129 172)',
  'ctp-mocha':      'rgb(137 180 250)',
  'ctp-latte':      'rgb(30 102 245)',
  dracula:          'rgb(189 147 249)',
  'tokyo-night':    'rgb(122 162 247)',
  gruvbox:          'rgb(254 128 25)',
  'solarized-dark': 'rgb(42 161 152)',
  'one-dark':       'rgb(97 175 239)',
  custom:           'rgb(120 113 108)',
}

/** Preview swatch: neutral-900 background for each preset (dark bg preview) */
const PRESET_BG_PREVIEW: Record<string, string> = {
  default:          'rgb(28 25 23)',
  ocean:            'rgb(15 23 42)',
  forest:           'rgb(28 25 23)',
  sunset:           'rgb(24 24 27)',
  nord:             'rgb(46 52 64)',
  'ctp-mocha':      'rgb(30 30 46)',
  'ctp-latte':      'rgb(239 241 245)',
  dracula:          'rgb(40 42 54)',
  'tokyo-night':    'rgb(26 27 38)',
  gruvbox:          'rgb(40 40 40)',
  'solarized-dark': 'rgb(0 43 54)',
  'one-dark':       'rgb(40 44 52)',
  custom:           'rgb(28 25 23)',
}

const ACCENT_SWATCHES: Record<string, string> = {
  teal:    'rgb(15 118 110)',
  blue:    'rgb(29 78 216)',
  purple:  'rgb(126 34 206)',
  rose:    'rgb(190 18 60)',
  indigo:  'rgb(67 56 202)',
  cyan:    'rgb(14 116 144)',
  orange:  'rgb(194 65 12)',
  emerald: 'rgb(4 120 87)',
}

function PresetCard({ id, label, active, onClick }: {
  id: string; label: string; active: boolean; onClick: () => void
}) {
  const accent = PRESET_ACCENT_PREVIEW[id]
  const bg = PRESET_BG_PREVIEW[id]
  return (
    <button onClick={onClick} className={
      'group flex flex-col items-center gap-1.5 rounded-sm border p-2 text-micro font-medium transition-all ' +
      (active
        ? 'border-accent ring-2 ring-accent/30 text-accent'
        : 'border-border text-content-secondary hover:border-border-focus')
    }>
      <span className="relative flex h-6 w-full overflow-hidden rounded-xs border border-border-subtle">
        <span className="flex-1" style={{ background: bg }} />
        <span className="w-2" style={{ background: accent }} />
      </span>
      <span className="truncate max-w-full">{label}</span>
    </button>
  )
}

function AccentPicker({ activeAccent, onSelect }: {
  activeAccent: string
  onSelect: (name: string) => void
}) {
  return (
    <div className="mt-2">
      <label className="mb-1.5 block text-caption text-content-tertiary">Accent Color</label>
      <div className="flex flex-wrap gap-2">
        {Object.entries(ACCENT_SWATCHES).map(([name, color]) => (
          <button
            key={name}
            onClick={() => onSelect(name)}
            title={name}
            className={
              'size-8 rounded-full border-2 transition-transform hover:scale-110 ' +
              (activeAccent === name
                ? 'border-accent ring-2 ring-accent/30 scale-110'
                : 'border-border')
            }
            style={{ background: color }}
          />
        ))}
      </div>
    </div>
  )
}

const MODE_OPTIONS: { value: 'light' | 'system' | 'dark'; label: string; icon: React.ElementType }[] = [
  { value: 'light',  label: 'Light',  icon: Sun     },
  { value: 'system', label: 'System', icon: Monitor  },
  { value: 'dark',   label: 'Dark',   icon: Moon    },
]

const TIMEZONES = [
  'UTC',
  'US/Eastern', 'US/Central', 'US/Mountain', 'US/Pacific', 'US/Alaska', 'US/Hawaii',
  'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles',
  'America/Phoenix', 'America/Anchorage', 'America/Toronto', 'America/Vancouver',
  'America/Mexico_City', 'America/Sao_Paulo', 'America/Argentina/Buenos_Aires',
  'Europe/London', 'Europe/Paris', 'Europe/Berlin', 'Europe/Amsterdam',
  'Europe/Madrid', 'Europe/Rome', 'Europe/Zurich', 'Europe/Stockholm',
  'Europe/Moscow', 'Europe/Istanbul',
  'Asia/Tokyo', 'Asia/Seoul', 'Asia/Shanghai', 'Asia/Hong_Kong',
  'Asia/Singapore', 'Asia/Kolkata', 'Asia/Dubai', 'Asia/Bangkok',
  'Asia/Jakarta', 'Asia/Taipei',
  'Australia/Sydney', 'Australia/Melbourne', 'Australia/Perth',
  'Pacific/Auckland', 'Pacific/Honolulu',
  'Africa/Cairo', 'Africa/Johannesburg', 'Africa/Lagos',
]

const FONT_SCALE_OPTIONS = [
  { value: 0.85, label: 'S' },
  { value: 1,    label: 'M' },
  { value: 1.15, label: 'L' },
  { value: 1.3,  label: 'XL' },
]

export function AppearanceSection() {
  const {
    modePreference, setModePreference,
    lightPreset, setLightPreset,
    darkPreset, setDarkPreset,
    customLightAccent, setCustomLightAccent,
    customDarkAccent, setCustomDarkAccent,
    fontScale, setFontScale,
    timezone, setTimezone,
  } = useTheme()

  const allPresets = Object.entries(themePresets)

  return (
    <Section
      icon={Palette}
      title="Appearance"
      description="Configure the look and feel of this dashboard."
    >
      {/* Mode Preference */}
      <div>
        <label className="mb-2 block text-caption font-medium text-content-secondary">Mode</label>
        <div className="inline-flex rounded-sm border border-border p-0.5">
          {MODE_OPTIONS.map(({ value, label, icon: Icon }) => (
            <button
              key={value}
              onClick={() => setModePreference(value)}
              className={
                'flex items-center gap-1.5 rounded-xs px-3 py-1.5 text-caption font-medium transition-colors ' +
                (modePreference === value
                  ? 'bg-surface-elevated text-accent'
                  : 'text-content-tertiary hover:text-content-secondary')
              }
            >
              <Icon size={13} />
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Text Size */}
      <div>
        <label className="mb-2 block text-caption font-medium text-content-secondary">Text Size</label>
        <div className="inline-flex rounded-sm border border-border p-0.5">
          {FONT_SCALE_OPTIONS.map(({ value, label }) => (
            <button
              key={value}
              onClick={() => setFontScale(value)}
              className={
                'flex items-center gap-1.5 rounded-xs px-3 py-1.5 text-caption font-medium transition-colors ' +
                (fontScale === value
                  ? 'bg-surface-elevated text-accent'
                  : 'text-content-tertiary hover:text-content-secondary')
              }
            >
              <Type size={value === 0.85 ? 11 : value === 1 ? 13 : value === 1.15 ? 15 : 17} />
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Timezone */}
      <div>
        <label className="mb-2 block text-caption font-medium text-content-secondary">Timezone</label>
        <select
          value={timezone}
          onChange={e => setTimezone(e.target.value)}
          className="h-9 rounded-sm border border-border bg-surface-input px-3 text-compact text-content-primary outline-none transition-colors duration-fast focus:border-border-focus focus:ring-2 focus:ring-accent-500/40"
        >
          {TIMEZONES.map(tz => (
            <option key={tz} value={tz}>{tz.replace(/_/g, ' ')}</option>
          ))}
        </select>
      </div>

      {/* Light Theme */}
      <div>
        <label className="mb-2 block text-caption font-medium text-content-secondary">Light Theme</label>
        <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
          {allPresets.map(([key, p]) => (
            <PresetCard key={key} id={key} label={p.label} active={lightPreset === key} onClick={() => setLightPreset(key)} />
          ))}
        </div>
        {lightPreset === 'custom' && (
          <AccentPicker activeAccent={customLightAccent} onSelect={setCustomLightAccent} />
        )}
      </div>

      {/* Dark Theme */}
      <div>
        <label className="mb-2 block text-caption font-medium text-content-secondary">Dark Theme</label>
        <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
          {allPresets.map(([key, p]) => (
            <PresetCard key={key} id={key} label={p.label} active={darkPreset === key} onClick={() => setDarkPreset(key)} />
          ))}
        </div>
        {darkPreset === 'custom' && (
          <AccentPicker activeAccent={customDarkAccent} onSelect={setCustomDarkAccent} />
        )}
      </div>
    </Section>
  )
}
