import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import ShareCard from './components/ShareCard.jsx'
import './lib/chunkReload.js'   // stale-chunk recovery after a deploy

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ShareCard />
  </StrictMode>,
)
