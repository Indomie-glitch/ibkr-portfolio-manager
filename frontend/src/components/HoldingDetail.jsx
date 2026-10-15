import { useEffect, useState } from 'react'
import { fetchHistory } from '../api.js'
import { companyName, formatMoney, formatNumber, formatPercent, trendClass } from '../format.js'
import AiSummaryCard from './AiSummaryCard.jsx'
import PriceChart from './PriceChart.jsx'

const RANGES = ['1D', '1W', '1M', '3M', '1Y', 'All']

function PositionStat({ label, value, className = '' }) {
  return (
    <div className="position-stat">
      <p className="position-stat-label">{label}</p>
      <p className={`position-stat-value num ${className}`}>{value}</p>
    </div>
  )
}

function HoldingDetail({ holding, refreshKey }) {
  const [range, setRange] = useState('1M')
  // Remember which holding and range the bars belong to, so we never draw one stock's
  // history under another stock's name while the new data loads.
  const [history, setHistory] = useState({ key: null, bars: null, error: null })
  const key = `${holding.con_id}-${range}`

  useEffect(() => {
    let ignore = false
    fetchHistory(holding.con_id, range)
      .then((data) => {
        if (!ignore) setHistory({ key, bars: data.bars, error: null })
      })
      .catch((err) => {
        if (!ignore) setHistory({ key, bars: null, error: err.message })
      })
    return () => {
      ignore = true
    }
  }, [holding.con_id, range, key, refreshKey])

  const current = history.key === key ? history : { bars: null, error: null }
  const loading = history.key !== key

  const quote = holding.quote
  const price = holding.last
  const change = quote?.day_change
  const c = holding.currency

  return (
    <div className="detail">
      <div className="detail-header">
        <div>
          <h2 className="detail-symbol">{holding.symbol}</h2>
          <p className="detail-subtitle">
            {companyName(holding)} · {holding.exchange} · {c}
          </p>
        </div>
        <div className="spacer" />
        <button type="button" className="button-muted" disabled title="Trading arrives in milestone 6">
          Trade · soon
        </button>
      </div>

      <div className="price-row">
        <div>
          <p className="detail-price num">{formatMoney(price, c)}</p>
          {change != null && (
            <p className={`detail-change num ${trendClass(change)}`}>
              {formatMoney(change, c, { signed: true })} ({formatPercent(quote.day_change_pct)}) since previous close
            </p>
          )}
        </div>
        <div className="spacer" />
        <div className="segmented range-control" role="group" aria-label="Chart range">
          {RANGES.map((r) => (
            <button key={r} type="button" aria-pressed={range === r} onClick={() => setRange(r)}>
              {r}
            </button>
          ))}
        </div>
      </div>

      <PriceChart
        bars={current.bars}
        range={range}
        avgCost={holding.avg_cost}
        currency={c}
        loading={loading}
        error={current.error}
      />

      <section>
        <h3 className="section-title">Your position</h3>
        <div className="position-stats">
          <PositionStat label="Quantity" value={formatNumber(holding.quantity, 0)} />
          <PositionStat label="Average cost" value={formatMoney(holding.avg_cost, c)} />
          <PositionStat label="Cost basis" value={formatMoney(holding.cost_basis, c)} />
          <PositionStat label="Market value" value={formatMoney(holding.market_value, c)} />
          <PositionStat
            label="Unrealised P&L"
            className={trendClass(holding.unrealized_pnl)}
            value={`${formatMoney(holding.unrealized_pnl, c, { signed: true })} (${formatPercent(holding.unrealized_pnl_pct)})`}
          />
          <PositionStat
            label="Portfolio weight"
            value={formatPercent(holding.weight, { signed: false, decimals: 1 })}
          />
        </div>
      </section>

      <AiSummaryCard
        title="AI summary"
        buttonLabel="Summarise"
        description={`No summary yet. Get a short overview of what ${companyName(holding)} does, recent news, and how the price has moved this month.`}
      />
    </div>
  )
}

export default HoldingDetail
