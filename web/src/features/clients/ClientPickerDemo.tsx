import { useState } from 'react'
import { Card, PageHeader } from '../../components/PageHeader'
import { ClientPicker, type ClientSummary } from './ClientPicker'

/** Development-only page (route /dev/client-picker): the picker has no screen of its own until a module
 * mounts it, and the Playwright axe sweep needs a real page to scan it on. Not part of the production build. */
export function ClientPickerDemo() {
  const [client, setClient] = useState<ClientSummary | null>(null)
  return (
    <>
      <PageHeader title="Client picker" description="Shared component preview (development only)." />
      <Card className="max-w-md">
        <ClientPicker label="Client" hint="Search by name, email, phone or member number." value={client} onChange={setClient} />
      </Card>
    </>
  )
}
