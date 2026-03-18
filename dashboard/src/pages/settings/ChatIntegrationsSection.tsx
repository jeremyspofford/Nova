import { useState, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { MessageSquare, ExternalLink } from 'lucide-react'
import { getChatIntegrationsStatus } from '../../api-recovery'
import { TelegramSetup, SlackSetup } from '../ChatIntegrations'
import { StatusBadge as RemoteStatusBadge } from '../RemoteAccess'
import { Section, Tabs } from '../../components/ui'

export function ChatIntegrationsSection() {
  const [tab, setTab] = useState('telegram')
  const queryClient = useQueryClient()

  const { data: status } = useQuery({
    queryKey: ['chat-integrations-status'],
    queryFn: getChatIntegrationsStatus,
    refetchInterval: 10_000,
  })

  const refresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['chat-integrations-status'] })
  }, [queryClient])

  const defaultAdapter = { configured: false, container: { name: 'chat-bridge', container_name: null, status: 'not_found', health: 'unknown', running: false } }
  const tgStatus = status?.telegram ?? defaultAdapter
  const slackStatus = status?.slack ?? defaultAdapter

  return (
    <Section
      icon={MessageSquare}
      title="Chat Integrations"
      description={<>Connect Nova to external chat platforms. Messages are relayed through the chat-bridge service. <a href="https://arialabs.ai/nova/docs/services/chat-bridge/" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">Setup guide <ExternalLink size={12} /></a></>}
    >
      <div className="flex gap-4 text-compact mb-3">
        <span className="flex items-center gap-1.5 text-content-tertiary">
          Telegram: <RemoteStatusBadge configured={tgStatus.configured} running={tgStatus.container.running} />
        </span>
        <span className="flex items-center gap-1.5 text-content-tertiary">
          Slack: <RemoteStatusBadge configured={slackStatus.configured} running={slackStatus.container.running} />
        </span>
      </div>

      <Tabs
        tabs={[
          { id: 'telegram', label: 'Telegram' },
          { id: 'slack', label: 'Slack' },
        ]}
        activeTab={tab}
        onChange={setTab}
        className="mb-4"
      />

      <div className="max-w-xl">
        {tab === 'telegram' && <TelegramSetup status={tgStatus} slackConfigured={slackStatus.configured} onDone={refresh} />}
        {tab === 'slack' && <SlackSetup status={slackStatus} telegramConfigured={tgStatus.configured} onDone={refresh} />}
      </div>
    </Section>
  )
}
