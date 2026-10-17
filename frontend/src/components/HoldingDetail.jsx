import { useEffect, useState } from 'react'
import { fetchHistory, fetchProfile } from '../api.js'
import { companyName, formatMoney, formatNumber, formatPercent, trendClass } from '../format.js'
import { benchmarkName } from '../holdings.js'
import { useFetch } from '../useFetch.js'
import AboutSection from './detail/AboutSection.jsx'
import AiSummarySection from './detail/AiSummarySection.jsx'
import DisclosureSection from './detail/DisclosureSection.jsx'
import KeyStats from './detail/KeyStats.jsx'
import NewsSection from './detail/NewsSection.jsx'
import PerformanceSection from './detail/PerformanceSection.jsx'
import PriceChart from './PriceChart.jsx'

const RANGES = ['1D', '1W', '1M', '3M', '1Y', 'All']
const RANGE_WORDS = { '1W': 'past week', '1M': 'past month', '3M': 'past 3 months', '1Y': 'past year' }

// Change over the selected range: today's move for 1D (vs the previous close),
// otherwise from the first to the last bar of the chart
function rangeChange(range, bars, quote) {
  if (range === '1D') {
    if (quote?.day_change == null) return null
    return { change: quote.day_change, pct: quote.day_change_pct, words: 'today' }
  }
  if (!bars || bars.length < 2) return null
  const first = bars[0].close
  const last = bars.at(-1).close
  const words = RANGE_WORDS[range] ?? `since ${new Date(bars[0].time).getFullYear()}`
  return { change: last - first, pct: ((last - first) / first) * 100, words }
}

function PositionStat({ label, value, className = '' }) {
  return (
    <div className="position-stat">
      <p className="position-stat-label">{label}</p>
      <p className={`position-stat-value num ${className}`}>{value}</p>
    </div>
  )
}

function HoldingDetail({ holding, refreshKey, trading, onTrade }) {
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

  // The profile feeds the About section and gives the full company name for the header
  const profile = useFetch(() => fetchProfile(holding.con_id), holding.con_id)
  const fullName = profile.data?.long_name ?? companyName(holding)
  const shortName = profile.data?.short_name ?? holding.symbol

  const price = holding.last
  // Buy and Sell open the order ticket while trading is on (TRADING_MODE); otherwise they say why not
  const canTrade = Boolean(trading?.can_trade && onTrade)
  const tradeTitle = canTrade ? undefined : (trading?.reason ?? 'Trading is unavailable')
  const tradeStock = { con_id: holding.con_id, symbol: holding.symbol, shortName, currency: holding.currency, last: holding.last }
  const move = rangeChange(range, current.bars, holding.quote)
  const c = holding.currency

  return (
    <div className="detail">
      <div className="detail-header">
        <div>
          <h2 className="detail-symbol">{holding.symbol}</h2>
          <p className="detail-subtitle">
            {fullName} · {holding.exchange} · {c}
          </p>
        </div>
        <div className="spacer" />
        <div className="trade-buttons">
          <button
            type="button"
            className="pill-button secondary"
            disabled={!canTrade || holding.not_owned}
            title={holding.not_owned ? 'You don’t own this stock' : tradeTitle}
            onClick={() => onTrade(tradeStock, 'SELL')}
          >
            Sell
          </button>
          <button
            type="button"
            className="pill-button primary"
            disabled={!canTrade}
            title={tradeTitle}
            onClick={() => onTrade(tradeStock, 'BUY')}
          >
            Buy
          </button>
        </div>
      </div>

      <div className="price-row">
        <div>
          <p className="detail-price num">{formatMoney(price, c)}</p>
          <p className={`detail-change num ${trendClass(move?.change)}`}>
            {move
              ? `${formatMoney(move.change, c, { signed: true })} (${formatPercent(move.pct)}) ${move.words}`
              : '…'}
          </p>
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

      <div id="price-chart">
        <PriceChart
          bars={current.bars}
          range={range}
          avgCost={holding.avg_cost}
          currency={c}
          loading={loading}
          error={current.error}
        />
      </div>

      <section id="your-position">
        <h3 className="section-title">Your position</h3>
        {holding.not_owned ? (
          <div className="not-owned">
            <div>
              <p className="not-owned-title">You don’t own {shortName}</p>
              <p className="not-owned-text">Buy shares to start tracking your cost, P&amp;L and dividends here.</p>
            </div>
            <button
              type="button"
              className="pill-button primary"
              disabled={!canTrade}
              title={tradeTitle}
              onClick={() => onTrade(tradeStock, 'BUY')}
            >
              Buy
            </button>
          </div>
        ) : (
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
        )}
      </section>

      <DisclosureSection id="keyStats" title="Key statistics" note="Delayed 15 min">
        <KeyStats holding={holding} />
      </DisclosureSection>

      <DisclosureSection id="about" title={`About ${shortName}`}>
        <AboutSection profile={profile.data} error={profile.error} loading={profile.loading} />
      </DisclosureSection>

      {/* AI summaries are written for holdings only */}
      {!holding.not_owned && <AiSummarySection holding={holding} name={shortName} />}

      <DisclosureSection id="news" title="News">
        <NewsSection holding={holding} companyName={shortName} />
      </DisclosureSection>

      <DisclosureSection id="performance" title="Performance" note={`Total return vs ${benchmarkName(holding)}`}>
        <PerformanceSection holding={holding} />
      </DisclosureSection>
    </div>
  )
}

export default HoldingDetail
