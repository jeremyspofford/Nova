import { Loader2 } from 'lucide-react'

interface Props {
  onSave: () => void
  onCancel: () => void
  isPending: boolean
  saveLabel?: string
  savingLabel?: string
}

export function SaveCancelButtons({ onSave, onCancel, isPending, saveLabel = 'Save', savingLabel = 'Saving…' }: Props) {
  return (
    <div className="flex items-center justify-end gap-1.5">
      <button
        onClick={onCancel}
        disabled={isPending}
        className="rounded-md border border-neutral-200 dark:border-neutral-800 px-3 py-1 text-xs text-neutral-500 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 disabled:opacity-40"
      >
        Cancel
      </button>
      <button
        onClick={onSave}
        disabled={isPending}
        className="flex items-center gap-1.5 rounded-md bg-accent-700 px-3 py-1 text-xs font-medium text-white hover:bg-accent-600 disabled:opacity-40"
      >
        {isPending ? <><Loader2 size={11} className="animate-spin" /> {savingLabel}</> : saveLabel}
      </button>
    </div>
  )
}
