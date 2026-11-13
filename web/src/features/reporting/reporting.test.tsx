import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { page, renderAsStaff, SCREEN } from '../scheduling/testing'
import { formatCell } from './queries'
import { ReportRunPage } from './ReportRunPage'
import { DashboardTiles } from './DashboardTiles'
import { ReportsPage } from './ReportsPage'

const PERIOD = { anyOf: [{ enum: ['today', 'this_month', 'last_30_days'], type: 'string' }, { type: 'null' }], title: 'Period' }
const deposits = {
  key: 'deposits', name: 'Deposits', description: 'Money received, by tender.', category: 'financial', required_permission: 'reporting.financial.run',
  required_entitlement: null, date_basis: 'received_on', supports_detail: true, export_formats: ['csv'], is_stub: false, features: [],
  params_schema: { properties: { location_ids: { anyOf: [{ type: 'array', items: { type: 'string', format: 'uuid' } }, { type: 'null' }] }, period: PERIOD,
    from_on: { anyOf: [{ type: 'string', format: 'date' }, { type: 'null' }], title: 'From' }, to_on: { anyOf: [{ type: 'string', format: 'date' }, { type: 'null' }], title: 'To' } } },
  columns: [{ key: 'tender', label: 'Tender', type: 'text' }, { key: 'amount_minor', label: 'Amount', type: 'money' }],
  total_columns: [{ key: 'amount_minor', label: 'Received', type: 'money' }],
  detail_columns: [{ key: 'receipt_number', label: 'Receipt', type: 'text' }, { key: 'amount_minor', label: 'Amount', type: 'money' }],
}
const timeClock = { ...deposits, key: 'time_clock', name: 'Hours worked', description: 'Clocked time by person.', category: 'time_clock', supports_detail: false }
const run = { id: 'run1', report_key: 'deposits', saved_report_id: null, params: { period: 'this_month' }, status: 'succeeded', row_count: 1, totals: { amount_minor: 2500 },
  error: null, started_at: null, finished_at: null, expires_at: '2026-11-12T00:00:00Z', created_at: '2026-11-11T00:00:00Z', updated_at: '2026-11-11T00:00:00Z' }
const rows = (data: object[], columns = deposits.columns) => ({ status: 200, body: { columns, data, totals: run.totals, page: { next_cursor: null, has_more: false, total: data.length } } })
const FINANCIAL = ['reporting.financial.run', 'reporting.report.export']

afterEach(() => vi.unstubAllGlobals())

