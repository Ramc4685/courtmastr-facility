import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Navigate, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { FramedRoutes, isFramed } from '../../app/App'
import { makePortalValue, PortalProvider, type PortalClient } from '../portal/shared'
import { LOCATION, page, renderAsStaff, SCREEN } from '../scheduling/testing'
import { PortalLeaguePostsPage } from './PortalPostsPage'
import { LeagueBoardPage, PublicLeaguesPage } from './PublicLeaguesPage'
import { LeaguePostsPage, LeagueSitePage } from './SitePages'

const site = {
  is_enabled: true, title: 'Club leagues', tagline: 'Play every week', about_text: null, accent_color: '#1a7f5a',
  shows_facility_info: true, shows_classes: false, shows_news: true, shows_gallery: false, shows_sponsors: false, shows_links: false,
  shows_classifieds: true, shows_pickup_games: false, board_refresh_sec: 60,
}
const competition = { id: 'c1', name: 'Wednesday Futsal', kind: 'league', sport_id: 'sp1', sport_name: 'Futsal', season_id: null, starts_on: '2031-05-01', ends_on: null, status: 'active', show_players: false, team_fee_text: null }
const post = {
  id: 'p1', kind: 'classified', category: 'player_wanted', location_name: 'Courtside Downtown', sport_name: null, title: 'Keeper wanted',
  body: 'Our Sunday side needs a keeper.', starts_at: null, skill_level: null, players_needed: 1, posted_at: '2031-05-01T10:00:00Z', expires_at: '2031-05-31T10:00:00Z',
}
const at = (path: string, route: string, element: JSX.Element) => (
  <Routes>
    <Route path="/" element={<Navigate to={path} />} />
    <Route path={route} element={element} />
  </Routes>
)

describe('PublicLeaguesPage site', SCREEN, () => {
  it('shows the branded site, its sections and filters kept in the query', async () => {
    const calls = renderAsStaff(at('/leagues/public', '/leagues/public', <PublicLeaguesPage />), [], {
      'GET /api/v1/public/league-site': { status: 200, body: { ...site, facilities: [{ id: 'l1', name: 'Courtside Downtown', city: 'Normal', region: 'IL', postal_code: null, phone: '555-0100', email: null, website_url: null }] } },
      'GET /api/v1/public/competitions': { status: 200, body: [competition] },
      'GET /api/v1/public/league-site/news': { status: 200, body: [{ id: 'n1', title: 'Opening night', summary: null, body: 'Games start.', published_at: '2031-05-01T10:00:00Z', is_pinned: false }] },
      'GET /api/v1/public/league-site/posts': { status: 200, body: [post] },
    })
    expect(await screen.findByText('Club leagues')).toBeVisible()
    expect(await screen.findByRole('heading', { name: 'Opening night' })).toBeVisible()
    expect(await screen.findByRole('heading', { name: 'Keeper wanted' })).toBeVisible()
    expect(screen.getByRole('link', { name: "Today's games" })).toHaveAttribute('href', '/leagues/board/l1')
    await userEvent.selectOptions(await screen.findByLabelText('Sport'), 'sp1')
    await waitFor(() => expect(calls.some((c) => c.url.startsWith('/api/v1/public/competitions?') && c.url.includes('sport_id=sp1'))).toBe(true))
  })

  it('embeds without the site chrome', async () => {
    renderAsStaff(at('/leagues/public?embed=1', '/leagues/public', <PublicLeaguesPage />), [], {
      'GET /api/v1/public/league-site': { status: 200, body: { ...site, facilities: [] } },
      'GET /api/v1/public/competitions': { status: 200, body: [competition] },
    })
    expect(await screen.findByRole('link', { name: 'Wednesday Futsal' })).toHaveAttribute('href', '/leagues/public/c1?embed=1')
    expect(screen.queryByText('Club leagues')).toBeNull()
    expect(screen.queryByRole('heading', { name: 'Classifieds' })).toBeNull()
  })
})

describe('LeagueBoardPage', SCREEN, () => {
  it("shows today's games at one location", async () => {
    renderAsStaff(at('/leagues/board/l1', '/leagues/board/:locationId', <LeagueBoardPage />), [], {
      'GET /api/v1/public/locations/l1/league-board': { status: 200, body: {
        location_name: 'Courtside Downtown', time_zone: 'America/Chicago', on_date: '2031-05-05', refresh_sec: 30, generated_at: '2031-05-05T20:00:00Z',
        games: [{ starts_at: '2031-05-05T18:00:00Z', competition_name: 'Wednesday Futsal', venue: 'Court 1', status: 'played', home_name: 'Strikers', away_name: 'Rovers', home_score: 3, away_score: 1 }],
      } },
    })
    expect(await screen.findByRole('heading', { level: 1, name: "Courtside Downtown: today's games" })).toBeVisible()
    expect(screen.getByText(/Strikers/)).toHaveTextContent('Strikers 3 - 1 Rovers')
  })
})

