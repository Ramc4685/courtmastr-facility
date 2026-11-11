import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { page, renderAsStaff, resource, SCREEN } from '../scheduling/testing'
import { ResourcesPage } from './ResourcesPage'

const group = { id: 'g1', name: 'Courts', location_id: 'l1', sort_order: 0, is_active: true }
const court = resource('r1', 'Court 1')
const half = resource('r2', 'Court 1 North half', { parent_id: 'r1' })
const routes = { 'GET /api/v1/resources': page([court, half]), 'GET /api/v1/resource-groups': page([group]) }

describe('ResourcesPage', SCREEN, () => {
  it('lists each group as a tree, naming the parent of every sub-resource', async () => {
    renderAsStaff(<ResourcesPage />, ['resources.resource.read', 'resources.resource.manage'], routes)
    const list = await screen.findByRole('list', { name: 'Courts' })
    const items = within(list).getAllByRole('listitem')
    expect(items.map((li) => li.querySelector('.font-medium')?.textContent)).toEqual(['Court 1', 'Court 1 North half'])
    expect(items[1]).toHaveTextContent(', part of Court 1')
    // three levels deep at most: a second-level resource can still take parts
    expect(within(list).getByRole('button', { name: 'Add part to Court 1 North half' })).toBeInTheDocument()
  })

  it('creates a sub-resource under the chosen parent in its group', async () => {
    const calls = renderAsStaff(<ResourcesPage />, ['resources.resource.read', 'resources.resource.manage'], {
      ...routes,
      'POST /api/v1/resources': { status: 201, body: resource('r3', 'Court 1 South half', { parent_id: 'r1' }) },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Add part to Court 1' }))
    const dialog = await screen.findByRole('dialog', { name: 'New sub-resource of Court 1' })
    await userEvent.type(within(dialog).getByRole('textbox', { name: 'Name' }), 'Court 1 South half')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create resource' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({ name: 'Court 1 South half', parent_id: 'r1', resource_group_id: 'g1', location_id: 'l1', kind: 'venue' })
  })

  it('shows read-only staff the tree without management buttons', async () => {
    renderAsStaff(<ResourcesPage />, ['resources.resource.read'], routes)
    await screen.findByRole('list', { name: 'Courts' })
    expect(screen.queryByRole('button', { name: 'New resource' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit Court 1' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Availability of Court 1' })).toBeInTheDocument()
  })
})
