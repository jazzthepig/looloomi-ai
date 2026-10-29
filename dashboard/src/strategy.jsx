import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import StrategyPage from './components/StrategyPage.jsx'
import './lib/chunkReload.js'   // stale-chunk recovery after a deploy

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <StrategyPage />
  </StrictMode>,
)