describe('LeagueSitePage', SCREEN, () => {
  it('saves the options and links the public site', async () => {
    const calls = renderAsStaff(<LeagueSitePage />, ['leagues.public_site.manage'], {
      'GET /api/v1/league-site': { status: 200, body: { ...site, is_enabled: false } },
      'PUT /api/v1/league-site': { status: 200, body: site },
    })
    await userEvent.click(await screen.findByLabelText('Publish the league site'))
    await userEvent.click(screen.getByLabelText('Pickup games'))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
    expect(calls.find((c) => c.method === 'PUT')?.body).toMatchObject({ is_enabled: true, shows_pickup_games: true, title: 'Club leagues' })
    expect(screen.getByRole('link', { name: /\/leagues\/public$/ })).toBeVisible()
    expect(screen.getByText(/Embedding it inside another website is not switched on yet/)).toBeVisible()
    expect(screen.queryByLabelText('Embed code')).toBeNull()
    expect(screen.queryByRole('tab', { name: 'Sponsors' })).toBeNull()
  })

})

describe('inside a frame', SCREEN, () => {
  const framed = (path: string) => renderAsStaff(
    <Routes><Route path="/" element={<Navigate to={path} />} /><Route path="*" element={<FramedRoutes />} /></Routes>, [], {
      'GET /api/v1/public/league-site': { status: 200, body: { ...site, facilities: [] } },
      'GET /api/v1/public/competitions': { status: 200, body: [competition] },
      'GET /api/v1/public/league-site/news': { status: 200, body: [] },
      'GET /api/v1/public/league-site/posts': { status: 200, body: [] },
    })

  it('detects the frame', () => {
    const top = Object.getOwnPropertyDescriptor(window, 'top')
    Object.defineProperty(window, 'top', { configurable: true, value: {} })
    try {
      expect(isFramed()).toBe(true)
    } finally {
      if (top) Object.defineProperty(window, 'top', top)
    }
    expect(isFramed()).toBe(false)
  })

  it('renders the public league pages', async () => {
    framed('/leagues/public')
    expect(await screen.findByText('Club leagues')).toBeVisible()
  })

  it('refuses staff and portal screens', async () => {
    framed('/billing/invoices/i1/document')
    expect(await screen.findByRole('heading', { name: 'This page cannot be shown inside another site' })).toBeVisible()
    expect(screen.getByRole('link', { name: 'Open it in its own window' })).toHaveAttribute('target', '_top')
  })
})

describe('LeaguePostsPage', SCREEN, () => {
  it('approves a pending post', async () => {
    const staff = { ...post, location_id: 'l1', status: 'pending', client_name: 'Pat Lee', moderated_at: null, reject_reason: null }
    const calls = renderAsStaff(<LeaguePostsPage />, ['leagues.classified.moderate'], {
      'GET /api/v1/league-posts': page([staff]),
      'POST /api/v1/league-posts/p1/approve': { status: 200, body: { ...staff, status: 'approved' } },
    })
    const row = within(await screen.findByRole('table', { name: 'League posts' })).getByRole('row', { name: /Keeper wanted/ })
    expect(row).toHaveTextContent('Pat Lee')
    await userEvent.click(within(row).getByRole('button', { name: 'Approve Keeper wanted' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url === '/api/v1/league-posts/p1/approve')).toBe(true))
    expect(calls.find((c) => c.url.startsWith('/api/v1/league-posts?'))?.url).toContain('status=pending')
  })
})

describe('PortalLeaguePostsPage', SCREEN, () => {
  it('posts a pickup game and replies to a classified through the relay', async () => {
    const self = { id: 'p1', first_name: 'Pat', last_name: 'Lee', preferred_name: null } as unknown as PortalClient
    const portal = makePortalValue([self], null, () => {}, [{ ...LOCATION, public_name: 'Courtside Downtown' } as never], 'USD')
    if (!portal) throw new Error('portal value expected')
    const calls = renderAsStaff(<PortalProvider value={portal}><PortalLeaguePostsPage /></PortalProvider>, [], {
      'GET /api/v1/portal/league-posts': { status: 200, body: [] },
      'POST /api/v1/portal/league-posts': { status: 201, body: { ...post, id: 'p2', kind: 'pickup', status: 'pending' } },
      'GET /api/v1/public/league-site/posts': { status: 200, body: [post] },
      'POST /api/v1/portal/league-posts/p1/contact': { status: 204 },
    })
    await userEvent.selectOptions(await screen.findByLabelText('Kind'), 'pickup')
    await userEvent.type(screen.getByLabelText('When'), '2031-05-09T18:00')
    await userEvent.type(screen.getByLabelText('Title'), 'Pickup futsal')
    await userEvent.type(screen.getByLabelText('Details'), 'Need four more players.')
    await userEvent.click(screen.getByRole('button', { name: 'Post' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url === '/api/v1/portal/league-posts')).toBe(true))
    expect(calls.find((c) => c.url === '/api/v1/portal/league-posts' && c.method === 'POST')?.body).toMatchObject({ kind: 'pickup', location_id: 'l1', title: 'Pickup futsal', category: 'other' })
    const [reply] = await screen.findAllByRole('button', { name: 'Reply to Keeper wanted' })
    if (!reply) throw new Error('reply button expected')
    await userEvent.click(reply)
    const dialog = await screen.findByRole('dialog', { name: 'Reply to "Keeper wanted"' })
    await userEvent.type(within(dialog).getByLabelText('Message'), 'I can play in goal on Sundays.')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(calls.some((c) => c.url === '/api/v1/portal/league-posts/p1/contact')).toBe(true))
    expect(calls.find((c) => c.url === '/api/v1/portal/league-posts/p1/contact')?.body).toEqual({ message: 'I can play in goal on Sundays.' })
  })
})
