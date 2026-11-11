import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockFetch } from '../../test/fetchMock'
import { ClientPhotoById } from './ClientFiles'

afterEach(() => vi.unstubAllGlobals())

describe('ClientPhotoById (check-in status card)', () => {
  it('loads the photo route directly, never the profile, and hides the image when there is none', () => {
    const calls = mockFetch({})
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ClientPhotoById clientId="c1" name="Morgan Member" />
      </QueryClientProvider>,
    )
    const img = screen.getByRole('img', { name: 'Morgan Member' })
    expect(img.getAttribute('src')).toBe('/api/v1/clients/c1/photo')
    expect(calls).toEqual([]) // no GET /clients/{id}: it would log a recent view and needs clients.client.read
    fireEvent.error(img)
    expect(screen.queryByRole('img')).toBeNull()
  })
})
