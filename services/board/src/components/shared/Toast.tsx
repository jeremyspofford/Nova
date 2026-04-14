interface ToastProps {
  message: string
  onDismiss: () => void
}

export function Toast({ message, onDismiss }: ToastProps) {
  return (
    <div className="toast" role="alert">
      <span>{message}</span>
      <button onClick={onDismiss} aria-label="Dismiss">&times;</button>
    </div>
  )
}
