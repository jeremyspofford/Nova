import { useAuth } from '../stores/auth-store'

export function Expired() {
  const { logout } = useAuth()

  return (
    <div className="min-h-screen flex items-center justify-center bg-neutral-50 dark:bg-neutral-950">
      <div className="max-w-md w-full p-8 text-center space-y-4">
        <div className="mx-auto w-12 h-12 rounded-full bg-amber-400/10 flex items-center justify-center">
          <span className="text-2xl">&#x23F0;</span>
        </div>
        <h1 className="text-xl font-semibold text-neutral-900 dark:text-neutral-100">
          Access Expired
        </h1>
        <p className="text-sm text-neutral-500 dark:text-neutral-400">
          Your account access has expired. Contact the administrator if you need an extension.
        </p>
        <button
          onClick={logout}
          className="rounded-lg bg-neutral-700 hover:bg-neutral-600 text-white text-sm px-4 py-2"
        >
          Sign Out
        </button>
      </div>
    </div>
  )
}
