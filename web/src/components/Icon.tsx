import type { IconName } from '../app/nav'

// Simple 20px line icons drawn for this product.
const paths: Record<IconName, string> = {
  home: 'M3 9.5 10 4l7 5.5V16a1 1 0 0 1-1 1h-4v-5H8v5H4a1 1 0 0 1-1-1z',
  pin: 'M10 17s5-4.6 5-8.5A5 5 0 0 0 5 8.5C5 12.4 10 17 10 17zm0-6.5a2 2 0 1 0 0-4 2 2 0 0 0 0 4z',
  users: 'M7.5 9a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM2.5 16c0-2.5 2.2-4.5 5-4.5s5 2 5 4.5M13 4.3a2.5 2.5 0 0 1 0 4.4M14.5 11.8c1.8.5 3 2.1 3 4.2',
  shield: 'M10 3 4 5.5v4c0 3.6 2.5 6.6 6 7.5 3.5-.9 6-3.9 6-7.5v-4zM7.5 10l2 2 3-3.5',
  list: 'M7 5h10M7 10h10M7 15h10M3.5 5h.01M3.5 10h.01M3.5 15h.01',
  gear: 'M10 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M4.7 15.3l1.4-1.4M13.9 6.1l1.4-1.4',
  calendar: 'M4 5h12v11H4zM4 8.5h12M7 3v3M13 3v3',
  ticket: 'M3 6h14v2.5a1.5 1.5 0 0 0 0 3V14H3v-2.5a1.5 1.5 0 0 0 0-3zM12 6v8',
  person: 'M10 9.5a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM4 17c0-3 2.7-5 6-5s6 2 6 5',
  card: 'M3 5.5h14v9H3zM3 8.5h14M6 12h3',
  clipboard: 'M7 4h6v2H7zM5.5 5H4v12h12V5h-1.5M7 10h6M7 13h4',
  pen: 'M13.5 3.5l3 3L8 15l-4 1 1-4zM11.5 5.5l3 3',
  cash: 'M2.5 6h15v8h-15zM10 12a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM5 8v4M15 8v4',
  cart: 'M3 4h2l1.6 8h8.4l1.5-6H6M8 16h.01M14 16h.01',
  door: 'M5 17V3h9v14M3 17h14M11 10h.01',
  trophy: 'M6 4h8v4a4 4 0 0 1-8 0zM6 5H3.5a2.5 2.5 0 0 0 2.6 3M14 5h2.5a2.5 2.5 0 0 1-2.6 3M10 12v3M7 17h6',
  clock: 'M10 17a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM10 6v4l2.5 2',
  mail: 'M3 5h14v10H3zM3 5l7 6 7-6',
  pulse: 'M2.5 10h3l2-5 3 10 2-5h5',
  chart: 'M4 16V9M8 16V4M12 16v-5M16 16V7M3 16.5h14',
  plug: 'M7 3v4M13 3v4M5 7h10v2a5 5 0 0 1-10 0zM10 14v3',
  phone: 'M6.5 2.5h7v15h-7zM9.5 15h1',
}

export function Icon({ name, className = 'h-5 w-5' }: { name: IconName; className?: string }) {
  return (
    <svg viewBox="0 0 20 20" className={className} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={paths[name]} />
    </svg>
  )
}

export function BrandMark({ className = 'h-8 w-8' }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="rgb(var(--primary))" />
      <rect x="7" y="9" width="18" height="14" rx="1.5" fill="none" stroke="rgb(var(--on-primary))" strokeWidth="2" />
      <path d="M16 9v14M7 16h4M21 16h4" stroke="rgb(var(--on-primary))" strokeWidth="2" />
      <circle cx="16" cy="16" r="2.5" fill="rgb(var(--accent))" />
    </svg>
  )
}
