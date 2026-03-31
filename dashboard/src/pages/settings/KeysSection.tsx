import { Key } from 'lucide-react'
import { Section } from '../../components/ui'
import { KeysContent } from '../Keys'

export function KeysSection() {
  return (
    <Section
      icon={Key}
      title="API Keys"
      description="Keys let external clients call Nova's OpenAI-compatible API. Each key has its own rate limit and usage tracking."
    >
      <KeysContent />
    </Section>
  )
}
