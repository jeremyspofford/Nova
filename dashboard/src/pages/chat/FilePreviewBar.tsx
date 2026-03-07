import { X, FileText } from 'lucide-react'
import type { AttachedFile } from '../../stores/chat-store'

interface Props {
  files: AttachedFile[]
  onRemove: (id: string) => void
}

export function FilePreviewBar({ files, onRemove }: Props) {
  if (files.length === 0) return null

  return (
    <div className="flex gap-2 px-1 pb-2 overflow-x-auto">
      {files.map(f => (
        <div
          key={f.id}
          className="relative group shrink-0 rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 overflow-hidden"
        >
          {f.type === 'image' && f.previewUrl ? (
            <img
              src={f.previewUrl}
              alt={f.file.name}
              className="h-16 w-16 object-cover"
            />
          ) : (
            <div className="h-16 w-20 flex flex-col items-center justify-center gap-1 px-1">
              <FileText size={16} className="text-neutral-400" />
              <span className="text-[9px] text-neutral-500 dark:text-neutral-400 truncate max-w-full text-center leading-tight">
                {f.file.name}
              </span>
            </div>
          )}
          <button
            type="button"
            onClick={() => onRemove(f.id)}
            className="absolute top-0.5 right-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-neutral-900/60 text-white opacity-0 group-hover:opacity-100 transition-opacity"
          >
            <X size={10} />
          </button>
        </div>
      ))}
    </div>
  )
}
