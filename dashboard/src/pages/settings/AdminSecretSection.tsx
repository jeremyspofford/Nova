import { useState } from 'react'
import { ShieldCheck } from 'lucide-react'
import { getAdminSecret, setAdminSecret } from '../../api'
import { Section } from './shared'

export function AdminSecretSection() {
  const [secret, setSecret] = useState(getAdminSecret)
  const [saved, setSaved] = useState(false)

  const handleSave = () => {
    setAdminSecret(secret)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <Section
      icon={ShieldCheck}
      title="Admin Secret"
      description="The password this browser sends with admin requests (Pods, Keys, Usage)."
    >
      <div className="space-y-2">
        <input
          type="password"
          value={secret}
          onChange={e => { setSecret(e.target.value); setSaved(false) }}
          placeholder="Paste your ADMIN_SECRET from .env"
          className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-100 dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 outline-none focus:border-accent-600"
        />
        <p className="text-xs text-neutral-500 dark:text-neutral-400">
          Must match the <code className="rounded bg-neutral-100 dark:bg-neutral-700 px-1 text-neutral-600 dark:text-neutral-300">ADMIN_SECRET</code> value
          in your server's <code className="rounded bg-neutral-100 dark:bg-neutral-700 px-1 text-neutral-600 dark:text-neutral-300">.env</code> file.
          Stored in localStorage only.
        </p>
        <button
          onClick={handleSave}
          className="rounded-md bg-accent-700 px-3 py-1.5 text-sm text-white hover:bg-accent-500"
        >
          {saved ? 'Saved' : 'Save'}
        </button>
      </div>
    </Section>
  )
}
