import { useQuery } from '@tanstack/react-query'
import { NavLink, Outlet } from 'react-router-dom'
import { api, type Schemas } from '../../api/client'
import type { Tone } from '../../components/Badge'
import { useAuth } from '../../lib/auth'

export type Sale = Schemas['PosSaleDetail']
export type Product = Schemas['ProductOut']
export type Register = Schemas['RegisterOut']

export const SALE_STATUS: Record<string, [string, Tone]> = {
  draft: ['Open cart', 'info'],
  completed: ['Completed', 'success'],
  abandoned: ['Abandoned', 'neutral'],
}
export const RETURN_STATE: Record<string, [string, Tone]> = {
  none: ['', 'neutral'],
  partial: ['Part returned', 'warning'],
  full: ['Returned', 'neutral'],
}
export const TENDER_STATUS: Record<string, [string, Tone]> = {
  pending: ['Waiting on processor', 'warning'],
  captured: ['Taken', 'success'],
  failed: ['Failed', 'danger'],
  removed: ['Removed', 'neutral'],
}
export const LOAN_STATUS: Record<string, [string, Tone]> = {
  open: ['Out', 'info'],
  returned: ['Returned', 'success'],
  lost: ['Lost', 'danger'],
}

// Reference lists: one page of 200 covers them.
export const useRegisters = () => useQuery({ queryKey: ['pos', 'registers', 'all'], queryFn: () => api.get('/api/v1/registers', { query: { limit: 200 } }) })
export const useCategories = () => useQuery({ queryKey: ['pos', 'categories', 'all'], queryFn: () => api.get('/api/v1/product-categories', { query: { limit: 200 } }) })
export const useBrands = () => useQuery({ queryKey: ['pos', 'brands', 'all'], queryFn: () => api.get('/api/v1/product-brands', { query: { limit: 200 } }) })
export const useSuppliers = () => useQuery({ queryKey: ['pos', 'suppliers', 'all'], queryFn: () => api.get('/api/v1/product-suppliers', { query: { limit: 200 } }) })
export const useEquipmentCategories = () => useQuery({ queryKey: ['pos', 'equipment-categories', 'all'], queryFn: () => api.get('/api/v1/equipment-categories', { query: { limit: 200 } }) })

export const options = (rows: { id: string; name: string }[] | undefined) => (rows ?? []).map((r) => ({ value: r.id, label: r.name }))

const LINKS = [
  { to: '/pos', label: 'Register', permission: 'pos.sale.create', end: true },
  { to: '/pos/sales', label: 'Transactions', permission: 'pos.sale.read' },
  { to: '/pos/products', label: 'Products & stock', permission: 'pos.sale.read' },
  { to: '/pos/equipment', label: 'Equipment', permission: 'pos.equipment.rent' },
  { to: '/pos/drawers', label: 'Drawers', permission: 'pos.drawer.operate' },
  { to: '/pos/reports', label: 'Reports', permission: 'reporting.pos.run' },
  { to: '/pos/setup', label: 'Set-up', permission: 'pos.register.manage' },
]

/** One sidebar entry for the point of sale; its screens share this second-level navigation. */
export function PosLayout() {
  const { can } = useAuth()
  return (
    <>
      <nav aria-label="Point of sale" className="-mt-2 mb-6 flex gap-1 overflow-x-auto border-b border-border">
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
