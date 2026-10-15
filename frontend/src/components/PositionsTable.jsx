import { formatMoney, formatNumber, formatPercent, trendClass } from '../format.js'
import { ChevronIcon } from './icons.jsx'

function PositionsTable({ holdings, onOpen }) {
  return (
    <section className="card positions-card">
      <div className="card-header">
        <h2 className="card-title">Positions</h2>
        <div className="spacer" />
        <span className="card-caption">
          {holdings.length} holdings · click one to open it
        </span>
      </div>

      {holdings.length === 0 ? (
        <p className="empty">No open positions.</p>
      ) : (
        <div className="table-scroll">
          <table className="positions-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th className="col-qty">Qty</th>
                <th className="col-price">Avg cost</th>
                <th className="col-price">Last</th>
                <th className="col-money">Market value</th>
                <th className="col-money">Unrealised P&amp;L</th>
                <th aria-label="Open" />
              </tr>
            </thead>
            <tbody>
              {holdings.map((h) => {
                const trend = trendClass(h.unrealized_pnl)
                return (
                  <tr
                    key={h.con_id}
                    tabIndex={0}
                    onClick={() => onOpen(h.con_id)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        onOpen(h.con_id)
                      }
                    }}
                  >
                    <td>
                      <div className="symbol-row">
                        {h.symbol} <span className="currency-pill">{h.currency}</span>
                      </div>
                      <div className="company">{h.name}</div>
                    </td>
                    <td className="num">{formatNumber(h.quantity, 0)}</td>
                    <td className="num">{formatNumber(h.avg_cost)}</td>
                    <td className="num">{formatNumber(h.quote?.last ?? h.market_price)}</td>
                    <td className="num">{formatMoney(h.market_value, h.currency)}</td>
                    <td className={`num pnl ${trend}`}>
                      <div>{formatMoney(h.unrealized_pnl, h.currency, { signed: true })}</div>
                      <div className="pnl-pct">{formatPercent(h.unrealized_pnl_pct)}</div>
                    </td>
                    <td>
                      <ChevronIcon />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export default PositionsTable
