import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './app/App'
import './index.css'
import { APP_NAME } from './lib/format'
import { applyTheme, readTheme } from './lib/theme'

document.title = APP_NAME
applyTheme(readTheme())

createRoot(document.getElementById('root') as HTMLElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
