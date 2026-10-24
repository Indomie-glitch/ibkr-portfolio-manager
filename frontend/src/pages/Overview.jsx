import { formatMoney, formatPercent, trendClass } from '../lib/format.js'
import AllocationCard from '../components/AllocationCard.jsx'
import PortfolioSummaryCard from '../components/PortfolioSummaryCard.jsx'
import PositionsTable from '../components/PositionsTable.jsx'
import StatCard from '../components/StatCard.jsx'

function Overview({ account, holdings, onOpenHolding }) {
  const c = account.currency
  const pnl = account.unrealized_pnl
  // P&L as a percentage of what was paid: today's value minus the gain
  const costBasis = account.positions_value - (pnl ?? 0)
  const pnlPct = pnl != null && costBasis ? (pnl / costBasis) * 100 : null
  const cashShare = account.net_liquidation ? (account.cash / account.net_liquidation) * 100 : null

  // Cash below zero in any currency is money owed to IBKR, charged interest daily (#289)
  const owed = account.negative_balances ?? []

  return (
    <>
      {owed.length > 0 && (
        <div className="borrow-warning" role="alert">
          <strong>You owe IBKR {owed.map((o) => formatMoney(o.amount, o.currency)).join(' and ')}.</strong>{' '}
          {owed.length === 1 ? 'That cash balance is' : 'Those cash balances are'} below zero, which is a loan from IBKR
          charged interest every day. Paying it off means converting another currency or adding cash in IBKR, or
          selling holdings in that currency.
        </div>
      )}

      {/* ids: where the portfolio summary's citation chips scroll to */}
      <section id="portfolio-value">
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

      <PortfolioSummaryCard onOpenHolding={onOpenHolding} />
    </>
  )
}

export default Overview
