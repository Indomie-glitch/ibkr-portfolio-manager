import HoldingDetail from '../components/HoldingDetail.jsx'
import HoldingsList from '../components/HoldingsList.jsx'

function Positions({ holdings, selectedId, onSelect, refreshKey, stale }) {
  // Fall back to the biggest holding if nothing (or something no longer held) is selected
  const selected = holdings.find((h) => h.con_id === selectedId) ?? holdings[0]

  if (!selected) {
    return <p className="empty">No open positions.</p>
  }

  return (
    <div className={`positions-page ${stale ? 'stale' : ''}`}>
      <HoldingsList holdings={holdings} selectedId={selected.con_id} onSelect={onSelect} />
      <HoldingDetail holding={selected} refreshKey={refreshKey} />
    </div>
  )
}

export default Positions
