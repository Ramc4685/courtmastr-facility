import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../api/client'
import { Button } from '../../components/Button'
import { useToast } from '../../components/Toast'
import { useWorkingLocation } from '../scheduling/location'

/** Check a client in from their profile (CHK-03), at the location the staff member is working at. */
export function ProfileCheckInButton({ clientId }: { clientId: string }) {
  const { location } = useWorkingLocation()
  const toast = useToast()
  const qc = useQueryClient()
  const run = useMutation({
    mutationFn: () => api.post('/api/v1/check-ins', { body: { client_id: clientId, location_id: location?.id ?? '', channel: 'client_profile', override: false } }),
    onSuccess: (done) => {
      const denied = done.check_in.result === 'denied'
      toast(denied ? 'error' : 'success', denied ? `Entry denied at ${location?.name}: recorded.` : `Checked in at ${location?.name}.`)
      qc.invalidateQueries({ queryKey: ['check-ins'] })
    },
    onError: (e) => toast('error', e instanceof ApiError ? e.message : 'Check-in failed.'),
  })
  if (!location) return null
  return (
    <Button variant="secondary" loading={run.isPending} onClick={() => run.mutate()}>
      Check in
    </Button>
  )
}
