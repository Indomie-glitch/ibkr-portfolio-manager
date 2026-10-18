import { useEffect } from 'react'
import { sizeWindowFor } from '../../desktop/appWindow.js'
import { SpinnerIcon } from '../../components/icons.jsx'
import { AppIcon } from './parts.jsx'

// "Starting up…" while the app's backend starts, or "Signing in…" when the app signs in by itself
function Startup({ label = 'Starting up…' }) {
  useEffect(() => {
    sizeWindowFor('startup')
  }, [])
  return (
    <div className="setup startup">
      <AppIcon size={72} />
      <p className="startup-name">Portfolio Manager</p>
      <p className="startup-status">
        <SpinnerIcon size={16} /> {label}
      </p>
    </div>
  )
}

export default Startup
