import { MARKETS } from '../lib/holdings.js'

// The All / ASX / US filter above a list of stocks (Positions, Markets, watchlists)
function MarketFilter({ market, onChange }) {
  return (
    <div className="list-filter">
      <div className="segmented" role="group" aria-label="Market">
        {MARKETS.map((m) => (
          <button key={m} type="button" aria-pressed={market === m} onClick={() => onChange(m)}>
            {m}
          </button>
        ))}
      </div>
    </div>
  )
}

export default MarketFilter
