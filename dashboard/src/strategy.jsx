import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import StrategyPage from './components/StrategyPage.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <StrategyPage />
  </StrictMode>,
)