describe('report centre', SCREEN, () => {
  it('lists the reports the caller may run, by family, with saved reports and exports', async () => {
    renderAsStaff(<ReportsPage />, FINANCIAL, {
      'GET /api/v1/report-definitions': page([deposits, timeClock]),
      'GET /api/v1/saved-reports': page([{ id: 'sv1', report_key: 'deposits', name: "Yesterday's deposits", params: {}, columns: null, is_shared: true, owner_staff_user_id: 's1', last_run_at: null, created_at: '', updated_at: '' }]),
      'GET /api/v1/export-jobs': page([{ id: 'x1', source_kind: 'report_run', report_run_id: 'run1', source_key: 'deposits', params: {}, format: 'csv', includes_details: false, page_size: null, orientation: null, status: 'succeeded', row_count: 3, file_name: 'deposits.csv', error: null, expires_at: '', created_at: '2026-11-11T00:00:00Z', updated_at: '' }]),
    })
    expect(await screen.findByRole('link', { name: 'Deposits' })).toHaveAttribute('href', '/reports/deposits')
    expect(screen.getByRole('heading', { name: 'Time clock' })).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: "Yesterday's deposits" })).toHaveAttribute('href', '/reports/deposits?saved=sv1')
    expect(await screen.findByRole('button', { name: 'Download deposits.csv' })).toBeInTheDocument()
  })

  it('runs a report from its generated form, totals it, sorts and drills into details', async () => {
    const user = userEvent.setup()
    const calls = renderAsStaff(<ReportRunPage reportKey="deposits" />, ['reporting.financial.run'], {
      'GET /api/v1/report-definitions': page([deposits]),
      'POST /api/v1/report-runs': { status: 200, body: run },
      'GET /api/v1/report-runs/run1/rows': (call) => (call.url.includes('group_key=card')
        ? rows([{ receipt_number: 'R-1', amount_minor: 2500, group_key: 'card' }], deposits.detail_columns)
        : rows([{ tender: 'card', amount_minor: 2500, group_key: 'card' }])),
    })
    await user.selectOptions(await screen.findByLabelText('Period'), 'this_month')
    expect(screen.queryByLabelText('From')).not.toBeInTheDocument() // a relative period hides the custom dates
    await user.click(screen.getByRole('button', { name: 'Run report' }))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ report_key: 'deposits', params: { period: 'this_month' } })
    expect(await screen.findByText('Received')).toBeInTheDocument()
    expect(screen.getAllByText('$25.00').length).toBeGreaterThan(0)
    expect(screen.queryByRole('heading', { name: 'Export' })).not.toBeInTheDocument() // no export key

    await user.click(screen.getByRole('button', { name: /^Amount/ }))
    await waitFor(() => expect(calls.some((c) => c.url.includes('sort=amount_minor'))).toBe(true))
    await user.click(await screen.findByRole('button', { name: 'Details for card' }))
    expect(await screen.findByText('R-1')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Details: card' })).toBeInTheDocument()
  })

  it('points a parameter error at its field', async () => {
    const user = userEvent.setup()
    renderAsStaff(<ReportRunPage reportKey="deposits" />, ['reporting.financial.run'], {
      'GET /api/v1/report-definitions': page([deposits]),
      'POST /api/v1/report-runs': { status: 422, body: { status: 422, code: 'validation-failed', title: 'Invalid', errors: [{ pointer: '/params/to_on', detail: 'The end is before the start' }] } },
    })
    await user.click(await screen.findByRole('button', { name: 'Run report' }))
    expect(await screen.findByText('The end is before the start')).toBeInTheDocument()
    expect(screen.getByLabelText('To')).toHaveAttribute('aria-invalid', 'true')
  })

  it('exports the run as a job and offers the file once it is ready', async () => {
    const user = userEvent.setup()
    const job = { id: 'x1', source_kind: 'report_run', report_run_id: 'run1', source_key: 'deposits', params: {}, format: 'csv', includes_details: true, page_size: null, orientation: null, row_count: null, file_name: null, error: null, expires_at: '', created_at: '', updated_at: '' }
    const calls = renderAsStaff(<ReportRunPage reportKey="deposits" />, FINANCIAL, {
      'GET /api/v1/report-definitions': page([deposits]),
      'POST /api/v1/report-runs': { status: 200, body: run },
      'GET /api/v1/report-runs/run1/rows': rows([{ tender: 'card', amount_minor: 2500, group_key: 'card' }]),
      'POST /api/v1/export-jobs': { status: 202, body: { ...job, status: 'queued' } },
      'GET /api/v1/export-jobs/x1': { status: 200, body: { ...job, status: 'succeeded', row_count: 2, file_name: 'deposits-2026-11-11.csv' } },
    })
    await user.click(await screen.findByRole('button', { name: 'Run report' }))
    await user.click(await screen.findByLabelText('Include detail rows'))
    await user.selectOptions(screen.getByLabelText('Format'), 'pdf')
    await user.selectOptions(screen.getByLabelText('Page size'), 'a4')
    await user.click(screen.getByRole('button', { name: 'Export' }))
    expect(calls.find((c) => c.url.endsWith('/export-jobs'))?.body).toEqual({
      source_kind: 'report_run', report_run_id: 'run1', format: 'pdf', includes_details: true, page_size: 'a4', orientation: null,
    })
    expect(await screen.findByRole('button', { name: 'Download deposits-2026-11-11.csv' })).toBeInTheDocument()
  })
})

