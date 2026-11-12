import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Dialog } from './Dialog'
import { Input } from './Field'
import { Table, useKeysetQuery } from './Table'
import { Tabs } from './Tabs'

describe('Tabs', () => {
  it('moves selection and focus with the arrow keys and wraps around', async () => {
    render(
      <Tabs
        label="Sections"
        tabs={[
          { id: 'a', label: 'Alpha', content: 'alpha panel' },
          { id: 'b', label: 'Beta', content: 'beta panel' },
        ]}
      />,
    )
    const alpha = screen.getByRole('tab', { name: 'Alpha' })
    expect(alpha).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tabpanel', { name: 'Alpha' })).toHaveTextContent('alpha panel')
    alpha.focus()
    await userEvent.keyboard('{ArrowRight}')
    const beta = screen.getByRole('tab', { name: 'Beta' })
    expect(beta).toHaveAttribute('aria-selected', 'true')
    expect(beta).toHaveFocus()
    await userEvent.keyboard('{ArrowRight}')
    expect(alpha).toHaveFocus()
  })
})

describe('Dialog', () => {
  it('is labelled by its title and closes on Escape (cancel)', () => {
    const onClose = vi.fn()
    render(
      <Dialog open title="New location" onClose={onClose}>
        body
      </Dialog>,
    )
    const dialog = screen.getByRole('dialog', { name: 'New location' })
    fireEvent(dialog, new Event('cancel', { cancelable: true }))
    expect(onClose).toHaveBeenCalled()
  })
})

describe('Input', () => {
  it('connects label, hint and error to the control', () => {
    render(<Input label="Email" hint="Work address" error="Required" />)
    const input = screen.getByRole('textbox', { name: 'Email' })
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input).toHaveAccessibleDescription('Work address Required')
  })
})

function Paged({ fetchPage }: { fetchPage: (c: string | undefined) => Promise<{ data: { id: string }[]; page: { next_cursor: string | null; has_more: boolean } }> }) {
  const paging = useKeysetQuery(['things'], fetchPage)
  return <Table caption="Things" columns={[{ header: 'Id', cell: (r) => r.id }]} rowKey={(r) => r.id} paging={paging} empty="none" />
}

describe('Table with keyset pagination', () => {
  it('follows next_cursor forward and returns to the previous cursor', async () => {
    const fetchPage = vi.fn(async (cursor: string | undefined) =>
      cursor === 'c2' ? { data: [{ id: 'row-3' }], page: { next_cursor: null, has_more: false } } : { data: [{ id: 'row-1' }], page: { next_cursor: 'c2', has_more: true } },
    )
    render(
      <QueryClientProvider client={new QueryClient()}>
        <Paged fetchPage={fetchPage} />
      </QueryClientProvider>,
    )
    expect(await screen.findByText('row-1')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(await screen.findByText('row-3')).toBeInTheDocument()
    expect(fetchPage).toHaveBeenLastCalledWith('c2')
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Previous' }))
    await waitFor(() => expect(screen.getByText('row-1')).toBeInTheDocument())
  })

  it('keeps stale rows at full contrast while the next page loads (axe colour-contrast regression)', async () => {
    let release: () => void = () => {}
    const fetchPage = vi.fn((cursor: string | undefined) =>
      cursor === 'c2'
        ? new Promise<{ data: { id: string }[]; page: { next_cursor: null; has_more: false } }>((resolve) => (release = () => resolve({ data: [{ id: 'row-3' }], page: { next_cursor: null, has_more: false } })))
        : Promise.resolve({ data: [{ id: 'row-1' }], page: { next_cursor: 'c2', has_more: true } }),
    )
    render(
      <QueryClientProvider client={new QueryClient()}>
        <Paged fetchPage={fetchPage} />
      </QueryClientProvider>,
    )
    expect(await screen.findByText('row-1')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(fetchPage).toHaveBeenLastCalledWith('c2'))
    // Opacity scales the text's contrast: muted text fell from 7.2:1 to 2.8:1 at 60%.
    expect(screen.getByText('row-1').closest('[class*="opacity-"]')).toBeNull()
    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'true')
    expect(screen.getByTestId('table-updating')).toBeInTheDocument()
    release()
    expect(await screen.findByText('row-3')).toBeInTheDocument()
    expect(screen.getByRole('table')).not.toHaveAttribute('aria-busy')
  })
})
