import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/States'
import { Tabs, type TabItem } from '../../components/Tabs'
import { useAuth } from '../../lib/auth'
import { ApiKeysPanel } from './ApiKeysPanel'
import { DirectoryPanel } from './DirectoryPanel'
import { WebhooksPanel } from './WebhooksPanel'

// `feature`: the panel is hidden when the account's plan lacks it (the API refuses with feature-not-in-plan too).
const PANELS: (TabItem & { permission: string; feature?: string })[] = [
  { id: 'directory', label: 'Directory', permission: 'integrations.connection.manage', content: <DirectoryPanel /> },
  { id: 'api-keys', label: 'API keys', permission: 'integrations.api_key.manage', feature: 'api_access', content: <ApiKeysPanel /> },
  { id: 'webhooks', label: 'Webhooks', permission: 'integrations.webhook.manage', content: <WebhooksPanel /> },
]

export function IntegrationsPage() {
  const { can, me } = useAuth()
  const features = me?.entitlements.features ?? []
  const tabs = PANELS.filter((p) => can(p.permission) && (!p.feature || features.includes(p.feature)))
  return (
    <>
      <PageHeader title="Integrations" description="Connect partner systems through API keys, webhooks and adapters." />
      {tabs.length ? <Tabs label="Integrations" tabs={tabs} /> : <EmptyState title="Your role cannot manage integrations" />}
    </>
  )
}
