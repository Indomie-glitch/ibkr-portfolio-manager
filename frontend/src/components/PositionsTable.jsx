import { formatNumber } from '../format.js'

function PositionsTable({ positions }) {
  if (positions.length === 0) {
    return <p className="empty">No open positions.</p>
  }

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th className="num">Quantity</th>
            <th className="num">Avg cost</th>
            <th className="num">Cost basis</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p, i) => (
            <tr key={`${p.symbol}-${i}`}>
              <td className="symbol">{p.symbol}</td>
              <td className="num">{formatNumber(p.quantity, 0)}</td>
              <td className="num">{formatNumber(p.avg_cost)}</td>
              <td className="num">{formatNumber(p.quantity * p.avg_cost)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default PositionsTable
