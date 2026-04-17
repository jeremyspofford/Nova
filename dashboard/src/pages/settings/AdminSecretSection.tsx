import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { ShieldAlert, Eye, EyeOff, Check, Copy, RefreshCw } from 'lucide-react'
import { apiFetch, getAdminSecret, setAdminSecret } from '../../api'
import { Section, Button, ConfirmDialog } from '../../components/ui'
import { useToast } from '../../components/ToastProvider'

interface RotateResponse {
  secret: string
}

const rotateAdminSecret = () =>
  apiFetch<RotateResponse>('/api/v1/admin/rotate-secret', { method: 'POST' })

/** Mask a secret: keep the first few prefix chars, replace the rest with "*". */
function mask(secret: string): string {
  if (!secret) return '(not set)'
  // Keep a recognizable prefix (up to the first hyphen-delimited token or 12 chars)
  const dashIdx = secret.indexOf('-')
  const prefixLen = dashIdx > 0 && dashIdx < 16 ? dashIdx + 1 : Math.min(12, Math.floor(secret.length / 3))
  const prefix = secret.slice(0, prefixLen)
  return `${prefix}${'*'.repeat(Math.max(8, secret.length - prefixLen))}`
}

export function AdminSecretSection() {
  const { addToast } = useToast()
  const [currentSecret, setCurrentSecret] = useState<string>(() => getAdminSecret())
  const [revealed, setRevealed] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [newSecret, setNewSecret] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const rotateMutation = useMutation({
    mutationFn: rotateAdminSecret,
    onSuccess: (data) => {
      setAdminSecret(data.secret)
      setCurrentSecret(data.secret)
      setNewSecret(data.secret)
      setRevealed(false)
      setConfirmOpen(false)
      addToast({ variant: 'success', message: 'Admin secret rotated. Copy the new value now.' })
    },
    onError: (err) => {
      setConfirmOpen(false)
      addToast({
        variant: 'error',
        message: `Failed to rotate admin secret: ${err instanceof Error ? err.message : String(err)}`,
      })
    },
  })

  const handleCopy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      addToast({ variant: 'error', message: 'Copy failed — select the value manually' })
    }
  }

  const isSet = currentSecret.length > 0
  const displayValue = revealed ? currentSecret : mask(currentSecret)

  return (
    <Section
      icon={ShieldAlert}
      title="Admin Secret"
      description={
        'The admin secret is a bootstrap credential that grants full admin access to Nova\u2019s API. ' +
        'It\u2019s used by the recovery console, CLI tools, and the dashboard before a user logs in. ' +
        'Rotate it after a suspected leak, when handing off ownership, or as routine hygiene.'
      }
    >
      <div className="space-y-4">
        {/* Current secret display */}
        <div>
          <label className="text-caption font-medium text-content-secondary mb-1.5 block">
            Current secret
          </label>
          <div className="flex items-center gap-2 flex-wrap">
            <code
              className="flex-1 min-w-0 font-mono text-mono-sm bg-surface-elevated border border-border-subtle rounded-sm px-3 py-2 text-content-primary break-all"
              aria-label={revealed ? 'Admin secret (revealed)' : 'Admin secret (masked)'}
            >
              {displayValue}
            </code>
            {isSet && (
              <>
                <Button
                  variant="ghost"
                  size="sm"
                  icon={revealed ? <EyeOff size={14} /> : <Eye size={14} />}
                  onClick={() => setRevealed((v) => !v)}
                >
                  {revealed ? 'Hide' : 'Reveal'}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  icon={copied ? <Check size={14} /> : <Copy size={14} />}
                  onClick={() => handleCopy(currentSecret)}
                >
                  {copied ? 'Copied' : 'Copy'}
                </Button>
              </>
            )}
          </div>
          {!isSet && (
            <p className="text-caption text-content-tertiary mt-1.5">
              No admin secret stored in this browser. Rotate to generate one, or paste an existing
              value into <code className="font-mono text-mono-sm bg-surface-elevated px-1 py-0.5 rounded-xs">localStorage.nova_admin_secret</code>.
            </p>
          )}
        </div>

        {/* Newly rotated secret banner */}
        {newSecret && (
          <div className="rounded-lg border border-success/30 bg-success-dim p-4 space-y-2">
            <p className="text-compact font-medium text-content-primary">
              New admin secret generated. This browser is already updated — save it somewhere safe before dismissing.
            </p>
            <div className="flex items-center gap-2 flex-wrap">
              <code className="flex-1 min-w-0 font-mono text-mono-sm bg-surface-elevated border border-border-subtle rounded-sm px-3 py-2 text-content-primary break-all">
                {newSecret}
              </code>
              <Button
                variant="outline"
                size="sm"
                icon={copied ? <Check size={14} /> : <Copy size={14} />}
                onClick={() => handleCopy(newSecret)}
              >
                {copied ? 'Copied' : 'Copy'}
              </Button>
            </div>
            <button
              type="button"
              onClick={() => setNewSecret(null)}
              className="text-caption text-content-tertiary hover:text-content-secondary transition-colors"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Rotate action */}
        <div className="flex items-center gap-3 pt-2 border-t border-border-subtle">
          <Button
            variant="danger"
            size="sm"
            icon={<RefreshCw size={14} />}
            loading={rotateMutation.isPending}
            onClick={() => setConfirmOpen(true)}
          >
            Rotate Admin Secret
          </Button>
          <span className="text-caption text-content-tertiary">
            Generates a new 64-character value and invalidates the current one immediately.
          </span>
        </div>
      </div>

      <ConfirmDialog
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title="Rotate admin secret?"
        description={
          'This generates a new admin secret and invalidates the current one. ' +
          'Any other devices, CLI tools, or scripts using the current secret will stop working ' +
          'until updated. This browser\u2019s stored secret will be updated automatically.'
        }
        confirmLabel="Rotate Secret"
        destructive
        onConfirm={() => rotateMutation.mutate()}
      />
    </Section>
  )
}
