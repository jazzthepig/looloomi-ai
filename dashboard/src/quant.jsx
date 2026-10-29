import './index.css'   // shared design foundation — fonts + navy field (single source of truth)
import { createRoot } from 'react-dom/client'
import QuantMonitor from './components/QuantMonitor.jsx'
import './lib/chunkReload.js'   // stale-chunk recovery after a deploy

createRoot(document.getElementById('root')).render(<QuantMonitor />)
