import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'
import { AlertTriangle, RotateCcw } from 'lucide-react'

type Props = {
  children: ReactNode
  /** Optional fallback UI. If omitted, a default crash card is rendered. */
  fallback?: ReactNode
}

type State = {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack)
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null })
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback

      return (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <AlertTriangle className="w-12 h-12 text-warning mb-4" />
          <h2 className="text-h3 text-content-primary mb-2">Something went wrong</h2>
          <p className="text-compact text-content-secondary max-w-md mb-2">
            This section crashed unexpectedly. You can try reloading it, or check the
            browser console for details.
          </p>
          {this.state.error && (
            <pre className="text-mono-sm text-content-tertiary max-w-lg truncate mb-4">
              {this.state.error.message}
            </pre>
          )}
          <button
            onClick={this.handleReset}
            className="inline-flex items-center gap-2 rounded-sm border border-border bg-surface-card px-4 py-2 text-compact text-content-primary hover:bg-surface-card-hover transition-colors duration-fast"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            Try Again
          </button>
        </div>
      )
    }

    return this.props.children
  }
}
