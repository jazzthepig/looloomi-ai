import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import MethodologyPage from './components/MethodologyPage.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <MethodologyPage />
  </StrictMode>,
)
