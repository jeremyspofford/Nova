import { Wand2 } from 'lucide-react'
import { Section } from '../../components/ui'
import { SkillsContent } from '../Skills'

export function SkillsSection() {
  return (
    <Section
      icon={Wand2}
      title="Skills"
      description="Reusable prompt templates injected into agent conversations."
    >
      <SkillsContent />
    </Section>
  )
}
