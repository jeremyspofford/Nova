import { useState } from 'react'
import { Radio } from 'lucide-react'
import { Section, Toggle } from '../../components/ui'

export function NotificationsSection() {
  const [enabled, setEnabled] = useState(() => localStorage.getItem('nova-notifications-enabled') === 'true')
  const [permission, setPermission] = useState<NotificationPermission | 'unsupported'>(
    'Notification' in window ? Notification.permission : 'unsupported'
  )

  const toggle = async (checked: boolean) => {
    if (checked) {
      // Enabling -- request permission first
      if ('Notification' in window && Notification.permission !== 'granted') {
        const result = await Notification.requestPermission()
        setPermission(result)
        if (result !== 'granted') return
      }
      localStorage.setItem('nova-notifications-enabled', 'true')
      setEnabled(true)
    } else {
      localStorage.setItem('nova-notifications-enabled', 'false')
      setEnabled(false)
    }
  }

  return (
    <Section
      icon={Radio}
      title="Notifications"
      description="Desktop notifications for task completion (coming soon)"
    >
      <div className="flex items-center justify-between">
        <div>
          <p className="text-compact font-medium text-content-primary">Enable notifications</p>
          <p className="text-caption text-content-tertiary">
            {permission === 'unsupported' ? 'Not supported in this browser' :
             permission === 'denied' ? 'Blocked by browser -- check site permissions' :
             'Push notifications will be available when async tasks are implemented'}
          </p>
        </div>
        <Toggle
          checked={enabled}
          onChange={toggle}
          disabled={permission === 'unsupported' || permission === 'denied'}
        />
      </div>
    </Section>
  )
}
