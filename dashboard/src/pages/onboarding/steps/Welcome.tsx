import { Sparkles } from 'lucide-react'
import { Button } from '../../../components/ui'

interface Props {
  onNext: () => void
  onSkip: () => void
}

export function Welcome({ onNext, onSkip }: Props) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-16 px-6">
      <div className="w-16 h-16 rounded-xl bg-accent/10 flex items-center justify-center mb-6">
        <Sparkles className="w-8 h-8 text-accent" />
      </div>
      <h1 className="text-h2 text-content-primary mb-2">
        Welcome to Nova
      </h1>
      <p className="text-compact text-content-secondary max-w-md mb-8">
        Let's set up your AI engine. We'll detect your hardware, pick the best
        inference backend, and download a model so you can start chatting in minutes.
      </p>
      <Button size="lg" onClick={onNext}>
        Get Started
      </Button>
      <button
        onClick={onSkip}
        className="mt-4 text-caption text-content-tertiary hover:text-content-secondary transition-colors"
      >
        Skip setup
      </button>
    </div>
  )
}
