import { useParams, Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../stores/auth-store'

export function Invite() {
  const { code } = useParams<{ code: string }>()
  const { isAuthenticated } = useAuth()
  const navigate = useNavigate()

  if (!isAuthenticated) {
    return <Navigate to={`/login?invite=${code}`} replace />
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-neutral-50 dark:bg-neutral-950">
      <div className="max-w-md w-full p-8 text-center space-y-4">
        <h1 className="text-xl font-semibold text-neutral-900 dark:text-neutral-100">
          You're already logged in
        </h1>
        <p className="text-sm text-neutral-500 dark:text-neutral-400">
          This invite link is for new users. You already have an account.
        </p>
        <button
          onClick={() => navigate('/')}
          className="rounded-lg bg-teal-600 hover:bg-teal-700 text-white text-sm px-4 py-2"
        >
          Go to Chat
        </button>
      </div>
    </div>
  )
}
