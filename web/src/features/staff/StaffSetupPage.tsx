import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, fieldErrors } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState } from '../../components/States'
import { Tabs } from '../../components/Tabs'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { parseMoney, today } from '../billing/money'
import { FormDialog, ListTable, Money, MoneyInput, TextArea } from '../billing/shared'
import { useJobs, useNames } from './shared'

type Job = { id: string; name: string; is_active: boolean }

function Jobs() {
  const qc = useQueryClient()
  const jobs = useJobs()
  const [editing, setEditing] = useState<Job | 'new' | null>(null)
  const [name, setName] = useState('')
  const done = () => void qc.invalidateQueries({ queryKey: ['staff', 'jobs'] })
  const save = useMutation({
    mutationFn: () =>
      editing && editing !== 'new'
        ? api.patch('/api/v1/job-classifications/{job_classification_id}', { path: { job_classification_id: editing.id }, body: { name } })
        : api.post('/api/v1/job-classifications', { body: { name } }),
    onSuccess: () => {
      done()
      setEditing(null)
    },
  })
  const toggle = useMutation({ mutationFn: (j: Job) => api.patch('/api/v1/job-classifications/{job_classification_id}', { path: { job_classification_id: j.id }, body: { is_active: !j.is_active } }), onSuccess: done })
  const open = (j: Job | 'new') => {
    setName(j === 'new' ? '' : j.name)
    setEditing(j)
  }
  return (
    <div className="space-y-3">
      <Button onClick={() => open('new')}>New job</Button>
      {jobs.error && <ErrorState error={jobs.error} />}
      <ListTable
        caption="Jobs"
        rows={jobs.data?.data ?? []}
        rowKey={(j) => j.id}
        empty={<EmptyState title="No jobs yet" />}
        columns={[
          { header: 'Name', cell: (j) => j.name },
          { header: 'Status', cell: (j) => (j.is_active ? <Badge tone="success">Active</Badge> : <Badge>Archived</Badge>) },
          {
            header: 'Actions', className: 'text-right',
            cell: (j) => (
              <div className="flex justify-end gap-1">
                <Button size="sm" variant="ghost" aria-label={`Rename ${j.name}`} onClick={() => open(j)}>Rename</Button>
                <Button size="sm" variant="ghost" aria-label={`${j.is_active ? 'Archive' : 'Restore'} ${j.name}`} onClick={() => toggle.mutate(j)}>{j.is_active ? 'Archive' : 'Restore'}</Button>
              </div>
            ),
          },
        ]}
      />
      {editing && (
        <FormDialog title={editing === 'new' ? 'New job' : 'Rename job'} submitLabel="Save" busy={save.isPending} error={save.error} onClose={() => setEditing(null)} onSubmit={() => save.mutate()}>
          <Input label="Name" required value={name} error={fieldErrors(save.error).name} onChange={(ev) => setName(ev.target.value)} />
        </FormDialog>
      )}
    </div>
  )
}

function HourlyRates() {
  const qc = useQueryClient()
  const names = useNames()
  const [user, setUser] = useState('')
  const [adding, setAdding] = useState(false)
  const [f, setF] = useState({ job_classification_id: '', rate: '', effective_from_on: today() })
  const key = ['staff', 'hourly', user]
  const rates = useQuery({ queryKey: key, queryFn: () => api.get('/api/v1/staff-users/{staff_user_id}/hourly-rates', { path: { staff_user_id: user } }), enabled: Boolean(user) })
  const add = useMutation({
    mutationFn: () => api.post('/api/v1/staff-users/{staff_user_id}/hourly-rates', { path: { staff_user_id: user }, body: { job_classification_id: f.job_classification_id, rate_minor: parseMoney(f.rate) ?? 0, effective_from_on: f.effective_from_on } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: key })
      setAdding(false)
    },
  })
  const remove = useMutation({
    mutationFn: (id: string) => api.delete('/api/v1/staff-users/{staff_user_id}/hourly-rates/{staff_hourly_rate_id}', { path: { staff_user_id: user, staff_hourly_rate_id: id } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: key }),
  })
  const e = fieldErrors(add.error)
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <Select label="Staff member" value={user} placeholder="Choose" onChange={(ev) => setUser(ev.target.value)} options={names.userOptions} />
        {user && <Button onClick={() => setAdding(true)}>Add rate</Button>}
      </div>
      {rates.error && <ErrorState error={rates.error} />}
      {remove.error && <ErrorState error={remove.error} />}
      {user && (
        <ListTable
          caption="Hourly rates"
          rows={rates.data ?? []}
          rowKey={(r) => r.id}
          empty={<EmptyState title="No hourly rates">Without a rate this person cannot clock in.</EmptyState>}
          columns={[
            { header: 'Job', cell: (r) => names.job(r.job_classification_id) },
            { header: 'Rate', cell: (r) => <Money minor={r.rate_minor} /> },
            { header: 'From', cell: (r) => r.effective_from_on },
            { header: 'Actions', className: 'text-right', cell: (r) => <Button size="sm" variant="ghost" aria-label={`Delete rate for ${names.job(r.job_classification_id)} from ${r.effective_from_on}`} onClick={() => remove.mutate(r.id)}>Delete</Button> },
          ]}
        />
      )}
      {adding && (
        <FormDialog title={`Hourly rate for ${names.user(user)}`} submitLabel="Add rate" busy={add.isPending} error={add.error} onClose={() => setAdding(false)} onSubmit={() => add.mutate()}>
          <Select label="Job" required value={f.job_classification_id} placeholder="Choose" error={e.job_classification_id} onChange={(ev) => setF({ ...f, job_classification_id: ev.target.value })} options={names.jobOptions} />
          <MoneyInput label="Per hour" required value={f.rate} error={e.rate_minor} onChange={(ev) => setF({ ...f, rate: ev.target.value })} />
          <Input label="Effective from" type="date" required value={f.effective_from_on} error={e.effective_from_on} onChange={(ev) => setF({ ...f, effective_from_on: ev.target.value })} />
        </FormDialog>
      )}
    </div>
  )
}

