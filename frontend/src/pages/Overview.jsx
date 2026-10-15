import { formatMoney, formatPercent, trendClass } from '../format.js'
import AiSummaryCard from '../components/AiSummaryCard.jsx'
import AllocationCard from '../components/AllocationCard.jsx'
import PositionsTable from '../components/PositionsTable.jsx'
import StatCard from '../components/StatCard.jsx'

function Overview({ account, holdings, onOpenHolding }) {
  const c = account.currency
  const pnl = account.unrealized_pnl
  // P&L as a percentage of what was paid: today's value minus the gain
  const costBasis = account.positions_value - (pnl ?? 0)
  const pnlPct = pnl != null && costBasis ? (pnl / costBasis) * 100 : null
  const cashShare = account.net_liquidation ? (account.cash / account.net_liquidation) * 100 : null

  return (
    <>
      <section>
        <p className="nlv-label">Net Liquidation Value</p>
        <p className="nlv-value num">{formatMoney(account.net_liquidation, c)}</p>
        {pnl != null && (
          <p className="nlv-change">
            <span className={`num ${trendClass(pnl)}`}>
              {formatMoney(pnl, c, { signed: true })} ({formatPercent(pnlPct)})
            </span>
            <span>unrealised P&amp;L</span>
          </p>
        )}
      </section>

      <div className="stat-cards">
        <StatCard
          label="Cash"
          value={formatMoney(account.cash, c)}
          caption={`${formatPercent(cashShare, { signed: false, decimals: 1 })} of account`}
        />
        <StatCard
          label="Positions Value"
          value={formatMoney(account.positions_value, c)}
          caption={`${holdings.length} holdings`}
        />
        <StatCard label="Buying Power" value={formatMoney(account.buying_power, c)} caption="Available to trade" />
      </div>

      <div className="holdings-row">
        <PositionsTable holdings={holdings} onOpen={onOpenHolding} />
        {holdings.length > 0 && <AllocationCard holdings={holdings} currency={c} />}
      </div>

      <AiSummaryCard
        title="AI portfolio summary"
        buttonLabel="Summarise portfolio"
        description="No summary yet. Get a short overview of your whole portfolio: how it is split across stocks and markets, what is driving your P&L, and anything worth keeping an eye on."
      />
    </>
  )
}

export default Overview
