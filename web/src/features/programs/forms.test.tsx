import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { page, renderAsStaff, SCREEN } from '../scheduling/testing'
import { FormPage } from './FormPage'
import { FormsPage } from './FormsPage'
import { answersOf, isShown, stockKeys, totalOf, type PublicFormItem } from './forms'
import { ProgramSetupPage, ToolsTab } from './groupTools'
import { PublicFormPage } from './PublicFormPage'

const ALL = [
  'programs.form.manage',
  'programs.form_response.read',
  'programs.registration.read',
  'programs.registration.update',
  'programs.registration.export',
  'programs.program.manage',
  'programs.registration_config.manage',
  'reporting.program.run',
]
const shirt = {
  type: 'question',
  key: 'shirt',
  question_type: 'radio',
  text: 'Shirt size',
  required: true,
  choices: [
    { key: 's', text: 'Small', price_minor: 0, sold_out: false, remaining: 2 },
    { key: 'l', text: 'Large', price_minor: 0, sold_out: true, remaining: 0 },
  ],
}
const tickets = { type: 'question', key: 'tickets', question_type: 'purchase_quantity', text: 'Dinner tickets', required: false, unit_price_minor: 1500, choices: [], depends_on: { question_key: 'shirt', choice_key: 's' } }
const form = (extra: Record<string, unknown> = {}) => ({
  id: 'f1',
  location_id: 'l1',
  name: 'Open Day',
  event_name: 'Open Day',
  event_text: null,
  event_starts_on: '2031-06-01',
  event_ends_on: null,
  opens_local: null,
  closes_local: null,
  capacity: 50,
  has_waitlist: false,
  allows_coupons: false,
  confirmation_message: null,
  closed_message: null,
  theme: null,
  time_zone: 'America/Chicago',
  status: 'open',
  effective_state: 'open',
  is_template: false,
  is_free: true,
  has_header_image: false,
  submitted_count: 3,
  revenue_category_id: null,
  copied_from_form_id: null,
  created_at: '',
  updated_at: 'u1',
  draft: null,
  published: { id: 'v1', version_no: 1, schema_doc: { items: [shirt] } },
  ...extra,
})
const publicForm = (items: unknown[]) => ({
  id: 'f1',
  event_name: 'Open Day',
  event_text: null,
  event_starts_on: null,
  event_ends_on: null,
  has_header_image: false,
  allows_coupons: false,
  closed_message: null,
  state: 'open',
  theme: {},
  items,
})

/** Mounts a page that reads its id from the route, inside the test harness's own router. */
const at = (path: string, ui: ReactElement, pattern: string) => (
  <Routes>
    <Route path="/" element={<Navigate to={path} replace />} />
    <Route path={pattern} element={ui} />
  </Routes>
)

describe('form helpers', () => {
  it('totals shown choices and quantities, and drops hidden answers', () => {
    const items = [shirt, tickets] as unknown as PublicFormItem[]
    expect(isShown(tickets as unknown as PublicFormItem, {})).toBe(false)
    expect(totalOf(items, { shirt: ['s'] }, { tickets: 2 })).toBe(3000)
    expect(totalOf(items, {}, { tickets: 2 })).toBe(0)
    expect(answersOf(items, {}, {}, { tickets: 2 })).toEqual([{ item_key: 'shirt', choice_keys: [] }])
    expect(stockKeys([shirt, tickets] as never).map((k) => k.key)).toEqual(['shirt.s', 'shirt.l', 'tickets'])
  })
})

describe('FormsPage', SCREEN, () => {
  it('lists the event forms with their state and registrations', async () => {
    renderAsStaff(<FormsPage />, ALL, { 'GET /api/v1/forms': page([form()]) })
    const row = within(await screen.findByRole('table', { name: 'Event forms' })).getByRole('row', { name: /Open Day/ })
    expect(row).toHaveTextContent('3 of 50')
    expect(row).toHaveTextContent('Open')
  })
})

