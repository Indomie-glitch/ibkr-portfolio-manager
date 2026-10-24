import { useEffect, useState } from 'react'
import { modifyOrder, placeOrder, watchOrders } from '../lib/api.js'
import { formatMoney } from '../lib/format.js'
import { outcomeUnknown } from '../lib/orderTicket.js'
import { CheckCircleIcon, CheckIcon, InfoIcon, WarningIcon } from './icons.jsx'

// IB statuses after which nothing more will happen to an order
const FINAL = new Set(['Filled', 'Cancelled', 'ApiCancelled', 'Inactive'])

const timeNow = () =>
  new Date().toLocaleTimeString('en-AU', { hour: 'numeric', minute: '2-digit', second: '2-digit' }).replace(' ', '')

function Line({ label, value, total = false }) {
  return (
    <div className={`estimate-line ${total ? 'total' : ''}`}>
      <span>{label}</span>
      <span className="num">{value}</span>
    </div>
  )
}

const TIF_WORDS = { DAY: 'Good for today', GTC: 'Good till cancelled' }
// When an unfilled limit order ends
const untilWords = (order) => (order.tif === 'GTC' ? 'stays open until you cancel it' : 'is cancelled at today’s close')

function orderWords(order, c) {
  const type = order.order_type === 'LMT' ? `Limit order at ${formatMoney(order.limit_price, c)}` : 'Market order'
  return `${type} · ${TIF_WORDS[order.tif] ?? TIF_WORDS.DAY}`
}

// The limit-order explanation in the callout (Figma "M6 / 3 Review order")
function calloutText(order, c) {
  if (order.order_type === 'MKT') {
    return 'A market order fills at the best price available when it reaches the exchange, which can differ from the price shown here.'
  }
  const price = formatMoney(order.limit_price, c)
  return order.action === 'BUY'
    ? `A limit order only fills at ${price} or lower. If the price stays above that, it won’t fill and ${untilWords(order)}.`
    : `A limit order only fills at ${price} or higher. If the price stays below that, it won’t fill and ${untilWords(order)}.`
}

// A change of order type may not be possible in place (IBKR refuses market -> limit, for example)
function replaceNote(preview) {
  if (!preview.modify_order_id || preview.order_type === preview.original_order_type) return null
  return 'If IBKR can’t change the order type in place, the order is cancelled and placed again as a new order.'
}

// What the result sheet says for an order's state
function resultText(order, c, accountLabel) {
  const verb = order.action === 'BUY' ? 'Bought' : 'Sold'
  const where = `in your ${accountLabel.toLowerCase()}`
  if (order.status === 'Filled') {
    return { title: 'Order filled', tone: 'ok', text: `${verb} ${order.filled} ${order.symbol} at an average of ${formatMoney(order.avg_fill_price, c)} ${where}.` }
  }
  if (FINAL.has(order.status)) {
    return { title: 'Order not filled', tone: 'bad', text: order.message ?? `IBKR ended the order (${order.status}).` }
  }
  if (order.filled > 0) {
    return { title: 'Order partly filled', tone: 'ok', text: `${verb} ${order.filled} of ${order.quantity} ${order.symbol} so far ${where}.` }
  }
  const lasts = order.tif === 'GTC' ? 'It stays open until it fills or you cancel it.' : 'It lasts until today’s close.'
  return { title: 'Order placed', tone: 'ok', text: `IBKR has the order and it will fill when the price allows. ${lasts}` }
}