function Settings() {
  const qc = useQueryClient()
  const toast = useToast()
  const settings = useQuery({ queryKey: ['staff', 'settings'], queryFn: () => api.get('/api/v1/staff-settings') })
  const [f, setF] = useState<{ restricted: boolean; networks: string; basis: string; period: string } | null>(null)
  const s = settings.data
  const v = f ?? { restricted: s?.is_time_clock_network_restricted ?? false, networks: (s?.time_clock_networks ?? []).join('\n'), basis: s?.default_commission_basis ?? 'paid', period: s?.pay_period ?? 'biweekly' }
  const save = useMutation({
    mutationFn: () =>
      api.put('/api/v1/staff-settings', {
        body: {
          is_time_clock_network_restricted: v.restricted,
          time_clock_networks: v.networks.split(/\s+/).filter(Boolean),
          default_commission_basis: v.basis as 'paid',
          pay_period: v.period as 'biweekly',
          pay_period_anchor_on: s?.pay_period_anchor_on ?? null,
        },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['staff', 'settings'] })
      setF(null)
      toast('success', 'Settings saved.')
    },
  })
  const e = fieldErrors(save.error)
  if (settings.error) return <ErrorState error={settings.error} />
  return (
    <Card title="Time clock and pay">
      <form
        className="max-w-lg space-y-4"
        onSubmit={(ev) => {
          ev.preventDefault()
          save.mutate()
        }}
      >
        <Checkbox label="Only accept clock-ins from these networks" checked={v.restricted} onChange={(ev) => setF({ ...v, restricted: ev.target.checked })} />
        <TextArea label="Networks" hint="One address range per line, for example 203.0.113.0/24." value={v.networks} error={e.time_clock_networks} onChange={(t) => setF({ ...v, networks: t })} />
        <Select label="Commission is earned when the sale is" value={v.basis} onChange={(ev) => setF({ ...v, basis: ev.target.value })} options={[{ value: 'paid', label: 'Paid' }, { value: 'invoiced', label: 'Invoiced' }]} />
        <Select
          label="Pay period"
          value={v.period}
          onChange={(ev) => setF({ ...v, period: ev.target.value })}
          options={[{ value: 'weekly', label: 'Weekly' }, { value: 'biweekly', label: 'Every two weeks' }, { value: 'semi_monthly', label: 'Twice a month' }, { value: 'monthly', label: 'Monthly' }]}
        />
        <Button type="submit" loading={save.isPending}>Save settings</Button>
      </form>
    </Card>
  )
}

/** Jobs, hourly rates and time clock settings (STF-07, STF-08). */
export function StaffSetupPage() {
  const { can } = useAuth()
  const tabs = [
    { id: 'jobs', label: 'Jobs', content: <Jobs /> },
    ...(can('staff.pay_rate.read') ? [{ id: 'rates', label: 'Hourly rates', content: <HourlyRates /> }] : []),
    { id: 'settings', label: 'Settings', content: <Settings /> },
  ]
  return (
    <>
      <PageHeader title="Staff set-up" description="Jobs people clock in as, what they earn per hour, and time clock rules." />
      <Tabs label="Staff set-up" tabs={tabs} />
    </>
  )
}
