import { useEffect, useState } from 'react'
import { Cpu, HardDrive, Loader2, Server, AlertTriangle } from 'lucide-react'
import { getHardwareInfo, type HardwareInfo } from '../../../api-recovery'

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
      <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
        <AlertTriangle className="w-10 h-10 text-amber-500 mb-4" />
        <p className="text-sm text-neutral-500 dark:text-neutral-400 mb-4">
          Could not detect hardware: {error}
        </p>
        <button
          onClick={() => { setError(null); getHardwareInfo().then(setHardware).catch(e => setError(e.message)) }}
          className="text-sm text-teal-600 hover:text-teal-700"
        >
          Retry
        </button>
      </div>
    )
  }

  if (!hardware) {
    return (
      <div className="flex flex-col items-center justify-center py-16">
        <Loader2 className="w-8 h-8 text-teal-500 animate-spin mb-4" />
        <p className="text-sm text-neutral-500 dark:text-neutral-400">Detecting hardware...</p>
      </div>
    )
  }

  const hasGpu = hardware.gpus.length > 0
  const totalVram = hardware.gpus.reduce((s, g) => s + g.vram_gb, 0)

  return (
    <div className="flex flex-col items-center py-12 px-4">
      <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100 mb-2">
        Hardware Detected
      </h2>
      <p className="text-sm text-neutral-500 dark:text-neutral-400 mb-6 text-center max-w-md">
        Here's what we found on your system.
      </p>

      {/* GPU banner */}
      {hasGpu ? (
        <div className="w-full max-w-sm rounded-lg bg-emerald-500/10 border border-emerald-500/20 p-3 mb-6">
          <p className="text-sm text-emerald-700 dark:text-emerald-400 font-medium">
            GPU detected — local AI inference available
          </p>
        </div>
      ) : (
        <div className="w-full max-w-sm rounded-lg bg-amber-500/10 border border-amber-500/20 p-3 mb-6">
          <p className="text-sm text-amber-700 dark:text-amber-400 font-medium">
            No GPU detected — CPU inference or cloud providers recommended
          </p>
        </div>
      )}

      {/* Hardware cards */}
      <div className="w-full max-w-sm space-y-3">
        {hardware.gpus.map((gpu, i) => (
          <div key={i} className="flex items-center gap-3 rounded-lg border border-neutral-200 dark:border-neutral-800 p-3">
            <Server className="w-5 h-5 text-teal-500 shrink-0" />
            <div className="min-w-0">
              <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100 truncate">{gpu.model}</p>
              <p className="text-xs text-neutral-500 dark:text-neutral-400">{gpu.vram_gb} GB VRAM</p>
            </div>
          </div>
        ))}

        <div className="flex items-center gap-3 rounded-lg border border-neutral-200 dark:border-neutral-800 p-3">
          <Cpu className="w-5 h-5 text-neutral-400 shrink-0" />
          <div>
            <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100">{hardware.cpu_cores} CPU cores</p>
            <p className="text-xs text-neutral-500 dark:text-neutral-400">{hardware.ram_gb} GB RAM</p>
          </div>
        </div>

        <div className="flex items-center gap-3 rounded-lg border border-neutral-200 dark:border-neutral-800 p-3">
          <HardDrive className="w-5 h-5 text-neutral-400 shrink-0" />
          <div>
            <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100">{hardware.disk_free_gb} GB free disk</p>
          </div>
        </div>
      </div>

      <button
        onClick={() => onNext(hardware)}
        className="mt-8 px-6 py-2.5 rounded-lg bg-teal-600 hover:bg-teal-700 text-white text-sm font-medium transition-colors"
      >
        Continue
      </button>
    </div>
  )
}
