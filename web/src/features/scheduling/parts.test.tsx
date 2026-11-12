import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { SeriesScopeDialog, WarningNote } from './parts'
import { page, renderAsStaff, SCREEN } from './testing'

const occurrence = (id: string, day: string) => ({ id, starts_at: `${day}T15:00:00Z`, ends_at: `${day}T16:00:00Z` })

describe('SeriesScopeDialog', SCREEN, () => {
  it('cancels the occurrences picked from the series (SCH-10 selected)', async () => {
    const onConfirm = vi.fn()
    renderAsStaff(<SeriesScopeDialog action="cancel" allowSeries seriesId="s1" timeZone="America/Chicago" onConfirm={onConfirm} onClose={() => {}} />, [], {
      'GET /api/v1/bookings': page([occurrence('b1', '2031-05-05'), occurrence('b2', '2031-05-12')]),
    })
    const dialog = await screen.findByRole('dialog', { name: 'Cancel a repeating booking' })
    await userEvent.click(within(dialog).getByRole('radio', { name: 'Cancel the occurrences I pick' }))
    const apply = within(dialog).getByRole('button', { name: 'Cancel bookings' })
    expect(apply).toBeDisabled()
    await userEvent.click(await within(dialog).findByRole('checkbox', { name: /May 12/ }))
    await userEvent.click(apply)
    expect(onConfirm).toHaveBeenCalledWith({ mode: 'selected', booking_ids: ['b2'] }, false)
  })

  it('edits the occurrences between two dates (SCH-10 date_range)', async () => {
    const onConfirm = vi.fn()
    renderAsStaff(<SeriesScopeDialog action="edit" allowSeries seriesId="s1" onConfirm={onConfirm} onClose={() => {}} />, [], {})
    const dialog = await screen.findByRole('dialog', { name: 'Change a repeating booking' })
    await userEvent.click(within(dialog).getByRole('radio', { name: 'Change the occurrences between two dates' }))
    await userEvent.type(within(dialog).getByLabelText('From'), '2031-05-01')
    await userEvent.type(within(dialog).getByLabelText('To'), '2031-05-31')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Apply' }))
    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith({ mode: 'date_range', from_on: '2031-05-01', to_on: '2031-05-31' }, false))
  })

  it('a move offers only this, following and all', async () => {
    renderAsStaff(<SeriesScopeDialog action="move" allowSeries seriesId="s1" onConfirm={() => {}} onClose={() => {}} />, [], {})
    const dialog = await screen.findByRole('dialog', { name: 'Move a repeating booking' })
    expect(within(dialog).getAllByRole('radio')).toHaveLength(3)
  })
})

describe('WarningNote', SCREEN, () => {
  it('says the booking is outside opening hours and can be dismissed', async () => {
    renderAsStaff(<WarningNote warnings={[{ code: 'outside-opening-hours', detail: 'Outside opening hours on 2031-05-05.', count: 1 }]} />, [], {})
    expect(await screen.findByRole('status')).toHaveTextContent('Outside opening hours on 2031-05-05. You can still book it.')
    await userEvent.click(screen.getByRole('button', { name: 'Dismiss warning' }))
    expect(screen.queryByRole('status')).toBeNull()
  })
})
