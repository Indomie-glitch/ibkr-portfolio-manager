import { useState } from 'react'
import { companyName, formatMoney, formatNumber, formatPercent, trendClass } from '../lib/format.js'
import { ChevronIcon, SortArrowIcon } from './icons.jsx'

// Each sortable column says which value to sort by. Money columns use the AUD copy
// so a US$ holding and an A$ holding are compared in the same currency.
const COLUMNS = [
  { key: 'symbol', label: 'Symbol', sortValue: (h) => h.symbol, text: true },
  { key: 'quantity', label: 'Qty', className: 'col-qty', sortValue: (h) => h.quantity },
  { key: 'avg_cost', label: 'Avg cost', className: 'col-price', sortValue: (h) => h.avg_cost_base },
  { key: 'last', label: 'Last', className: 'col-price', sortValue: (h) => h.last_base },
  { key: 'market_value', label: 'Market value', className: 'col-money', sortValue: (h) => h.market_value_base },
  { key: 'unrealized_pnl', label: 'Unrealised P&L', className: 'col-money', sortValue: (h) => h.unrealized_pnl_base },
]

function sortHoldings(holdings, column, direction) {
  const flip = direction === 'asc' ? 1 : -1
  return [...holdings].sort((a, b) => {
    const va = column.sortValue(a)
    const vb = column.sortValue(b)
    // Missing values always go to the bottom, whichever way we sort
    if (va == null) return vb == null ? 0 : 1
    if (vb == null) return -1
    return (column.text ? va.localeCompare(vb) : va - vb) * flip
  })
}

function PositionsTable({ holdings, onOpen }) {
  const [sort, setSort] = useState({ key: 'market_value', direction: 'desc' })
  const column = COLUMNS.find((c) => c.key === sort.key)
  const rows = sortHoldings(holdings, column, sort.direction)

  function toggleSort(next) {
    setSort((current) =>
      current.key === next.key
        ? { key: next.key, direction: current.direction === 'asc' ? 'desc' : 'asc' }
        : // New column: A→Z for text, biggest first for numbers
          { key: next.key, direction: next.text ? 'asc' : 'desc' },
    )
  }

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
                {COLUMNS.map((c) => {
                  const active = c.key === sort.key
                  return (
                    <th
                      key={c.key}
                      className={c.className}
                      aria-sort={active ? (sort.direction === 'asc' ? 'ascending' : 'descending') : undefined}
                    >
                      <button
                        type="button"
                        className={`sort-button ${active ? 'active' : ''}`}
                        onClick={() => toggleSort(c)}
                      >
                        {c.label}
                        {active && <SortArrowIcon direction={sort.direction} />}
                      </button>
                    </th>
                  )
                })}
                <th aria-label="Open" />
              </tr>
            </thead>
            <tbody>
              {rows.map((h) => {
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
                      <div className="company" title={h.name_truncated ? 'Name shortened by IB' : undefined}>
                        {companyName(h)}
                      </div>
                    </td>
                    <td className="num">{formatNumber(h.quantity, 0)}</td>
                    <td className="num">{formatNumber(h.avg_cost)}</td>
                    <td className="num">{formatNumber(h.last)}</td>
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
