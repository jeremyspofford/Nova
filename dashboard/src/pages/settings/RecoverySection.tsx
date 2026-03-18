import { Shield } from 'lucide-react'
import { BackupSection as RecoveryBackupSection, FactoryResetSection as RecoveryFactoryReset } from '../Recovery'
import { Section } from '../../components/ui'

export function RecoverySection() {
  return (
    <Section
      icon={Shield}
      title="Recovery"
      description="Database backups with restore, and factory reset. Recovery service also available directly at port 8888."
    >
      <div className="space-y-6">
        <RecoveryBackupSection />
        <RecoveryFactoryReset />
      </div>
    </Section>
  )
}
