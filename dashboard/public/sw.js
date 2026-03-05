/**
 * Nova PWA Service Worker
 *
 * Strategy:
 *  - Cache the app shell (HTML, CSS, JS) on install for instant home-screen launch
 *  - Network-first for API calls (never cache API responses)
 *  - Cache-first for static assets (icons, fonts)
 *  - Stale-while-revalidate for the app shell after initial load
 */

const CACHE_NAME = 'nova-shell-v1'

// App shell files cached on install — updated on new SW deployment
const SHELL_FILES = [
  '/',
  '/manifest.json',
  '/nova-icon.png',
  '/nova-icon-192.png',
]

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_FILES))
  )
  // Activate immediately without waiting for old SW to stop
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  // Clean up old caches when a new version deploys
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  )
  self.clients.claim()
})

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url)

  // Never cache API calls, WebSocket upgrades, or dev server HMR
  if (
    url.pathname.startsWith('/api') ||
    url.pathname.startsWith('/v1') ||
    url.pathname.startsWith('/ws') ||
    url.pathname.startsWith('/recovery-api') ||
    url.pathname.includes('hot-update') ||
    event.request.method !== 'GET'
  ) {
    return // Fall through to network
  }

  // Static assets: cache-first
  if (url.pathname.match(/\.(png|jpg|svg|ico|woff2?|ttf|eot)$/)) {
    event.respondWith(
      caches.match(event.request).then((cached) =>
        cached || fetch(event.request).then((resp) => {
          const clone = resp.clone()
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone))
          return resp
        })
      )
    )
    return
  }

  // App shell (HTML, JS, CSS): stale-while-revalidate
  event.respondWith(
    caches.match(event.request).then((cached) => {
      const fetchPromise = fetch(event.request).then((resp) => {
        const clone = resp.clone()
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone))
        return resp
      }).catch(() => cached) // Offline fallback to cache

      return cached || fetchPromise
    })
  )
})
