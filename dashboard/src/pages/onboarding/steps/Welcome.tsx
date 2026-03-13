import { Sparkles } from 'lucide-react'

interface Props {
  onNext: () => void
  onSkip: () => void
}

export function Welcome({ onNext, onSkip }: Props) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-16 px-4">
      <div className="w-16 h-16 rounded-2xl bg-teal-500/10 flex items-center justify-center mb-6">
        <Sparkles className="w-8 h-8 text-teal-500" />
      </div>
      <h1 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100 mb-2">
        Welcome to Nova
      </h1>
      <p className="text-sm text-neutral-500 dark:text-neutral-400 max-w-md mb-8">
        Let's set up your AI engine. We'll detect your hardware, pick the best
        inference backend, and download a model so you can start chatting in minutes.
      </p>
      <button
        onClick={onNext}
        className="px-6 py-2.5 rounded-lg bg-teal-600 hover:bg-teal-700 text-white text-sm font-medium transition-colors"
      >
        Get Started
      </button>
      <button
        onClick={onSkip}
        className="mt-4 text-xs text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-300 transition-colors"
      >
        Skip setup
      </button>
    </div>
  )
}
