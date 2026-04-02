import { Check, MessageSquare, Settings, Code } from 'lucide-react'
import { Button } from '../../../components/ui'

interface Props {
  backend: string
  model: string
  onFinish: () => void
}

export function Ready({ backend, model, onFinish }: Props) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-16 px-6">
      <div className="w-16 h-16 rounded-full bg-success flex items-center justify-center mb-6">
        <Check className="w-8 h-8 text-white" />
      </div>
      <h2 className="text-h3 text-content-primary mb-2">
        Nova is Ready
      </h2>
      <p className="text-compact text-content-secondary mb-2">
        {backend === 'cloud'
          ? 'Cloud providers are configured and ready to go.'
          : (
            <>
              <span className="font-medium text-content-primary">{model}</span>
              {' '}is running via{' '}
              <span className="font-medium text-content-primary">{backend}</span>.
            </>
          )
        }
      </p>
      <p className="text-caption text-content-tertiary mb-8 flex items-center gap-1">
        <Settings className="w-3 h-3" />
        You can change models and backends anytime in Settings.
      </p>
      <div className="flex gap-3">
        <Button
          size="lg"
          icon={<MessageSquare className="w-4 h-4" />}
          onClick={onFinish}
        >
          Start Chatting
        </Button>
        <Button
          size="lg"
          variant="secondary"
          icon={<Code className="w-4 h-4" />}
          onClick={() => { window.location.href = '/editors' }}
        >
          Connect Your Editor
        </Button>
      </div>
    </div>
  )
}
