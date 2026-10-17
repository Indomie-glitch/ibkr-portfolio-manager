import { useCallback, useEffect, useState } from 'react'
import { cancelOrder, fetchOrders, watchOrders } from '../lib/api.js'
import { formatMoney, formatNumber } from '../lib/format.js'

const TYPE_WORDS = { LMT: 'Limit', MKT: 'Market' }
const TIF_WORDS = { DAY: 'Day', GTC: 'GTC' }
// What IBKR's order statuses look like here (Figma "M6 / 5 Orders")
const WORKING = new Set(['PendingSubmit', 'ApiPending', 'PreSubmitted', 'Submitted', 'PendingCancel'])

function statusPill(status) {
  if (status === 'Filled') return { label: 'Filled', tone: 'gain' }
  if (status === 'PendingCancel') return { label: 'Cancelling', tone: 'accent' }
  if (WORKING.has(status)) return { label: 'Working', tone: 'accent' }
  if (status === 'Cancelled' || status === 'ApiCancelled') return { label: 'Cancelled', tone: 'neutral' }
  return { label: status || '—', tone: 'neutral' }
}

const placedTime = (iso) =>
  iso ? new Date(iso).toLocaleTimeString('en-AU', { hour: 'numeric', minute: '2-digit' }).replace(' ', '') : '—'

function OrderRow({ order, canTrade, tradeReason, onModify, onCancel, cancelling }) {
  const pill = statusPill(order.status)
  const open = WORKING.has(order.status)
  const price = order.status === 'Filled' ? order.avg_fill_price : order.limit_price
  const type = [TYPE_WORDS[order.order_type] ?? order.order_type, TIF_WORDS[order.tif] ?? order.tif].filter(Boolean).join(' · ')
  return (
    <div className="orders-row" role="row">
      <div className="orders-symbol" role="cell">
        <span className="holding-symbol">{order.symbol}</span>
        {order.name && <span className="company">{order.name}</span>}
      </div>
      <span
        className="orders-placed"
        role="cell"
        title={order.placed ? undefined : 'IBKR doesn’t say when this order was placed (it wasn’t placed from this app session)'}
      >
        {placedTime(order.placed)}
      </span>
      <span className="orders-side" role="cell">
        <span className={`status-pill ${order.action === 'BUY' ? 'gain' : 'loss'}`}>{order.action === 'BUY' ? 'Buy' : 'Sell'}</span>
      </span>
      <span className="orders-qty num" role="cell">
        {formatNumber(order.status === 'Filled' ? order.filled : order.quantity, 0)}
      </span>
      <span className="orders-type" role="cell">
        {type || '—'}
      </span>
      <span className="orders-price num" role="cell">
        {order.order_type === 'MKT' && order.status !== 'Filled' ? 'Market' : formatMoney(price, order.currency)}
      </span>
      <span className="orders-status" role="cell">
        <span className={`status-pill ${pill.tone}`}>{pill.label}</span>
      </span>
      <span className="orders-actions" role="cell">
        {open && order.order_id && (
          <>
            {/* Changing goes through the ticket and a review, like a new order */}
            <button
              type="button"
              className="small-button"
              disabled={!canTrade || !['LMT', 'MKT'].includes(order.order_type)}
              title={canTrade ? undefined : tradeReason}
              onClick={() => onModify(order)}
            >
              Modify
            </button>
            <button
              type="button"
              className="small-button destructive"
              disabled={!canTrade || cancelling}
              title={canTrade ? undefined : tradeReason}
              onClick={() => onCancel(order)}
            >
              {cancelling ? 'Cancelling…' : 'Cancel'}
            </button>
          </>
        )}
      </span>
    </div>
  )
}

