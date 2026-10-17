import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { IN_APP } from './lib/api.js'

// The Mac app hides its title bar: CSS leaves room for the traffic lights (.in-app)
if (IN_APP) document.documentElement.classList.add('in-app')

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
