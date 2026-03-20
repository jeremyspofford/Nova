import { useState, useRef, useCallback, useEffect } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { Sheet, Button, Textarea, RadioGroup, Toast } from './ui'
import { createFrictionEntry } from '../api'

interface LogFrictionSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function LogFrictionSheet({ open, onOpenChange }: LogFrictionSheetProps) {
  const qc = useQueryClient()
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [description, setDescription] = useState('')
  const [severity, setSeverity] = useState('blocker')
  const [screenshot, setScreenshot] = useState<{ full: string; thumb: string } | null>(null)
  const [toast, setToast] = useState<{ variant: 'success' | 'error'; message: string } | null>(null)

  // Auto-focus textarea on open
  useEffect(() => {
    if (open) setTimeout(() => textareaRef.current?.focus(), 100)
  }, [open])

  const mutation = useMutation({
    mutationFn: () => createFrictionEntry({
      description,
      severity,
      screenshot: screenshot?.full,
      screenshot_thumb: screenshot?.thumb,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['friction'] })
      qc.invalidateQueries({ queryKey: ['friction-stats'] })
      setDescription('')
      setSeverity('blocker')
      setScreenshot(null)
      onOpenChange(false)
      setToast({ variant: 'success', message: 'Friction logged' })
    },
    onError: () => {
      setToast({ variant: 'error', message: 'Failed to save. Try again.' })
    },
  })

  const handlePaste = useCallback(async (e: React.ClipboardEvent) => {
    const items = e.clipboardData.items
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        e.preventDefault()
        const file = item.getAsFile()
        if (!file) return
        if (file.size > 5 * 1024 * 1024) {
          setToast({ variant: 'error', message: 'Screenshot too large (max 5MB)' })
          return
        }
        const result = await resizeImage(file)
        setScreenshot(result)
        return
      }
    }
  }, [])

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    if (!file?.type.startsWith('image/')) return
    if (file.size > 5 * 1024 * 1024) {
      setToast({ variant: 'error', message: 'Screenshot too large (max 5MB)' })
      return
    }
    const result = await resizeImage(file)
    setScreenshot(result)
  }, [])

  return (
    <>
      <Sheet open={open} onClose={() => onOpenChange(false)} title="Log Friction">
        <div className="p-5 space-y-5" onPaste={handlePaste}>
          <div>
            <label className="text-caption font-medium text-content-secondary mb-1.5 block">
              What went wrong?
            </label>
            <Textarea
              ref={textareaRef}
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Describe the issue..."
              rows={4}
            />
          </div>

          <div>
            <label className="text-caption font-medium text-content-secondary mb-1.5 block">
              Severity
            </label>
            <RadioGroup
              name="severity"
              options={[
                { value: 'blocker', label: 'Blocker' },
                { value: 'annoyance', label: 'Annoyance' },
                { value: 'idea', label: 'Idea' },
              ]}
              value={severity}
              onChange={setSeverity}
            />
          </div>

          <div>
            <label className="text-caption font-medium text-content-secondary mb-1.5 block">
              Screenshot (optional)
            </label>
            {screenshot ? (
              <div className="relative inline-block">
                <img
                  src={screenshot.thumb}
                  alt="Screenshot preview"
                  className="rounded-md max-h-32 border border-border"
                />
                <button
                  onClick={() => setScreenshot(null)}
                  className="absolute -top-2 -right-2 rounded-full bg-surface-elevated border border-border p-0.5"
                  aria-label="Remove screenshot"
                >
                  <X size={12} />
                </button>
              </div>
            ) : (
              <div
                onDrop={handleDrop}
                onDragOver={e => e.preventDefault()}
                tabIndex={0}
                role="button"
                aria-label="Drop screenshot here or paste with Ctrl+V"
                className="border-2 border-dashed border-border-subtle rounded-lg p-6 text-center text-caption text-content-tertiary hover:border-accent/50 transition-colors cursor-pointer"
              >
                Paste (Ctrl+V) or drop an image
              </div>
            )}
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => mutation.mutate()}
              disabled={!description.trim() || mutation.isPending}
              loading={mutation.isPending}
            >
              Submit
            </Button>
          </div>
        </div>
      </Sheet>

      {toast && (
        <Toast
          variant={toast.variant}
          message={toast.message}
          onDismiss={() => setToast(null)}
        />
      )}
    </>
  )
}


function resizeImage(file: File, maxWidth = 200): Promise<{ full: string; thumb: string }> {
  return new Promise((resolve) => {
    const reader = new FileReader()
    reader.onload = () => {
      const img = new Image()
      img.onload = () => {
        const canvas = document.createElement('canvas')
        const scale = Math.min(maxWidth / img.width, maxWidth / img.height, 1)
        canvas.width = img.width * scale
        canvas.height = img.height * scale
        canvas.getContext('2d')!.drawImage(img, 0, 0, canvas.width, canvas.height)
        resolve({
          full: reader.result as string,
          thumb: canvas.toDataURL('image/jpeg', 0.7),
        })
      }
      img.src = reader.result as string
    }
    reader.readAsDataURL(file)
  })
}