function OrdersTable({ title, orders, empty, ...rowProps }) {
  return (
    <section className="orders-section">
      <h2 className="orders-section-title">{title}</h2>
      <div className="orders-table" role="table" aria-label={title}>
        <div className="orders-row orders-header" role="row">
          <span className="orders-symbol" role="columnheader">Symbol</span>
          <span className="orders-placed" role="columnheader">Placed</span>
          <span className="orders-side" role="columnheader">Side</span>
          <span className="orders-qty" role="columnheader">Qty</span>
          <span className="orders-type" role="columnheader">Type</span>
          <span className="orders-price" role="columnheader">Price</span>
          <span className="orders-status" role="columnheader">Status</span>
          <span className="orders-actions" role="columnheader" />
        </div>
        {orders.map((o) => (
          <OrderRow key={o.perm_id ?? o.order_id} order={o} cancelling={rowProps.cancellingId === o.order_id} {...rowProps} />
        ))}
        {orders.length === 0 && <p className="orders-empty">{empty}</p>}
      </div>
    </section>
  )
}

// A failed request in words: the backend's own message (e.g. which IBKR list failed), or, when no
// answer came back at all ("Failed to fetch"), what that usually means
function errorText(err) {
  if (err.status) return err.message
  return 'The backend didn’t answer. Check that it’s running; the backend terminal shows the details.'
}

function OrdersError({ title, message }) {
  return (
    <div className="error" role="alert">
      <strong>{title}</strong>
      <div className="error-detail">{message}</div>
    </div>
  )
}

// Open orders, and today's filled and cancelled orders. Updates live while open.
function Orders({ refreshKey, trading, onModify }) {
  const [tab, setTab] = useState('open')
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [cancellingId, setCancellingId] = useState(null)

  const load = useCallback(() => {
    fetchOrders()
      .then((orders) => {
        setData(orders)
        setError(null)
      })
      .catch((err) => setError({ title: 'Couldn’t load your orders', message: errorText(err) }))
  }, [])

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect
    load()
  }, [load, refreshKey])

  // Any order update (a fill, a cancel, a new order) reloads the lists
  useEffect(() => {
    const controller = new AbortController()
    let timer
    watchOrders((name) => {
      if (name !== 'order') return
      clearTimeout(timer)
      timer = setTimeout(load, 300)
    }, controller.signal).catch(() => {}) // stream unavailable: Refresh still works
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [load])

  async function cancel(order) {
    setCancellingId(order.order_id)
    try {
      await cancelOrder(order.order_id)
    } catch (err) {
      setError({ title: 'Couldn’t cancel the order', message: errorText(err) })
    } finally {
      setCancellingId(null)
      load()
    }
  }

  if (!data) {
    return error ? (
      <div className="page-body">
        <OrdersError {...error} />
      </div>
    ) : (
      <p className="empty">Loading orders…</p>
    )
  }

  const canTrade = Boolean(trading?.can_trade)
  const rowProps = { canTrade, tradeReason: trading?.reason ?? 'Trading is unavailable', onModify, onCancel: cancel, cancellingId }
  const tabs = [
    ['open', `Open (${data.open.length})`],
    ['filled', `Filled today (${data.filled_today.length})`],
    ['cancelled', data.cancelled.length ? `Cancelled (${data.cancelled.length})` : 'Cancelled'],
  ]

  return (
    <div className="page-body orders-page">
      <div className="segmented orders-tabs" role="group" aria-label="Orders">
        {tabs.map(([value, label]) => (
          <button key={value} type="button" aria-pressed={tab === value} onClick={() => setTab(value)}>
            {label}
          </button>
        ))}
      </div>
      {error && <OrdersError {...error} />}
      {tab === 'open' && <OrdersTable title="Open orders" orders={data.open} empty="No open orders." {...rowProps} />}
      {tab === 'filled' && (
        <OrdersTable title="Filled today" orders={data.filled_today} empty="No orders filled today." {...rowProps} />
      )}
      {tab === 'cancelled' && (
        <OrdersTable title="Cancelled today" orders={data.cancelled} empty="No cancelled orders today." {...rowProps} />
      )}
    </div>
  )
}

export default Orders
