import { ShieldAlert } from 'lucide-react'
import { Section } from '../../components/ui'
import { RulesContent } from '../Rules'

export function RulesSection() {
  return (
    <Section
      icon={ShieldAlert}
      title="Rules"
      description="Constraints on agent behavior. Rules check tool calls before execution."
    >
      <RulesContent />
    </Section>
  )
}
