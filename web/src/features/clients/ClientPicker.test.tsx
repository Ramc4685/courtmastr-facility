import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockFetch } from '../../test/fetchMock'
import { ClientPicker, type ClientSummary } from './ClientPicker'

const person = (id: string, first_name: string, last_name: string, extra: Partial<ClientSummary> = {}): ClientSummary => ({
  id, first_name, last_name, primary_email: null, phone_mobile: null, home_location_id: 'l1', member_number: null, status: 'active', created_at: '2026-11-10T00:00:00Z', ...extra,
})
const page = (data: ClientSummary[]) => ({ status: 200, body: { data, page: { next_cursor: null, has_more: false } } })
const ada = person('c1', 'Ada', 'Lovelace', { member_number: 'M-100', primary_email: 'ada@example.com' })
const adam = person('c2', 'Adam', 'Smith')

function Harness({ onPick = () => {} }: { onPick?: (c: ClientSummary | null) => void }) {
  const [value, setValue] = useState<ClientSummary | null>(null)
  return (
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <form onSubmit={(e) => e.preventDefault()}>
        <ClientPicker
          label="Client"
          value={value}
          hint="Who is this for?"
          onChange={(c) => {
            setValue(c)
            onPick(c)
          }}
        />
      </form>
    </QueryClientProvider>
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('ClientPicker', () => {
  it('searches as you type and picks with the keyboard', async () => {
    const calls = mockFetch({ 'GET /api/v1/clients': page([ada, adam]) })
    const onPick = vi.fn()
    render(<Harness onPick={onPick} />)
    const input = screen.getByRole('combobox', { name: 'Client' })
    expect(input).toHaveAttribute('aria-expanded', 'false')
    expect(input).toHaveAccessibleDescription('Who is this for?')

    await userEvent.type(input, 'a')
    expect(screen.getByRole('status')).toHaveTextContent('Type at least 2 characters')
    expect(calls).toHaveLength(0) // one letter never hits the API
    await userEvent.type(input, 'd')
    const options = await screen.findAllByRole('option')
    expect(options.map((o) => o.textContent)).toEqual(['Ada LovelaceM-100 · ada@example.com', 'Adam Smith'])
    expect(calls[0]?.url).toBe('/api/v1/clients?q=ad&status=active&limit=8')
    expect(screen.getByRole('status')).toHaveTextContent('2 clients found.')
    expect(input).toHaveAttribute('aria-expanded', 'true')
    expect(input).toHaveAttribute('aria-activedescendant', options[0]?.id)

    await userEvent.keyboard('{ArrowDown}')
    expect(input).toHaveAttribute('aria-activedescendant', options[1]?.id)
    expect(options[1]).toHaveAttribute('aria-selected', 'true')
    await userEvent.keyboard('{ArrowDown}{Enter}') // wraps to the first, then chooses it
    expect(onPick).toHaveBeenLastCalledWith(ada)
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    expect(screen.getByText('Ada Lovelace')).toBeInTheDocument()
    const change = screen.getByRole('button', { name: /Change client, currently Ada Lovelace/ })
    expect(change).toHaveFocus() // focus follows the control that replaced the input

    await userEvent.click(change)
    expect(onPick).toHaveBeenLastCalledWith(null)
    expect(screen.getByRole('combobox', { name: 'Client' })).toHaveValue('')
    expect(screen.getByRole('combobox', { name: 'Client' })).toHaveFocus()
  })

  it('picks with the mouse, closes on Escape and says when nothing matches', async () => {
    mockFetch({ 'GET /api/v1/clients': (call) => page(call.url.includes('q=zz') ? [] : [adam]) })
    const onPick = vi.fn()
    render(<Harness onPick={onPick} />)
    const input = screen.getByRole('combobox', { name: 'Client' })
    await userEvent.type(input, 'zz')
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('No clients match.'))
    expect(screen.queryByRole('option')).not.toBeInTheDocument()

    await userEvent.clear(input)
    await userEvent.type(input, 'smi')
    await screen.findByRole('option', { name: /Adam Smith/ })
    await userEvent.keyboard('{Escape}')
    expect(input).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('option')).not.toBeInTheDocument()
    await userEvent.keyboard('{ArrowUp}') // reopens
    await userEvent.click(await screen.findByRole('option', { name: /Adam Smith/ }))
    expect(onPick).toHaveBeenLastCalledWith(adam)
  })

  it('reports a failed search and shows a field error', async () => {
    mockFetch({ 'GET /api/v1/clients': { status: 403, body: { code: 'permission-denied' } } })
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ClientPicker label="Payer" value={null} onChange={() => {}} error="Choose a client." required />
      </QueryClientProvider>,
    )
    const input = screen.getByRole('combobox', { name: 'Payer' })
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input).toHaveAccessibleDescription('Choose a client.')
    await userEvent.type(input, 'ada')
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Search failed. Try again.'))
  })
})
