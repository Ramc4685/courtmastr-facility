import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { page, renderAsStaff, SCREEN } from '../scheduling/testing'
import { formatCell } from './queries'
import { ReportRunPage } from './ReportRunPage'
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
    await user.click(screen.getByRole('button', { name: 'Export CSV' }))
    expect(calls.find((c) => c.url.endsWith('/export-jobs'))?.body).toEqual({ source_kind: 'report_run', report_run_id: 'run1', format: 'csv', includes_details: true })
    expect(await screen.findByRole('button', { name: 'Download deposits-2026-11-11.csv' })).toBeInTheDocument()
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
