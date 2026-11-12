import { Card, PageHeader } from '../../components/PageHeader'
import { RELEASES, type Release } from '../../lib/changelog'

/** **bold** is the only inline markup CHANGELOG.md uses. */
function Inline({ text }: { text: string }) {
  return (
    <>
      {text.split(/\*\*(.+?)\*\*/g).map((part, i) => (i % 2 ? <strong key={i}>{part}</strong> : part))}
    </>
  )
}

export function WhatsNewPage({ releases = RELEASES }: { releases?: Release[] }) {
  return (
    <>
      <PageHeader title="What's new" description="Changes you can see, newest first." />
      <div className="space-y-4">
        {releases.map((release) => (
          <Card key={release.title} title={release.title}>
            {release.groups.map((group) => (
              <section key={group.heading} aria-label={`${release.title}: ${group.heading}`} className="mt-3 first:mt-0">
                <h3 className="text-sm font-semibold text-muted">{group.heading}</h3>
                <ul className="mt-1 list-disc space-y-1 pl-5">
                  {group.items.map((item) => (
                    <li key={item}>
                      <Inline text={item} />
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </Card>
        ))}
      </div>
    </>
  )
}
