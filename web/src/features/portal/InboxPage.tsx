import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { EmptyState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { formatDateTime } from '../../lib/format'
import { PortalPage } from './PortalApp'
import { usePortal } from './shared'

type Item = Schemas['PortalInboxItem']

/** Unread count for the nav badge: the acting-for member's inbox only (each item belongs to one recipient). */
export const useUnreadCount = (clientId: string) =>
  useQuery({ queryKey: ['portal', 'inbox', 'unread', clientId], queryFn: () => api.get('/api/v1/portal/inbox/unread-count', { query: { client_id: clientId } }), staleTime: 30_000 })

export function InboxBadge() {
  const unread = useUnreadCount(usePortal().actingFor.id).data?.unread ?? 0
  if (!unread) return null
  return (
    <span className="ml-1.5 inline-flex min-w-5 items-center justify-center rounded-full bg-primary px-1.5 text-xs font-semibold text-on-primary">
      {unread}
      <span className="sr-only"> unread</span>
    </span>
  )
}

// Staff-entered links: only http(s) become clickable.
const safeLink = (url: string | null | undefined) => (url && /^https?:\/\//i.test(url) ? url : null)

export function InboxPage() {
  const qc = useQueryClient()
  const toast = useToast()
  const { actingFor } = usePortal()
  const paging = useKeysetQuery(['portal', 'inbox', 'list', actingFor.id], (cursor) => api.get('/api/v1/portal/inbox', { query: { client_id: actingFor.id, cursor, limit: 25 } }))
  const read = useMutation({
    mutationFn: (i: Item) => api.post('/api/v1/portal/inbox/{inbox_item_id}/read', { path: { inbox_item_id: i.id } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['portal', 'inbox'] }),
    onError: (e) => toast('error', e.message),
  })
  return (
    <PortalPage title="Inbox" description="Announcements and notices from the facility.">
      <Table
        caption="Inbox"
        paging={paging}
        rowKey={(i) => i.id}
        empty={<EmptyState title="Nothing here yet">Announcements from the facility will show up here.</EmptyState>}
        columns={[
          {
            header: 'Message',
            cell: (i) => (
              <div className="max-w-xl">
                <p className={i.read_at ? 'font-medium' : 'font-semibold'}>{i.title}</p>
                <p className="whitespace-pre-wrap text-muted">{i.body}</p>
                {safeLink(i.link_url) && (
                  <a className="text-primary underline-offset-2 hover:underline" href={safeLink(i.link_url) ?? undefined} target="_blank" rel="noopener noreferrer">
                    Learn more
                  </a>
                )}
              </div>
            ),
          },
          { header: 'Received', cell: (i) => formatDateTime(i.created_at) },
          {
            header: 'Status',
            className: 'text-right',
            cell: (i) =>
              i.read_at ? (
                <Badge>Read</Badge>
              ) : (
                <Button size="sm" variant="secondary" aria-label={`Mark as read: ${i.title}`} loading={read.isPending && read.variables?.id === i.id} onClick={() => read.mutate(i)}>
                  Mark as read
                </Button>
              ),
          },
        ]}
      />
    </PortalPage>
  )
}
