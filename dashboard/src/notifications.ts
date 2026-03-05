/**
 * Push notification utilities (stub).
 *
 * Requests permission and stores preference. Actual push subscription
 * (VAPID keys, service worker registration) will be wired up when the
 * async task webhook system lands (Phase 4+).
 */

const PREF_KEY = 'nova-notifications-enabled'

export function getNotificationPreference(): boolean {
  return localStorage.getItem(PREF_KEY) === 'true'
}

export function setNotificationPreference(enabled: boolean) {
  localStorage.setItem(PREF_KEY, String(enabled))
}

export async function requestNotificationPermission(): Promise<boolean> {
  if (!('Notification' in window)) return false

  if (Notification.permission === 'granted') return true
  if (Notification.permission === 'denied') return false

  const result = await Notification.requestPermission()
  return result === 'granted'
}

/**
 * Show a local notification (for testing / future use).
 * Push subscriptions will be added when the backend supports it.
 */
export function showNotification(title: string, body: string) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return
  new Notification(title, {
    body,
    icon: '/nova-icon-192.png',
    badge: '/nova-icon-192.png',
  })
}
