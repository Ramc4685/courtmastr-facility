import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Call } from '../../test/fetchMock'
import { page, renderAsStaff, SCREEN } from '../scheduling/testing'
import { AssessmentSetupPage } from './AssessmentSetupPage'
import { ClientAssessmentsTab } from './ClientAssessmentsTab'
import { PortalProgress } from './PortalProgress'
import { TrendChart } from './TrendChart'

afterEach(() => vi.unstubAllGlobals())

const weight = { id: 'f1', assessment_template_id: 't1', name: 'Weight', decimal_places: 1, unit_label: 'kg', better_direction: 'lower', is_client_visible: true, sort_order: 0, is_active: true }
const template = { id: 't1', name: 'Fitness', sort_order: 0, is_active: true, fields: [weight] }
const templates = { 'GET /api/v1/assessment-templates': page([template]) }

describe('assessment screens', SCREEN, () => {
  it('records a result for a client', async () => {
    const posts: Call[] = []
    renderAsStaff(<ClientAssessmentsTab client={{ id: 'c1', home_location_id: 'l1' }} />, ['assessments.assessment.read', 'assessments.assessment.record'], {
      ...templates,
      'GET /api/v1/assessment-series': { status: 200, body: { series: [{ assessment_field_id: 'f1', points: [], latest_value: '80.5', first_value: '82.0', change: '-1.5', best_value: '80.5' }] } },
      'GET /api/v1/assessment-results': page([]),
      'POST /api/v1/assessment-results': (c) => (posts.push(c), { status: 201, body: { id: 'r1' } }),
    })
    expect(await screen.findAllByText('80.5 kg')).toHaveLength(2)
    await userEvent.click(screen.getByRole('button', { name: 'Record assessment' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText(/Weight \(kg\)/), '79.25')
    await userEvent.click(within(dialog).getByRole('button', { name: /Save|Record/ }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0]?.body).toMatchObject({ client_id: 'c1', location_id: 'l1', values: [{ assessment_field_id: 'f1', value: '79.25' }] })
  })

  it('charts each field over time and links to the history report', async () => {
    const points = [{ recorded_at: '2026-11-08T15:00:00Z', result_id: 'r2', value: '80.5' }, { recorded_at: '2026-10-01T15:00:00Z', result_id: 'r1', value: '82.0' }]
    renderAsStaff(<ClientAssessmentsTab client={{ id: 'c1', home_location_id: 'l1' }} />, ['assessments.assessment.read', 'reporting.client.run'], {
      ...templates,
      'GET /api/v1/assessment-series': { status: 200, body: { series: [{ assessment_field_id: 'f1', points, latest_value: '80.5', first_value: '82.0', change: '-1.5', best_value: '80.5' }] } },
      'GET /api/v1/assessment-results': page([]),
    })
    const chart = await screen.findByRole('img')
    expect(chart.getAttribute('aria-label')).toMatch(/^Weight from 82\.0 kg on .+ to 80\.5 kg on .+, 2 entries$/)
    expect(chart.querySelectorAll('circle')).toHaveLength(2)
    expect(screen.getByRole('link', { name: /Assessment history report/ })).toHaveAttribute('href', '/reports/assessment_history?client_id=c1')
  })

  it('draws no trend from a single value', () => {
    const { container } = render(<TrendChart points={[{ recorded_at: '2026-11-08T15:00:00Z', value: '80.5' }]} field={{ name: 'Weight', unit_label: 'kg' }} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('creates a category and turns on portal sharing', async () => {
    const posts: Call[] = []
    renderAsStaff(<AssessmentSetupPage />, ['assessments.definition.manage'], {
      ...templates,
      'GET /api/v1/assessment-settings': { status: 200, body: { is_portal_sharing_enabled: false, summary_max_age_days_default: 90 } },
      'POST /api/v1/assessment-templates': (c) => (posts.push(c), { status: 201, body: { ...template, id: 't2', name: 'Mobility', fields: [] } }),
      'PATCH /api/v1/assessment-settings': (c) => (posts.push(c), { status: 200, body: { is_portal_sharing_enabled: true, summary_max_age_days_default: 90 } }),
    })
    await userEvent.click(await screen.findByRole('button', { name: 'New category' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText(/Name/), 'Mobility')
    await userEvent.click(within(dialog).getByRole('button', { name: /Save|Create/ }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0]?.body).toEqual({ name: 'Mobility', sort_order: 0 })
    await userEvent.click(await screen.findByRole('checkbox'))
    await waitFor(() => expect(posts).toHaveLength(2))
    expect(posts[1]?.body).toMatchObject({ is_portal_sharing_enabled: true })
  })

  it('shows personal bests on the portal and hides itself when sharing is off', async () => {
    renderAsStaff(<PortalProgress />, [], {
      'GET /api/v1/portal/assessment-bests': { status: 200, body: [{ assessment_field_id: 'f1', field_name: 'Plank hold', template_name: 'Fitness', unit_label: 's', better_direction: 'higher', best_value: '95', best_recorded_at: '2026-11-01T15:00:00Z', latest_value: '90', latest_recorded_at: '2026-11-08T15:00:00Z' }] },
      'GET /api/v1/portal/assessment-results': page([]),
    })
    expect(await screen.findByText('Your progress')).toBeInTheDocument()
    expect(await screen.findByText('95 s')).toBeInTheDocument()
  })
})
