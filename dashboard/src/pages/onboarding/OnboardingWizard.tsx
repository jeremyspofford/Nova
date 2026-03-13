import { useState, useCallback } from 'react'
import { updatePlatformConfig } from '../../api'
import type { HardwareInfo } from '../../api-recovery'
import { Welcome } from './steps/Welcome'
import { HardwareDetection } from './steps/HardwareDetection'
import { ChooseEngine } from './steps/ChooseEngine'
import { PickModel } from './steps/PickModel'
import { Downloading } from './steps/Downloading'
import { Ready } from './steps/Ready'

type Step = 'welcome' | 'hardware' | 'engine' | 'model' | 'downloading' | 'ready'

const stepOrder: Step[] = ['welcome', 'hardware', 'engine', 'model', 'downloading', 'ready']

export function OnboardingWizard() {
  const [step, setStep] = useState<Step>('welcome')
  const [hardware, setHardware] = useState<HardwareInfo | null>(null)
  const [engine, setEngine] = useState<'vllm' | 'ollama' | 'cloud'>('ollama')
  const [model, setModel] = useState('')

  const completeOnboarding = useCallback(async () => {
    try {
      await updatePlatformConfig('onboarding.completed', '"true"')
    } catch {
      // Best-effort — don't block the user
    }
    window.location.href = '/chat'
  }, [])

  const handleSkip = useCallback(() => {
    completeOnboarding()
  }, [completeOnboarding])

  const handleHardwareNext = useCallback((hw: HardwareInfo) => {
    setHardware(hw)
    // Pre-select recommended engine
    const totalVram = hw.gpus.reduce((s, g) => s + g.vram_gb, 0)
    if (totalVram >= 8) setEngine('vllm')
    else setEngine('ollama')
    setStep('engine')
  }, [])

  const handleEngineNext = useCallback(() => {
    if (engine === 'cloud') {
      setStep('downloading')
    } else {
      setStep('model')
    }
  }, [engine])

  const handleModelNext = useCallback(() => {
    setStep('downloading')
  }, [])

  const handleDownloadNext = useCallback(() => {
    setStep('ready')
  }, [])

  const currentIdx = stepOrder.indexOf(step)

  return (
    <div className="min-h-screen bg-neutral-50 dark:bg-neutral-950 flex flex-col items-center justify-center">
      <div className="w-full max-w-lg mx-auto px-4">
        {/* Progress dots */}
        <div className="flex items-center justify-center gap-2 mb-8">
          {stepOrder.map((s, i) => (
            <div
              key={s}
              className={`h-1.5 rounded-full transition-all ${
                i <= currentIdx
                  ? 'w-6 bg-teal-500'
                  : 'w-1.5 bg-neutral-300 dark:bg-neutral-700'
              }`}
            />
          ))}
        </div>

        {/* Step content */}
        <div className="bg-white dark:bg-neutral-900 rounded-2xl border border-neutral-200 dark:border-neutral-800 shadow-sm">
          {step === 'welcome' && (
            <Welcome onNext={() => setStep('hardware')} onSkip={handleSkip} />
          )}
          {step === 'hardware' && (
            <HardwareDetection onNext={handleHardwareNext} />
          )}
          {step === 'engine' && hardware && (
            <ChooseEngine
              hardware={hardware}
              selected={engine}
              onSelect={setEngine}
              onNext={handleEngineNext}
              onBack={() => setStep('hardware')}
            />
          )}
          {step === 'model' && hardware && (
            <PickModel
              backend={engine}
              maxVramGb={hardware.gpus.reduce((s, g) => s + g.vram_gb, 0)}
              selectedModel={model}
              onSelect={setModel}
              onNext={handleModelNext}
              onBack={() => setStep('engine')}
            />
          )}
          {step === 'downloading' && (
            <Downloading
              backend={engine}
              model={model}
              onNext={handleDownloadNext}
            />
          )}
          {step === 'ready' && (
            <Ready
              backend={engine}
              model={model}
              onFinish={completeOnboarding}
            />
          )}
        </div>
      </div>
    </div>
  )
}
