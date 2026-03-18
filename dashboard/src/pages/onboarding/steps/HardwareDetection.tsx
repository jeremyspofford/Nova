import { useEffect, useState } from 'react'
import { Cpu, HardDrive, Loader2, Server, AlertTriangle } from 'lucide-react'
import { getHardwareInfo, type HardwareInfo } from '../../../api-recovery'
import { Button, Card, Badge } from '../../../components/ui'

interface Props {
  onNext: (hardware: HardwareInfo) => void
}

export function HardwareDetection({ onNext }: Props) {
  const [hardware, setHardware] = useState<HardwareInfo | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getHardwareInfo()
      .then(setHardware)
      .catch(e => setError(e.message))
  }, [])

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-16 px-6 text-center">
        <AlertTriangle className="w-10 h-10 text-warning mb-4" />
        <p className="text-compact text-content-secondary mb-4">
          Could not detect hardware: {error}
        </p>
        <button
          onClick={() => { setError(null); getHardwareInfo().then(setHardware).catch(e => setError(e.message)) }}
          className="text-compact text-accent hover:text-accent-hover transition-colors"
        >
          Retry
        </button>
      </div>
    )
  }

  if (!hardware) {
    return (
      <div className="flex flex-col items-center justify-center py-16">
        <Loader2 className="w-8 h-8 text-accent animate-spin mb-4" />
        <p className="text-compact text-content-secondary">Detecting hardware...</p>
      </div>
    )
  }

  const hasGpu = hardware.gpus.length > 0

  return (
    <div className="flex flex-col items-center py-12 px-6">
      <h2 className="text-h3 text-content-primary mb-2">
        Hardware Detected
      </h2>
      <p className="text-compact text-content-secondary mb-6 text-center max-w-md">
        Here's what we found on your system.
      </p>

      {/* GPU banner */}
      {hasGpu ? (
        <div className="w-full max-w-sm rounded-lg bg-success-dim border border-success/20 p-3 mb-6">
          <p className="text-compact text-emerald-700 dark:text-emerald-400 font-medium">
            GPU detected -- local AI inference available
          </p>
        </div>
      ) : (
        <div className="w-full max-w-sm rounded-lg bg-warning-dim border border-warning/20 p-3 mb-6">
          <p className="text-compact text-amber-700 dark:text-amber-400 font-medium">
            No GPU detected -- CPU inference or cloud providers recommended
          </p>
        </div>
      )}

      {/* Hardware cards */}
      <div className="w-full max-w-sm space-y-3">
        {hardware.gpus.map((gpu, i) => (
          <div key={i} className="flex items-center gap-3 rounded-lg border border-border-subtle bg-surface-elevated p-3">
            <Server className="w-5 h-5 text-accent shrink-0" />
            <div className="min-w-0">
              <p className="text-compact font-medium text-content-primary truncate">{gpu.model}</p>
              <p className="text-caption text-content-tertiary">{gpu.vram_gb} GB VRAM</p>
            </div>
          </div>
        ))}

        <div className="flex items-center gap-3 rounded-lg border border-border-subtle bg-surface-elevated p-3">
          <Cpu className="w-5 h-5 text-content-tertiary shrink-0" />
          <div>
            <p className="text-compact font-medium text-content-primary">{hardware.cpu_cores} CPU cores</p>
            <p className="text-caption text-content-tertiary">{hardware.ram_gb} GB RAM</p>
          </div>
        </div>

        <div className="flex items-center gap-3 rounded-lg border border-border-subtle bg-surface-elevated p-3">
          <HardDrive className="w-5 h-5 text-content-tertiary shrink-0" />
          <div>
            <p className="text-compact font-medium text-content-primary">{hardware.disk_free_gb} GB free disk</p>
          </div>
        </div>
      </div>

      <Button className="mt-8" onClick={() => onNext(hardware)}>
        Continue
      </Button>
    </div>
  )
}
