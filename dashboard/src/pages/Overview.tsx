import { useQuery } from '@tanstack/react-query'
import {
  Activity, MessageSquare, ListTodo, AlertTriangle,
  Brain, Boxes, TrendingUp, TrendingDown, Minus,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { PageHeader } from '../components/layout/PageHeader'
import { Card, Metric, Badge, StatusDot, Skeleton } from '../components/ui'
import { useDebug } from '../stores/debug-store'
import {
  getPipelineStats, getFrictionStats, getActivityFeed,
  type ActivityEvent,
} from '../api'

const HELP_ENTRIES = [
  { term: 'Sprint Health', definition: "A snapshot of today's task pipeline performance — success rate, submissions, failures, and unresolved issues." },
  { term: 'Friction', definition: 'Issues, bugs, and rough edges discovered while using Nova — logged manually or automatically from pipeline failures.' },
  { term: 'Pipeline', definition: "Nova's 5-stage task execution chain — Context, Task, Guardrail, Code Review, and Decision agents working in sequence." },
  { term: 'Engrams', definition: "Individual units of memory in Nova's knowledge graph — facts, preferences, procedures, and entities learned from conversations." },
]

const SEVERITY_ICON: Record<string, React.ReactNode> = {
  info: <Activity size={12} className="text-blue-400" />,
  warning: <AlertTriangle size={12} className="text-amber-400" />,
  error: <AlertTriangle size={12} className="text-red-400" />,
}

export default function Overview() {
  const { isDebug } = useDebug()

  const { data: pipelineStats, isLoading: statsLoading } = useQuery({
    queryKey: ['pipeline-stats'],
    queryFn: getPipelineStats,
    staleTime: 10_000,
  })

  const { data: frictionStats } = useQuery({
    queryKey: ['friction-stats'],
    queryFn: getFrictionStats,
    staleTime: 10_000,
    enabled: isDebug,
  })

  const { data: activity, isLoading: activityLoading } = useQuery({
    queryKey: ['activity-feed', 8],
    queryFn: () => getActivityFeed(8),
    staleTime: 10_000,
  })

  const successRate = pipelineStats
    ? (pipelineStats.completed_this_week + pipelineStats.failed_this_week) > 0
      ? Math.round((pipelineStats.completed_this_week / (pipelineStats.completed_this_week + pipelineStats.failed_this_week)) * 100)
      : null
    : null

  const rateIcon = successRate === null ? <Minus size={12} />
    : successRate >= 90 ? <TrendingUp size={12} className="text-emerald-400" />
    : <TrendingDown size={12} className="text-red-400" />

  return (
    <div className="space-y-6">
      <PageHeader title="Overview" description="System health and recent activity at a glance." helpEntries={HELP_ENTRIES} />

      {/* Sprint Health */}
      <h3 className="text-compact font-semibold text-content-primary">Sprint Health</h3>
      <p className="text-caption text-content-tertiary -mt-4">Pipeline success rate, throughput, and open issues for the current period.</p>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {statsLoading ? (
          [1, 2, 3, 4].map(i => (
            <Card key={i} className="p-4"><Skeleton lines={2} /></Card>
          ))
        ) : (
          <>
            <Card className="p-4 animate-fade-in-up-delay-1">
              <Metric
                label="Success Rate (7d)"
                value={successRate !== null ? `${successRate}%` : '--'}
                icon={rateIcon}
                tooltip="Percentage of pipeline tasks that completed successfully in the last 7 days."
              />
            </Card>
            <Card className="p-4 animate-fade-in-up-delay-2">
              <Metric label="Submitted Today" value={pipelineStats?.submitted_today ?? 0} tooltip="Tasks submitted to the pipeline queue today." />
            </Card>
            <Card className="p-4 animate-fade-in-up-delay-3">
              <Metric label="Failed Today" value={pipelineStats?.failed_today ?? 0} tooltip="Tasks that failed or were aborted today." />
            </Card>
            {isDebug && (
              <Card className="p-4 animate-fade-in-up-delay-4">
                <Metric label="Open Friction" value={frictionStats?.open_count ?? 0} tooltip="Unresolved friction log entries — bugs and issues found during use." />
              </Card>
            )}
          </>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Activity */}
        <Card className="p-5">
          <h3 className="text-compact font-semibold text-content-primary mb-1">Recent Activity</h3>
          <p className="text-caption text-content-tertiary mb-4">Events from across all services — task completions, failures, and system changes.</p>
          {activityLoading ? (
            <Skeleton lines={5} />
          ) : !activity?.length ? (
            <p className="text-caption text-content-tertiary">No activity yet.</p>
          ) : (
            <div className="space-y-2.5">
              {activity.map((evt) => (
                <ActivityRow key={evt.id} event={evt} />
              ))}
            </div>
          )}
        </Card>

        {/* Quick Navigation */}
        <div className="grid grid-cols-2 gap-4">
          <NavCard to="/chat" icon={MessageSquare} label="Chat" description="Talk to Nova" />
          <NavCard to="/tasks" icon={ListTodo} label="Tasks" description="Pipeline queue" />
          {isDebug && <NavCard to="/friction" icon={AlertTriangle} label="Friction" description="Issue tracker" />}
          <NavCard to="/engrams" icon={Brain} label="Memory" description="Engram explorer" />
          <NavCard to="/pods" icon={Boxes} label="Pods" description="Agent pipelines" />
          <NavCard to="/settings" icon={Activity} label="Settings" description="Configuration" />
        </div>
      </div>
    </div>
  )
}


function ActivityRow({ event }: { event: ActivityEvent }) {
  const timeAgo = formatTimeAgo(event.created_at)
  return (
    <div className="flex items-start gap-2.5 text-caption">
      <div className="mt-0.5 shrink-0">
        {SEVERITY_ICON[event.severity] ?? <Activity size={12} className="text-content-tertiary" />}
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-content-secondary truncate">{event.summary}</p>
        <p className="text-content-tertiary">{event.service} · {timeAgo}</p>
      </div>
    </div>
  )
}


function NavCard({
  to, icon: Icon, label, description,
}: {
  to: string; icon: React.ElementType; label: string; description: string
}) {
  return (
    <Link to={to}>
      <Card className="p-4 hover:bg-surface-elevated transition-colors cursor-pointer h-full">
        <Icon size={20} className="text-accent/50 mb-2" />
        <p className="text-compact font-medium text-content-primary">{label}</p>
        <p className="text-caption text-content-tertiary">{description}</p>
      </Card>
    </Link>
  )
}


function formatTimeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(ms / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}
