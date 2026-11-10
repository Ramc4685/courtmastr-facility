import type { Config } from 'tailwindcss'

// Colours are CSS variables (RGB channels) so one palette serves light and dark; see src/index.css.
const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`

export default {
  content: ['index.html', 'src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: token('bg'),
        surface: token('surface'),
        'surface-2': token('surface-2'),
        border: token('border'),
        fg: token('fg'),
        muted: token('muted'),
        primary: token('primary'),
        'primary-hover': token('primary-hover'),
        'on-primary': token('on-primary'),
        accent: token('accent'),
        danger: token('danger'),
        'on-danger': token('on-danger'),
        success: token('success'),
        warning: token('warning'),
        info: token('info'),
        rail: token('rail'),
        'rail-fg': token('rail-fg'),
        'rail-muted': token('rail-muted'),
        'rail-active': token('rail-active'),
      },
      fontFamily: {
        sans: ['"Inter var"', 'Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      borderRadius: { DEFAULT: '0.5rem' },
      boxShadow: { card: '0 1px 2px rgb(0 0 0 / 0.06), 0 1px 3px rgb(0 0 0 / 0.04)' },
    },
  },
  plugins: [],
} satisfies Config
