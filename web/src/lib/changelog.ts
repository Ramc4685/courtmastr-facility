import raw from '../../../CHANGELOG.md?raw'

export type Release = { title: string; groups: { heading: string; items: string[] }[] }

/** The three levels CHANGELOG.md uses: `## [Version] - date`, `### Added`, `- item`. Anything else is ignored. */
export function parseChangelog(markdown: string): Release[] {
  const releases: Release[] = []
  for (const line of markdown.split('\n')) {
    if (line.startsWith('## ')) {
      releases.push({ title: line.slice(3).replace(/[[\]]/g, '').replace(' - ', ' · '), groups: [] })
    } else if (line.startsWith('### ')) {
      releases.at(-1)?.groups.push({ heading: line.slice(4).trim(), items: [] })
    } else if (line.startsWith('- ')) {
      releases.at(-1)?.groups.at(-1)?.items.push(line.slice(2).trim())
    }
  }
  return releases.filter((r) => r.groups.some((g) => g.items.length))
}

export const RELEASES = parseChangelog(raw)