// Review, then follow the placed order (Figma "M6 / 3 Review order" and "M6 / 4 Order filled")
function OrderConfirm({ preview, trading, onEdit, onDone, onViewOrders }) {
  const [placing, setPlacing] = useState(false)
  const [error, setError] = useState(null)
  const [order, setOrder] = useState(null)
  const [submittedAt, setSubmittedAt] = useState(null)
  // Set when IBKR refused the change in place and the order was cancelled and placed again
  const [replaced, setReplaced] = useState(null)
  // When the app first heard of the current number of filled shares
  const [fillSeen, setFillSeen] = useState(null)
  // Sending failed in a way that leaves it unclear whether IBKR has the order (#200): the error text
  const [unknown, setUnknown] = useState(null)
  // The live updates stopped before the order reached a final status (#200)
  const [updatesLost, setUpdatesLost] = useState(false)
  const c = preview.currency
  const accountLabel = trading?.account_label ?? 'Account'

  useEffect(() => {
    // Escape never goes back to the ticket once the order may have been sent
    const onKey = (e) => e.key === 'Escape' && !placing && (order || unknown ? onDone() : onEdit())
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [placing, order, unknown, onDone, onEdit])

  function update(next) {
    setOrder(next)
    if (next.filled > 0) setFillSeen((old) => (old?.filled === next.filled ? old : { filled: next.filled, time: timeNow() }))
  }

  // After placing, follow the order's updates until IB is done with it
  const orderId = order?.order_id
  const finished = order && FINAL.has(order.status)
  useEffect(() => {
    if (orderId == null || finished) return
    const controller = new AbortController()
    // The stream only ends on its own when it breaks (the backend stopped, the network dropped): the
    // sheet then says its status may be out of date. Closing the sheet aborts it, which isn't a loss.
    const lost = () => !controller.signal.aborted && setUpdatesLost(true)
    watchOrders((name, data) => {
      const updates = name === 'orders' ? data : [data]
      const mine = updates.filter((u) => u.order_id === orderId).at(-1)
      if (mine) {
        setUpdatesLost(false)
        update(mine)
      }
    }, controller.signal).then(lost, lost)
    return () => controller.abort()
  }, [orderId, finished])

  async function place() {
    setPlacing(true)
    setError(null)
    try {
      // A change to an open order keeps its id; otherwise this places a new order
      const placed = preview.modify_order_id
        ? await modifyOrder(preview.modify_order_id, {
            quantity: preview.quantity,
            limit_price: preview.limit_price,
            order_type: preview.order_type,
            tif: preview.tif,
            confirmation_token: preview.confirmation_token,
          })
        : await placeOrder({
            con_id: preview.con_id,
            action: preview.action,
            quantity: preview.quantity,
            order_type: preview.order_type,
            limit_price: preview.limit_price,
            tif: preview.tif,
            confirmation_token: preview.confirmation_token,
          })
      setSubmittedAt(timeNow())
      setReplaced(placed.replaced ?? null)
      update(placed)
    } catch (err) {
      // Never placed again automatically: the user checks Orders first
      if (outcomeUnknown(err)) setUnknown(err.message)
      else setError(err.message)
    } finally {
      setPlacing(false)
    }
  }

  if (unknown) {
    const change = Boolean(preview.modify_order_id)
    return (
      <div className="sheet-backdrop">
        <div className="sheet order-result" role="alertdialog" aria-modal="true" aria-labelledby="result-title" aria-describedby="result-text">
          <div className="result-icon bad">
            <WarningIcon size={30} />
          </div>
          <h2 id="result-title" className="result-title">
            {change ? 'We couldn’t confirm your change' : 'We couldn’t confirm your order'}
          </h2>
          <p id="result-text" className="result-text">
            {change
              ? 'The connection dropped while the change was being sent, so IBKR may have made it.'
              : 'The connection dropped while the order was being sent, so IBKR may have placed it.'}{' '}
            Check the Orders page before you try again.
          </p>
          <p className="sheet-note">{unknown}</p>
          <div className="sheet-footer">
            <button type="button" className="pill-button secondary" onClick={onDone}>
              Close
            </button>
            <div className="spacer" />
            {onViewOrders && (
              <button type="button" className="pill-button primary" onClick={onViewOrders} autoFocus>
                View Orders
              </button>
            )}
          </div>
        </div>
      </div>
    )
  }

  if (order) {
    const result = resultText(order, c, accountLabel)
    const timeline = replaced
      ? [
          { kind: 'cancelled', label: `Original order cancelled (IBKR couldn’t change it in place)`, time: submittedAt },
          { kind: 'submitted', label: 'New order submitted to IBKR', time: submittedAt },
        ]
      : [{ kind: 'submitted', label: preview.modify_order_id ? 'Change sent to IBKR' : 'Submitted to IBKR', time: submittedAt }]
    if (fillSeen) {
      timeline.push({ kind: 'fill', label: `Filled ${fillSeen.filled} of ${order.quantity} at ${formatMoney(order.avg_fill_price, c)}`, time: fillSeen.time })
    }
    const commission = order.commission_currency === c ? order.commission : null
    const totalCost =
      order.filled > 0 && order.avg_fill_price != null
        ? order.filled * order.avg_fill_price + (commission ?? 0) * (order.action === 'BUY' ? 1 : -1)
        : null
    return (
      <div className="sheet-backdrop">
        <div className="sheet order-result" role="dialog" aria-modal="true" aria-labelledby="result-title">
          <div className={`result-icon ${result.tone}`}>{result.tone === 'ok' ? <CheckIcon /> : <WarningIcon size={30} />}</div>
          <h2 id="result-title" className="result-title">
            {result.title}
          </h2>
          <p className="result-text">{result.text}</p>
          {updatesLost && !FINAL.has(order.status) && (
            <div className="callout error" role="status">
              <WarningIcon size={16} />
              <p>Live updates stopped, so this may not be the latest status. Check the Orders page for where the order is now.</p>
            </div>
          )}
          {replaced && (
            <div className="callout">
              <InfoIcon />
              <p>
                IBKR couldn’t make this change to the existing order ({replaced.reason}), so it was cancelled and placed
                again as a new order.
              </p>
            </div>
          )}
          <div className="estimates timeline">
            {timeline.map((e) => (
              <div key={e.kind} className="timeline-event">
                <CheckCircleIcon />
                <span>{e.label}</span>
                <span className="spacer" />
                <span className="timeline-time">{e.time}</span>
              </div>
            ))}
          </div>
          {totalCost != null && (
            <div className="estimates">
              <Line
                label={order.action === 'BUY' ? `Total cost${commission != null ? ' incl. commission' : ''}` : `Total proceeds${commission != null ? ' after commission' : ''}`}
                value={formatMoney(totalCost, c)}
                total
              />
            </div>
          )}
          <div className="sheet-footer">
            {onViewOrders && (
              <button type="button" className="pill-button secondary" onClick={onViewOrders}>
                View Orders
              </button>
            )}
            <div className="spacer" />
            <button type="button" className="pill-button primary" onClick={onDone} autoFocus>
              Done
            </button>
          </div>
        </div>
      </div>
    )
  }

  const buying = preview.action === 'BUY'
  const commission = preview.what_if?.commission
  const commissionSame = preview.what_if?.commission_currency === c
  const total =
    preview.estimated_value != null && commission != null && commissionSame
      ? preview.estimated_value + (buying ? commission : -commission)
      : preview.estimated_value
  return (
    <div className="sheet-backdrop">
      <div className="sheet" role="dialog" aria-modal="true" aria-labelledby="review-title">
        <div className="sheet-title-row">
          <h2 id="review-title" className="sheet-title">
            Review order
          </h2>
          <div className="spacer" />
          {trading && trading.account !== 'unknown' && (
            <span className={`badge badge-account ${trading.account}`}>
              <span className="badge-dot" /> {accountLabel}
            </span>
          )}
        </div>

        <div className="review-summary">
          <p className="review-headline">
            {preview.modify_order_id ? (
              <>
                Change to <span className={`order-side ${buying ? 'buy' : 'sell'}`}>{buying ? 'Buy' : 'Sell'}</span>
              </>
            ) : buying ? (
              'Buy'
            ) : (
              'Sell'
            )}{' '}
            {preview.quantity} {preview.symbol}
          </p>
          <p className="review-words">{orderWords(preview, c)}</p>
        </div>

        {preview.borrow && !preview.borrow.blocked && (
          <p className="borrow-warning" role="alert">
            <strong>This order borrows from IBKR.</strong> {preview.borrow.message}
          </p>
        )}

        <div className="estimates">
          <Line label={buying ? 'Estimated cost' : 'Estimated proceeds'} value={formatMoney(preview.estimated_value, c)} />
          <Line
            label="Commission (est.)"
            value={commission != null ? formatMoney(commission, preview.what_if.commission_currency) : '—'}
          />
          <Line label="Account" value={accountLabel} />
          <Line label="Estimated total" value={formatMoney(total, c)} total />
        </div>

        <div className={`callout ${error ? 'error' : ''}`} role={error ? 'alert' : undefined}>
          {error ? <WarningIcon size={16} /> : <InfoIcon />}
          <p>{error ?? [calloutText(preview, c), replaceNote(preview)].filter(Boolean).join(' ')}</p>
        </div>

        {preview.what_if?.warning && <p className="sheet-note">IBKR: {preview.what_if.warning}</p>}

        <div className="sheet-footer">
          <button type="button" className="pill-button secondary" onClick={onEdit} disabled={placing}>
            Edit
          </button>
          <div className="spacer" />
          <button type="button" className="pill-button primary" onClick={place} disabled={placing || Boolean(error)}>
            {placing ? 'Sending…' : preview.modify_order_id ? 'Change Order' : `Place ${buying ? 'Buy' : 'Sell'} Order`}
          </button>
        </div>
      </div>
    </div>
  )
}

export default OrderConfirm
