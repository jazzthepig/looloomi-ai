import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { AuthProvider } from './context/AuthContext.jsx'

// Lightweight analytics — fire-and-forget to /api/v1/analytics/track
// Writes to analytics_events in Supabase. No third-party, full data ownership.
export const track = (event, props = {}) => {
  try {
    fetch('/api/v1/analytics/track', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        event,
        props,
        path: window.location.pathname,
        referrer: document.referrer || null,
        ts: new Date().toISOString(),
      }),
    }).catch(() => {}) // never throws, never blocks
  } catch (_) {}
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <AuthProvider>
      <App />
    </AuthProvider>
  </StrictMode>,
)
