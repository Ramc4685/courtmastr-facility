import type { Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'

export function StaffStatusBadge({ user }: { user: Schemas['StaffUserOut'] }) {
  if (!user.is_active) return <Badge tone="neutral">Deactivated</Badge>
  if (user.identity_status === 'invited') return <Badge tone="info">Invited</Badge>
  return <Badge tone="success">Active</Badge>
}
