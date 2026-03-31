import { Plug, Server } from 'lucide-react'
import { useTabHash } from '../hooks/useTabHash'
import { PageHeader } from '../components/layout/PageHeader'
import { Tabs } from '../components/ui'
import { MCPContent } from './MCP'
import { AgentEndpointsContent } from './AgentEndpoints'

type IntegrationTab = 'mcp' | 'agents'

const TABS = [
  { id: 'mcp' as const, label: 'MCP Servers', icon: Plug },
  { id: 'agents' as const, label: 'Agent Endpoints', icon: Server },
]

const HELP_ENTRIES = [
  { term: 'MCP', definition: 'Model Context Protocol -- an open standard for connecting AI models to external tools and data sources.' },
  { term: 'Transport', definition: 'How Nova communicates with the MCP server -- stdio runs it as a subprocess, HTTP connects to a remote URL.' },
  { term: 'A2A', definition: 'Google Agent-to-Agent protocol for cross-platform agent delegation.' },
  { term: 'ACP', definition: 'BeeAI Agent Communication Protocol for structured agent interoperability.' },
]

export function Integrations() {
  const [activeTab, setActiveTab] = useTabHash<IntegrationTab>('mcp', ['mcp', 'agents'])

  return (
    <div className="space-y-6">
      <PageHeader
        title="Integrations"
        description="Connect Nova to external tool servers and agent endpoints"
        helpEntries={HELP_ENTRIES}
      />
      <Tabs tabs={TABS} activeTab={activeTab} onChange={(id) => setActiveTab(id as IntegrationTab)} />
      {activeTab === 'mcp' && <MCPContent />}
      {activeTab === 'agents' && <AgentEndpointsContent />}
    </div>
  )
}
