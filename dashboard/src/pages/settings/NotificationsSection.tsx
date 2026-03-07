import { useState } from 'react'
import { Radio } from 'lucide-react'
import { Section } from './shared'

export function NotificationsSection() {
  const [enabled, setEnabled] = useState(() => localStorage.getItem('nova-notifications-enabled') === 'true')
  const [permission, setPermission] = useState<NotificationPermission | 'unsupported'>(
    'Notification' in window ? Notification.permission : 'unsupported'
  )

  const toggle = async () => {
    if (!enabled) {
      // Enabling — request permission first
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
          <p className="text-sm font-medium text-stone-700 dark:text-stone-300">Enable notifications</p>
          <p className="text-xs text-stone-500 dark:text-stone-400">
            {permission === 'unsupported' ? 'Not supported in this browser' :
             permission === 'denied' ? 'Blocked by browser — check site permissions' :
             'Push notifications will be available when async tasks are implemented'}
          </p>
        </div>
        <button
          onClick={toggle}
          disabled={permission === 'unsupported' || permission === 'denied'}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
            enabled ? 'bg-accent-600' : 'bg-stone-300 dark:bg-stone-600'
          } ${(permission === 'unsupported' || permission === 'denied') ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
        >
          <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
            enabled ? 'translate-x-6' : 'translate-x-1'
          }`} />
        </button>
      </div>
    </Section>
  )
}
