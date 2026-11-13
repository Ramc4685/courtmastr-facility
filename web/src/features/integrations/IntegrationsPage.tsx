import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/States'
import { Tabs, type TabItem } from '../../components/Tabs'
import { useAuth } from '../../lib/auth'
import { ApiKeysPanel } from './ApiKeysPanel'
import { CalendarFeedsPanel } from './CalendarFeedsPanel'
import { ConnectionsPanel } from './ConnectionsPanel'
import { DirectoryPanel } from './DirectoryPanel'
import { WebhooksPanel } from './WebhooksPanel'

// `permission: null`: any staff member (calendar feeds are personal). `feature`: the panel is hidden when the account's plan lacks it (the API refuses with feature-not-in-plan too).
const PANELS: (TabItem & { permission: string | null; feature?: string })[] = [
  { id: 'directory', label: 'Directory', permission: 'integrations.connection.manage', content: <DirectoryPanel /> },
  { id: 'connections', label: 'Connections', permission: 'integrations.connection.manage', content: <ConnectionsPanel /> },
  { id: 'api-keys', label: 'API keys', permission: 'integrations.api_key.manage', feature: 'api_access', content: <ApiKeysPanel /> },
  { id: 'webhooks', label: 'Webhooks', permission: 'integrations.webhook.manage', content: <WebhooksPanel /> },
  { id: 'calendar-feeds', label: 'Calendar feeds', permission: null, content: <CalendarFeedsPanel /> },
]

export function IntegrationsPage() {
  const { can, me } = useAuth()
  const features = me?.entitlements.features ?? []
  const tabs = PANELS.filter((p) => (p.permission === null || can(p.permission)) && (!p.feature || features.includes(p.feature)))
  return (
    <>
      <PageHeader title="Integrations" description="Connect partner systems, accounting, online meetings and your calendar." />
      {tabs.length ? <Tabs label="Integrations" tabs={tabs} /> : <EmptyState title="Your role cannot manage integrations" />}
    </>
  )
}