describe('report centre, wave 4', SCREEN, () => {
  const revenue = {
    ...deposits, key: 'revenue_summary', name: 'Revenue summary', supports_detail: false,
    params_schema: { properties: { revenue_category_ids: { anyOf: [{ type: 'array', items: { type: 'string', format: 'uuid' } }, { type: 'null' }], title: 'Revenue categories' } } },
    columns: [{ key: 'revenue_category', label: 'Revenue category', type: 'text' }, { key: 'net_minor', label: 'Net revenue', type: 'money' }],
    total_columns: [{ key: 'net_minor', label: 'Net revenue', type: 'money' }],
  }

  it('filters by revenue category and charts net revenue against the goal', async () => {
    const user = userEvent.setup()
    const calls = renderAsStaff(<ReportRunPage reportKey="revenue_summary" />, ['reporting.financial.run'], {
      'GET /api/v1/report-definitions': page([revenue]),
      'GET /api/v1/revenue-categories': page([{ id: 'rc1', label: 'Court rentals', code: 'CR', is_active: true, parent_id: null, system_key: null }]),
      'POST /api/v1/report-runs': { status: 200, body: { ...run, report_key: 'revenue_summary', totals: { net_minor: 9000, goal_minor: 12000, goal_pct: 75 } } },
      'GET /api/v1/report-runs/run1/rows': rows([{ revenue_category: 'Court rentals', net_minor: 9000, group_key: 'rc1' }], revenue.columns),
    })
    await user.click(await screen.findByLabelText('Court rentals'))
    await user.click(screen.getByRole('button', { name: 'Run report' }))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ report_key: 'revenue_summary', params: { revenue_category_ids: ['rc1'] } })
    expect(await screen.findByRole('img', { name: 'Net revenue $90.00 against a goal of $120.00 (75.0%)' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Print' })).toBeInTheDocument()
  })

  it('schedules a saved report for chosen recipients', async () => {
    const user = userEvent.setup()
    const saved = { id: 'sv1', report_key: 'deposits', name: 'Weekly deposits', params: {}, columns: null, is_shared: false, owner_staff_user_id: 's1', last_run_at: null, created_at: '', updated_at: '' }
    const calls = renderAsStaff(<ReportRunPage reportKey="deposits" savedId="sv1" />, FINANCIAL, {
      'GET /api/v1/report-definitions': page([deposits]),
      'GET /api/v1/saved-reports/sv1': { status: 200, body: saved },
      'GET /api/v1/report-definitions/deposits/recipients': page([{ id: 's1', display_name: 'Pat Example' }, { id: 's2', display_name: 'Sam Manager' }]),
      'POST /api/v1/report-schedules': { status: 201, body: { id: 'rs1' } },
    })
    await user.click(await screen.findByRole('button', { name: 'Schedule…' }))
    await user.click(await screen.findByLabelText('Sam Manager'))
    await user.click(screen.getByRole('button', { name: 'Schedule' }))
    await waitFor(() => expect(calls.find((c) => c.url.endsWith('/report-schedules'))?.body).toEqual({
      location_id: 'l1', frequency: 'weekly', weekday: 0, month_day: null, send_time: '07:00', format: 'pdf', includes_details: false,
      recipient_staff_user_ids: ['s2'], saved_report_id: 'sv1', is_active: true,
    }))
  })

  it('shows the dashboard tiles with links to the full reports', async () => {
    renderAsStaff(<DashboardTiles />, ['reporting.dashboard.read', 'reporting.financial.run'], {
      'GET /api/v1/dashboards/management': { status: 200, body: { location_id: null, generated_at: '', tiles: [
        { key: 'revenue_summary', name: 'Revenue summary', period: 'this_month', available: true, totals: [{ key: 'net_minor', label: 'Net revenue', type: 'money', value: 9000 }] },
        { key: 'open_invoices', name: 'Open invoices', period: null, available: false, totals: [{ key: 'balance_minor', label: 'Balance', type: 'money', value: null }] },
      ] } },
    })
    expect(await screen.findByRole('link', { name: 'Revenue summary' })).toHaveAttribute('href', '/reports/revenue_summary')
    expect(screen.getByText('$90.00')).toBeInTheDocument()
    expect(screen.getByText('This month')).toBeInTheDocument()
    expect(screen.getByText(/Too much data for a tile/)).toBeInTheDocument()
  })
})

describe('formatCell', () => {
  it('formats money, percentages, dates and counts, and never shows "NaN"', () => {
    expect(formatCell(123456, 'money', 'USD')).toBe('$1,234.56')
    expect(formatCell(12.345, 'pct', 'USD')).toBe('12.3%')
    expect(formatCell('INV-7', 'number', 'USD')).toBe('INV-7')
    expect(formatCell(null, 'money', 'USD')).toBe('—')
    expect(formatCell('no_show', 'text', 'USD')).toBe('no show')
  })
})
