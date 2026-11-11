import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { parseChangelog, RELEASES } from '../../lib/changelog'
import { WhatsNewPage } from './WhatsNewPage'

const SAMPLE = `# Changelog
intro text

## [Unreleased]

### Added
- A **new** thing
- Another thing

## [Empty] - 2026-01-01

### Fixed

## [1.0.0] - 2026-02-02

### Changed
- Old thing
`

describe('changelog', () => {
  it('parses releases, groups and items and drops empty releases', () => {
    expect(parseChangelog(SAMPLE)).toEqual([
      { title: 'Unreleased', groups: [{ heading: 'Added', items: ['A **new** thing', 'Another thing'] }] },
      { title: '1.0.0 · 2026-02-02', groups: [{ heading: 'Changed', items: ['Old thing'] }] },
    ])
  })

  it('ships a changelog with an Unreleased section on top', () => {
    expect(RELEASES[0].title).toBe('Unreleased')
  })

  it('renders each release as a labelled list with bold text', () => {
    render(<MemoryRouter><WhatsNewPage releases={parseChangelog(SAMPLE)} /></MemoryRouter>)
    expect(screen.getByRole('heading', { level: 1, name: "What's new" })).toBeInTheDocument()
    const added = screen.getByRole('region', { name: 'Unreleased: Added' })
    expect(within(added).getAllByRole('listitem')).toHaveLength(2)
    expect(within(added).getByText('new').tagName).toBe('STRONG')
  })
})
