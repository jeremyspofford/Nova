import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { Button } from './ui'
import { LogFrictionSheet } from './LogFrictionSheet'

export function LogFrictionButton() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button
        variant="primary"
        className="fixed bottom-6 right-6 z-40 shadow-lg"
        onClick={() => setOpen(true)}
        aria-label="Log friction"
      >
        <AlertTriangle className="h-4 w-4" />
        <span className="hidden md:inline ml-2">Log Friction</span>
      </Button>
      <LogFrictionSheet open={open} onOpenChange={setOpen} />
    </>
  )
}