describe('FormPage', SCREEN, () => {
  it('adds a question to the draft and saves it', async () => {
    const calls = renderAsStaff(at('/programs/forms/f1', <FormPage />, '/programs/forms/:id'), ALL, {
      'GET /api/v1/forms/f1': { status: 200, body: form() },
      'PUT /api/v1/forms/f1/draft': { status: 200, body: form() },
    })
    await userEvent.click(await screen.findByRole('tab', { name: 'Questions' }))
    await userEvent.click(screen.getByRole('button', { name: 'Add question' }))
    await userEvent.type(screen.getByRole('textbox', { name: 'Question 2 text' }), 'Allergies')
    await userEvent.click(screen.getByRole('button', { name: 'Save draft' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
    const body = calls.find((c) => c.method === 'PUT')?.body as { items: { key: string }[] }
    expect(body.items.map((i) => i.key)).toEqual(['shirt', 'q1'])
    expect(body.items[1]).toMatchObject({ question_type: 'text_box', text: 'Allergies' })
  })

  it('publishes a pending draft', async () => {
    const calls = renderAsStaff(at('/programs/forms/f1', <FormPage />, '/programs/forms/:id'), ALL, {
      'GET /api/v1/forms/f1': { status: 200, body: form({ draft: { id: 'v2', version_no: 2, schema_doc: { items: [shirt] } } }) },
      'POST /api/v1/forms/f1/publish': { status: 200, body: form() },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Publish' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/publish'))).toBe(true))
  })
})

describe('PublicFormPage', SCREEN, () => {
  it('registers anonymously on a free form and shows the confirmation number', async () => {
    const calls = renderAsStaff(at('/forms/f1', <PublicFormPage />, '/forms/:id'), [], {
      'GET /api/v1/public/forms/f1': { status: 200, body: publicForm([shirt]) },
      'POST /api/v1/public/forms/f1/submissions': { status: 201, body: { confirmation_no: 7, status: 'confirmed', total_minor: 0, confirmation_message: 'See you there.' } },
    })
    await userEvent.type(await screen.findByRole('textbox', { name: 'Your name' }), 'Sam Lee')
    await userEvent.type(screen.getByRole('textbox', { name: 'Email' }), 'sam@example.com')
    expect(screen.getByRole('radio', { name: /Large/ })).toBeDisabled()
    await userEvent.click(screen.getByRole('radio', { name: /Small/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Register' }))
    expect(await screen.findByText('Confirmation number 7.')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
      contact_name: 'Sam Lee',
      contact_email: 'sam@example.com',
      contact_phone: null,
      answers: [{ item_key: 'shirt', choice_keys: ['s'] }],
    })
    expect(calls.some((c) => c.url.includes('/portal/'))).toBe(false)
  })

  it('asks for sign-in once a priced choice is picked', async () => {
    renderAsStaff(at('/forms/f1', <PublicFormPage />, '/forms/:id'), [], { 'GET /api/v1/public/forms/f1': { status: 200, body: publicForm([shirt, tickets]) } })
    await userEvent.click(await screen.findByRole('radio', { name: /Small/ }))
    const qty = screen.getByRole('spinbutton', { name: /Dinner tickets/ })
    await userEvent.clear(qty)
    await userEvent.type(qty, '2')
    expect(screen.getByText('Total $30.00')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Sign in and register' })).toHaveAttribute('href', '/portal/forms/f1')
    expect(screen.queryByRole('button', { name: /Register/ })).not.toBeInTheDocument()
  })
})

describe('ProgramSetupPage', SCREEN, () => {
  it('adds a season classifier', async () => {
    const calls = renderAsStaff(<ProgramSetupPage />, ALL, {
      'GET /api/v1/program-classifiers': { status: 200, body: [] },
      'GET /api/v1/locations/l1/registration-defaults': {
        status: 200,
        body: { location_id: 'l1', payment_requirement: 'immediate_card_payment', displays_openings: false, waitlist_mode: 'manual', online_description: null, confirmation_message: null, closed_message: null },
      },
      'POST /api/v1/program-classifiers': { status: 201, body: { id: 'k1', kind: 'season', title: 'Fall 2031', sort_order: 0, is_active: true, group_count: 0 } },
    })
    const input = await screen.findByRole('textbox', { name: 'New season' })
    await userEvent.type(input, 'Fall 2031')
    await userEvent.click(within(input.closest('form') as HTMLElement).getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ kind: 'season', title: 'Fall 2031', sort_order: 0 })
  })
})

describe('ToolsTab', SCREEN, () => {
  it('moves the picked registrations to another program', async () => {
    const group = { id: 'g1', location_id: 'l1', name: 'Camp A', status: 'active', season_classifier_id: null, sport_classifier_id: null, age_division_classifier_id: null }
    const roster = {
      program_group_id: 'g1',
      capacity: null,
      enrolled_count: 1,
      waiting_count: 0,
      participants: [{ enrollment_id: 'e1', client_id: 'c1', client_name: 'Riley Reyes', program_group_id: 'g1', program_group_name: 'Camp A', channel: 'staff', enrolled_at: '', charge_id: null, invoice_id: null, payer_client_id: null }],
    }
    const calls = renderAsStaff(<ToolsTab group={group as never} canManage={false} />, ALL, {
      'GET /api/v1/program-groups/g1/roster': { status: 200, body: roster },
      'GET /api/v1/program-groups': page([group, { ...group, id: 'g2', name: 'Camp B' }]),
      'POST /api/v1/enrollments/move': { status: 200, body: { to_program_group_id: 'g2', outcomes: [{ enrollment_id: 'e1', moved: true, code: null }] } },
    })
    await userEvent.click(await screen.findByRole('checkbox', { name: 'Riley Reyes' }))
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Move to' }), 'g2')
    await userEvent.click(screen.getByRole('button', { name: /Move 1 registration/ }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ enrollment_ids: ['e1'], to_program_group_id: 'g2' })
  })
})
