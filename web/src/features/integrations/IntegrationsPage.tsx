import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/States'
import { Tabs, type TabItem } from '../../components/Tabs'
import { useAuth } from '../../lib/auth'
import { ApiKeysPanel } from './ApiKeysPanel'
import { DirectoryPanel } from './DirectoryPanel'
import { WebhooksPanel } from './WebhooksPanel'

const PANELS: (TabItem & { permission: string })[] = [
  { id: 'directory', label: 'Directory', permission: 'integrations.connection.manage', content: <DirectoryPanel /> },
  { id: 'api-keys', label: 'API keys', permission: 'integrations.api_key.manage', content: <ApiKeysPanel /> },
  { id: 'webhooks', label: 'Webhooks', permission: 'integrations.webhook.manage', content: <WebhooksPanel /> },
]

export function IntegrationsPage() {
  const { can } = useAuth()
  const tabs = PANELS.filter((p) => can(p.permission))
  return (
    <>
      <PageHeader title="Integrations" description="Connect partner systems through API keys, webhooks and adapters." />
      {tabs.length ? <Tabs label="Integrations" tabs={tabs} /> : <EmptyState title="Your role cannot manage integrations" />}
    </>
  )
}
