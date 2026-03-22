import { useState } from 'react'
import { Users as UsersIcon } from 'lucide-react'
import { useAuth } from '../../stores/auth-store'
import { Section, Tabs } from '../../components/ui'
import { UsersTab, InvitationsTab } from '../Users'
import type { Role } from '../../lib/roles'

type Tab = 'users' | 'invitations'

export function UsersSection() {
  const [tab, setTab] = useState<Tab>('users')
  const { user: currentUser } = useAuth()
  const currentRole = (currentUser?.role ?? 'viewer') as Role

  return (
    <Section
      icon={UsersIcon}
      title="Users"
      description="Manage users and invite new people to your Nova instance."
    >
      <Tabs
        tabs={[
          { id: 'users', label: 'Users' },
          { id: 'invitations', label: 'Invitations' },
        ]}
        activeTab={tab}
        onChange={(id) => setTab(id as Tab)}
      />

      {tab === 'users' ? (
        <UsersTab currentRole={currentRole} currentUserId={currentUser?.id} />
      ) : (
        <InvitationsTab currentRole={currentRole} />
      )}
    </Section>
  )
}
