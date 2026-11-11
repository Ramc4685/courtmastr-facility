import { useQuery } from '@tanstack/react-query'
import { NavLink, Outlet } from 'react-router-dom'
import { api, type Schemas } from '../../api/client'
import type { Tone } from '../../components/Badge'
import { useAuth } from '../../lib/auth'

export type Payee = Schemas['StaffPayeeOut']
export type TimeEntry = Schemas['TimeEntryOut']
export type Shift = Schemas['ShiftOut']
export type PayrollRun = Schemas['PayrollRunOut']
export type Statement = Schemas['PayStatementOut']

export const RUN_STATUS: Record<string, [string, Tone]> = {
  draft: ['Draft', 'neutral'], calculating: ['Calculating', 'info'], calculated: ['Ready to review', 'warning'],
  finalized: ['Finalized', 'success'], voided: ['Voided', 'neutral'],
}
export const SHIFT_STATUS: Record<string, [string, Tone]> = { draft: ['Draft', 'neutral'], published: ['Published', 'success'], cancelled: ['Cancelled', 'neutral'] }

// Reference lists: one page of 200 covers them. shortcut: no paging past 200, add it when a tenant gets close.
export const useStaffUsers = () => useQuery({ queryKey: ['staff-users', 'all'], queryFn: () => api.get('/api/v1/staff-users', { query: { limit: 200, is_active: true } }) })
export const useJobs = () => useQuery({ queryKey: ['staff', 'jobs'], queryFn: () => api.get('/api/v1/job-classifications', { query: { limit: 200 } }) })
export const usePayees = () => useQuery({ queryKey: ['staff', 'payees'], queryFn: () => api.get('/api/v1/staff-payees', { query: { limit: 200 } }) })

export function useNames() {
  const users = useStaffUsers()
  const jobs = useJobs()
  const user = (id: string | null | undefined) => {
    const u = users.data?.data.find((x) => x.id === id)
    return u ? `${u.first_name} ${u.last_name}`.trim() : '—'
  }
  const job = (id: string | null | undefined) => jobs.data?.data.find((x) => x.id === id)?.name ?? '—'
  const userOptions = (users.data?.data ?? []).map((u) => ({ value: u.id, label: `${u.first_name} ${u.last_name}`.trim() }))
  const jobOptions = (jobs.data?.data ?? []).filter((j) => j.is_active).map((j) => ({ value: j.id, label: j.name }))
  return { user, job, userOptions, jobOptions }
}

export const hours = (minutes: number | null | undefined) => (minutes === null || minutes === undefined ? '—' : `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, '0')}m`)

const LINKS = [
  { to: '/staff-time', label: 'Time clock', permission: 'staff.time_entry.punch', end: true },
  { to: '/staff-time/entries', label: 'Time entries', permission: 'staff.time_entry.read' },
  { to: '/staff-time/shifts', label: 'Shifts', permission: 'staff.shift.manage' },
  { to: '/staff-time/payees', label: 'Trainers & salespeople', permission: 'resources.resource.manage' },
  { to: '/staff-time/payroll', label: 'Payroll', permission: 'staff.payroll_run.create' },
  { to: '/staff-time/setup', label: 'Set-up', permission: 'staff.time_entry.manage' },
]

/** One sidebar entry for staff time and pay; its screens share this second-level navigation. */
export function StaffTimeLayout() {
  const { can } = useAuth()
  return (
    <>
      <nav aria-label="Staff time and pay" className="-mt-2 mb-6 flex gap-1 overflow-x-auto border-b border-border">
        {LINKS.filter((l) => can(l.permission)).map((l) => (
          <NavLink
            key={l.to}
            to={l.to}
            end={l.end}
            className={({ isActive }) => `-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium ${isActive ? 'border-primary text-primary' : 'border-transparent text-muted hover:text-fg'}`}
          >
            {l.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </>
  )
}
