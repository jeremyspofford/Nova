import { Check, MessageSquare, Settings } from 'lucide-react'

interface Props {
  backend: string
  model: string
  onFinish: () => void
}

export function Ready({ backend, model, onFinish }: Props) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-16 px-4">
      <div className="w-16 h-16 rounded-full bg-teal-500 flex items-center justify-center mb-6">
        <Check className="w-8 h-8 text-white" />
      </div>
      <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100 mb-2">
        Nova is Ready
      </h2>
      <p className="text-sm text-neutral-500 dark:text-neutral-400 mb-2">
        {backend === 'cloud'
          ? 'Cloud providers are configured and ready to go.'
          : (
            <>
              <span className="font-medium text-neutral-700 dark:text-neutral-300">{model}</span>
              {' '}is running via{' '}
              <span className="font-medium text-neutral-700 dark:text-neutral-300">{backend}</span>.
            </>
          )
        }
      </p>
      <p className="text-xs text-neutral-400 dark:text-neutral-500 mb-8 flex items-center gap-1">
        <Settings className="w-3 h-3" />
        You can change models and backends anytime in Settings.
      </p>
      <button
        onClick={onFinish}
        className="inline-flex items-center gap-2 px-6 py-2.5 rounded-lg bg-teal-600 hover:bg-teal-700 text-white text-sm font-medium transition-colors"
      >
        <MessageSquare className="w-4 h-4" />
        Start Chatting
      </button>
    </div>
  )
}
