import { Target } from 'lucide-react'
import { Section } from '../../components/ui'
import { ConfigField, useConfigValue, type ConfigSectionProps } from './shared'
import { useLocalStorage } from '../../hooks/useLocalStorage'

const AUTONOMY_OPTIONS = [
  { value: 'auto_all', label: 'Full autonomy', description: 'Nova creates tasks and goals without asking' },
  { value: 'auto_tasks', label: 'Tasks autonomous', description: 'Nova auto-creates tasks, confirms goals with you first' },
  { value: 'auto_goals', label: 'Goals autonomous', description: 'Nova auto-creates goals, confirms tasks with you first' },
  { value: 'confirm_all', label: 'Always confirm', description: 'Nova confirms before creating anything' },
]

export function GoalCreationSection({ entries, onSave, saving }: ConfigSectionProps) {
  const autonomy = useConfigValue(entries, 'creation.autonomy', 'auto_tasks')
  const [directCreation, setDirectCreation] = useLocalStorage('goals.directCreation', false)

  return (
    <Section
      icon={Target}
      title="Goal & Task Creation"
      description="Control how Nova creates goals and tasks on your behalf"
      id="goal-creation"
    >
      <ConfigField
        label="Nova creation autonomy"
        configKey="creation.autonomy"
        value={autonomy}
        description="What Nova can create without asking you first"
        onSave={onSave}
        saving={saving}
      />
      <p className="text-micro text-content-tertiary -mt-2 mb-2">
        {AUTONOMY_OPTIONS.find(o => o.value === autonomy)?.description}
      </p>
      <p className="text-micro text-content-tertiary mb-3">
        Valid values: {AUTONOMY_OPTIONS.map(o => o.value).join(', ')}
      </p>

      <div>
        <label className="text-caption font-medium text-content-secondary mb-1.5 block">
          Direct goal creation
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={directCreation}
            onChange={e => setDirectCreation(e.target.checked)}
            className="rounded border-border text-accent focus:ring-accent-500/40"
          />
          <span className="text-compact text-content-primary">
            Enable manual goal creation form on Goals page
          </span>
        </label>
      </div>
    </Section>
  )
}
