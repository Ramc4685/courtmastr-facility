import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, fieldErrors } from '../../api/client'
import { Button } from '../../components/Button'
import { Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useMe } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'
import { FormError, ListTable, LocationSelect } from '../billing/shared'
import { useNames } from './shared'

/** Clock in and out with your password (STF-07), and your published shifts (STF-15). */
export function ClockPage() {
  const me = useMe()
  const qc = useQueryClient()
  const toast = useToast()
  const names = useNames()
  const [location, setLocation] = useState(me.primary_location_id ?? me.locations?.[0]?.id ?? '')
  const [job, setJob] = useState('')
  const [password, setPassword] = useState('')
  const state = useQuery({
    queryKey: ['staff', 'clock', location],
    queryFn: () => api.get('/api/v1/time-entries/current', { query: { location_id: location } }),
    enabled: Boolean(location),
  })
  const shifts = useQuery({ queryKey: ['staff', 'my-shifts'], queryFn: () => api.get('/api/v1/my-shifts', { query: { limit: 20 } }) })
  const open = state.data?.open_entry ?? null
  const punch = useMutation({
    mutationFn: () =>
      open
        ? api.post('/api/v1/time-entries/clock-out', { body: { password } })
        : api.post('/api/v1/time-entries/clock-in', { body: { location_id: location, job_classification_id: job || (state.data?.job_classifications[0]?.id ?? ''), password } }),
    onSuccess: () => {
      setPassword('')
      void qc.invalidateQueries({ queryKey: ['staff'] })
      toast('success', open ? 'Clocked out.' : 'Clocked in.')
    },
  })
  const e = fieldErrors(punch.error)
  return (
    <>
      <PageHeader title="Time clock" description="Clock in when you start and out when you finish. Your password confirms it is you." />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title={open ? 'You are clocked in' : 'You are clocked out'}>
          {state.isLoading && <LoadingState />}
          {state.error && <ErrorState error={state.error} />}
          {state.data && (
            <form
              className="space-y-4"
              onSubmit={(ev) => {
                ev.preventDefault()
                punch.mutate()
              }}
            >
              {open ? (
                <p className="text-sm" role="status">Since {formatDateTime(open.clock_in_at)} as {names.job(open.job_classification_id)}.</p>
              ) : (
                <>
                  <LocationSelect value={location} onChange={setLocation} />
                  <Select
                    label="Job"
                    value={job || (state.data.job_classifications[0]?.id ?? '')}
                    error={e.job_classification_id}
                    onChange={(ev) => setJob(ev.target.value)}
                    options={state.data.job_classifications.map((j) => ({ value: j.id, label: j.name }))}
                  />
                  {state.data.job_classifications.length === 0 && <p className="text-sm text-muted">No job has an hourly rate for you here yet. Ask a manager.</p>}
                  {!state.data.is_network_allowed && <p className="text-sm text-danger">This location only accepts clock-ins from its own network.</p>}
                </>
              )}
              <Input label="Password" type="password" autoComplete="current-password" required value={password} error={e.password} onChange={(ev) => setPassword(ev.target.value)} />
              <FormError error={punch.error} />
              <Button type="submit" loading={punch.isPending} disabled={!open && state.data.job_classifications.length === 0}>{open ? 'Clock out' : 'Clock in'}</Button>
            </form>
          )}
        </Card>
        <Card title="My shifts">
          <ListTable
            caption="My shifts"
            rows={shifts.data?.data ?? []}
            rowKey={(s) => s.id}
            empty={<EmptyState title="No published shifts" />}
            columns={[
              { header: 'Starts', cell: (s) => formatDateTime(s.starts_at) },
              { header: 'Ends', cell: (s) => formatDateTime(s.ends_at) },
              { header: 'Job', cell: (s) => names.job(s.job_classification_id) },
            ]}
          />
        </Card>
      </div>
    </>
  )
}
