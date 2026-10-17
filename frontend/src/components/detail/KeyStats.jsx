import { fetchStats } from '../../lib/api.js'
import { formatCompactNumber, formatDate, formatNumber, formatPercent } from '../../lib/format.js'
import { useFetch } from '../../hooks/useFetch.js'

function range(low, high) {
  return low == null || high == null ? '—' : `${formatNumber(low)} – ${formatNumber(high)}`
}

function dividend(rate, yieldPct) {
  if (rate == null && yieldPct == null) return '—'
  const yieldText = yieldPct == null ? '' : ` (${formatPercent(yieldPct, { signed: false })})`
  return `${rate == null ? '—' : formatNumber(rate)}${yieldText}`
}

// Market fields come from IB with the quotes (refreshed every minute);
// the slower fields come from Yahoo Finance (cached for an hour on the backend).
function KeyStats({ holding }) {
  const { data: stats, error, loading } = useFetch(() => fetchStats(holding.con_id), holding.con_id)
  const q = holding.quote ?? {}
  const s = stats ?? {}
  const yahooValue = (format) => (loading ? '…' : format())

  const columns = [
    [
      ['Prev close', formatNumber(q.prev_close)],
      ['Open', formatNumber(q.open)],
      ['Bid', formatNumber(q.bid)],
      ['Ask', formatNumber(q.ask)],
    ],
    [
      ['Day’s range', range(q.day_low, q.day_high)],
      ['52W range', yahooValue(() => range(s.fifty_two_week_low, s.fifty_two_week_high))],
      ['Volume', formatCompactNumber(q.volume)],
      ['Avg volume', formatCompactNumber(q.avg_volume)],
    ],
    [
      ['Market cap', yahooValue(() => formatCompactNumber(s.market_cap))],
      ['Beta (5Y)', yahooValue(() => formatNumber(s.beta))],
      ['P/E (TTM)', yahooValue(() => formatNumber(s.pe_ttm))],
      ['EPS (TTM)', yahooValue(() => formatNumber(s.eps_ttm))],
    ],
    [
      ['Earnings date', yahooValue(() => formatDate(s.earnings_date))],
      ['Fwd div & yield', yahooValue(() => dividend(s.dividend_rate, s.dividend_yield))],
      ['Ex-div date', yahooValue(() => formatDate(s.ex_dividend_date))],
      ['1Y target', yahooValue(() => formatNumber(s.target_price))],
    ],
  ]

  return (
    <>
      <div className="key-stats">
        {columns.map((rows, i) => (
          <dl className="key-stats-column" key={i}>
            {rows.map(([label, value]) => (
              <div className="key-stat" key={label}>
                <dt>{label}</dt>
                <dd className="num">{value}</dd>
              </div>
            ))}
          </dl>
        ))}
      </div>
      {error && <p className="section-footnote">Some statistics are unavailable from Yahoo Finance right now.</p>}
      {!error && q.bid == null && (
        <p className="section-footnote">Bid and ask need live delayed quotes from IB, which aren’t available right now.</p>
      )}
    </>
  )
}

export default KeyStats
