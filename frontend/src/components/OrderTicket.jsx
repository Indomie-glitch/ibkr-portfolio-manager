import { useEffect, useRef, useState } from 'react'
import { previewOrder } from '../lib/api.js'
import { formatMoney, prefixFor } from '../lib/format.js'
import { amountPrice, commissionText, estimates, orderFrom, parseMoney, sharesForAmount, stepShares, switchOrderBy } from '../lib/orderTicket.js'
import { ChevronsIcon, StepDownIcon, StepUpIcon } from './icons.jsx'

// Ask IBKR for a new estimate once typing pauses
const PREVIEW_DELAY_MS = 500

function Line({ label, value, total = false }) {
  return (
    <div className={`estimate-line ${total ? 'total' : ''}`}>
      <span>{label}</span>
      <span className="num">{value}</span>
    </div>
  )
}

// The order ticket sheet (Figma "M6 / 2 Order ticket"). Nothing is sent from here: Review Order
// hands the preview (with its confirmation token) to the confirmation sheet.
// existing: an open order being changed (side and type stay; quantity and limit price can change)
function OrderTicket({ stock, side, existing = null, trading, account, onClose, onReview, hidden = false, previewNonce = 0 }) {
  const [form, setForm] = useState(() =>
    existing
      ? {
          side: existing.action,
          orderType: existing.order_type,
          quantity: String(existing.quantity),
          limitPrice: existing.limit_price != null ? existing.limit_price.toFixed(2) : '',
          tif: existing.tif === 'GTC' ? 'GTC' : 'DAY',
        }
      : {
          side,
          orderType: 'LMT',
          // Order by a number of shares, or by an amount of money (new orders only)
          by: 'shares',
          quantity: '1',
          amount: '',
          limitPrice: stock.last != null ? stock.last.toFixed(2) : '',
          tif: 'DAY',
        },
  )
  // The preview belongs to `key`, so an old estimate never shows for changed numbers
  const [preview, setPreview] = useState({ key: null, data: null, error: null })
  const quantityRef = useRef(null)

  // The maths lives in lib/orderTicket.js (tested there); inputProblems: what's wrong with what was typed
  const { order, problems: inputProblems } = orderFrom(stock, form)
  const key = order ? JSON.stringify(order) : null

  useEffect(() => {
    if (hidden) return
    quantityRef.current?.focus()
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, hidden])

  useEffect(() => {
    if (!key || hidden) return
    let ignore = false
    const timer = setTimeout(() => {
      previewOrder(JSON.parse(key))
        .then((data) => !ignore && setPreview({ key, nonce: previewNonce, data, error: null }))
        .catch((err) => !ignore && setPreview({ key, nonce: previewNonce, data: null, error: err.message }))
    }, PREVIEW_DELAY_MS)
    return () => {
      ignore = true
      clearTimeout(timer)
    }
    // previewNonce: back from the review sheet, its token may be used up, so ask again
  }, [key, hidden, previewNonce])

  const set = (field) => (value) => setForm((old) => ({ ...old, [field]: value }))
  function step(by) {
    set('quantity')(stepShares(form.quantity, by))
  }

  // Switching keeps the order about the same size: shares × price becomes the amount, and back
  function orderBy(by) {
    setForm((old) => switchOrderBy(old, by, stock.last))
  }

  const byAmount = form.by === 'amount'
  const unitPrice = amountPrice(stock.last, form)
  const amountShares = byAmount ? sharesForAmount(parseMoney(form.amount).value, unitPrice) : null

  const current = preview.key === key && preview.nonce === previewNonce ? preview : { data: null, error: null }
  const data = current.data
  const c = stock.currency
  const buying = form.side === 'BUY'
  const { total, buyingPowerAfter } = estimates(data, { side: form.side, currency: c, buyingPower: account?.buying_power })
  // A problem with the amount already shows in the note under it
  const amountProblem = byAmount ? parseMoney(form.amount).problem : null
  const problems = [...inputProblems.filter((p) => p !== amountProblem), ...(data?.problems ?? [])]
  const canReview = Boolean(data?.can_submit && data.confirmation_token && onReview)

  return (
    <div className="sheet-backdrop" hidden={hidden} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="sheet order-ticket" role="dialog" aria-modal="true" aria-labelledby="ticket-title">
        <div className="sheet-title-row">
          <h2 id="ticket-title" className="sheet-title">
            {existing ? (
              <>
                {/* A change can't switch sides, so the side is shown in colour instead of a selector (#165) */}
                Change order: <span className={`order-side ${buying ? 'buy' : 'sell'}`}>{buying ? 'Buy' : 'Sell'}</span>
              </>
            ) : buying ? (
              'Buy'
            ) : (
              'Sell'
            )}{' '}
            {stock.shortName ?? stock.symbol}
          </h2>
          <div className="spacer" />
          {trading && trading.account !== 'unknown' && (
            <span className={`badge badge-account ${trading.account}`}>
              <span className="badge-dot" /> {trading.account_label}
            </span>
          )}
        </div>

        {/* A change keeps the order's side (the title says it), so only new orders get the selector */}
        {!existing && (
          <div className="segmented sheet-side" role="group" aria-label="Buy or sell">
            {[
              ['BUY', 'Buy'],
              ['SELL', 'Sell'],
            ].map(([value, label]) => (
              <button key={value} type="button" aria-pressed={form.side === value} onClick={() => set('side')(value)}>
                {label}
              </button>
            ))}
          </div>
        )}

        <div className="form-rows">
          <label className="form-row">
            <span>Order type</span>
            <span className="popup-button">
              <select value={form.orderType} onChange={(e) => set('orderType')(e.target.value)}>
                <option value="LMT">Limit</option>
                <option value="MKT">Market</option>
              </select>
              <ChevronsIcon />
            </span>
          </label>

          <div className="form-row wrap">
            <label htmlFor={byAmount ? 'ticket-amount' : 'ticket-quantity'}>{byAmount ? 'Amount' : 'Quantity'}</label>
            <div className="quantity-controls">
              {/* Shares or an amount of money: new orders only (a change edits the shares) */}
              {!existing && (
                <div className="segmented order-by" role="group" aria-label="Order by">
                  {[
                    ['shares', 'Shares'],
                    ['amount', 'Amount'],
                  ].map(([value, label]) => (
                    <button key={value} type="button" aria-pressed={form.by === value} onClick={() => orderBy(value)}>
                      {label}
                    </button>
                  ))}
                </div>
              )}
              {byAmount ? (
                <span className="form-field price-field amount-field">
                  <span className="price-prefix">{prefixFor(c).trim()}</span>
                  <input
                    id="ticket-amount"
                    className="num"
                    inputMode="decimal"
                    value={form.amount}
                    aria-label="Amount"
                    onChange={(e) => set('amount')(e.target.value)}
                  />
                </span>
              ) : (
                <div className="quantity-stepper">
                  <input
                    id="ticket-quantity"
                    ref={quantityRef}
                    className="form-field num"
                    inputMode="numeric"
                    value={form.quantity}
                    aria-label="Quantity"
                    onChange={(e) => set('quantity')(e.target.value)}
                  />
                  <div className="stepper">
                    <button type="button" aria-label="One more share" onClick={() => step(1)}>
                      <StepUpIcon />
                    </button>
                    <button type="button" aria-label="One less share" onClick={() => step(-1)}>
                      <StepDownIcon />
                    </button>
                  </div>
                </div>
              )}
            </div>
            {byAmount && (
              <p className="form-row-note" aria-live="polite">
                {!unitPrice
                  ? form.orderType === 'LMT'
                    ? 'Enter a limit price to work out the shares.'
                    : 'No current price to work out the shares. Use Shares, or a limit order.'
                  : amountShares === null
                    ? parseMoney(form.amount).problem ?? 'Enter an amount.'
                    : amountShares === 0
                      ? `Less than one share at ${formatMoney(unitPrice, c)}.`
                      : `= ${amountShares} ${amountShares === 1 ? 'share' : 'shares'} at ${formatMoney(unitPrice, c)} ${
                          form.orderType === 'MKT' ? '(latest price; the final cost can differ)' : '(limit price)'
                        }`}
              </p>
            )}
          </div>

          {form.orderType === 'LMT' && (
            <label className="form-row">
              <span>Limit price</span>
              <span className="form-field price-field">
                <span className="price-prefix">{prefixFor(c).trim()}</span>
                <input
                  className="num"
                  inputMode="decimal"
                  value={form.limitPrice}
                  onChange={(e) => set('limitPrice')(e.target.value)}
                  aria-label="Limit price"
                />
              </span>
            </label>
          )}

          <label className="form-row">
            <span>Time in force</span>
            <span className="popup-button">
              <select value={form.tif} onChange={(e) => set('tif')(e.target.value)} aria-label="Time in force">
                <option value="DAY">Day</option>
                <option value="GTC">Good till cancelled</option>
              </select>
              <ChevronsIcon />
            </span>
          </label>
        </div>

        <div className="estimates" aria-live="polite">
          <Line label={buying ? 'Estimated cost' : 'Estimated proceeds'} value={formatMoney(data?.estimated_value, c)} />
          <Line label="Commission (est.)" value={commissionText(data?.what_if)} />
          <Line label="Buying power after (est.)" value={formatMoney(buyingPowerAfter, account?.currency)} />
          <Line label="Total (est.)" value={formatMoney(total, c)} total />
        </div>

        {(problems.length > 0 || current.error) && (
          <ul className="ticket-problems">
            {current.error && <li>{current.error}</li>}
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        )}

        <p className="sheet-note">
          Estimates come from IBKR’s order preview. Nothing is sent until you review and confirm.
        </p>

        <div className="sheet-footer">
          <button type="button" className="pill-button secondary" onClick={onClose}>
            Cancel
          </button>
          <div className="spacer" />
          <button
            type="button"
            className="pill-button primary"
            disabled={!canReview}
            onClick={() =>
              onReview(existing ? { ...data, modify_order_id: existing.order_id, original_order_type: existing.order_type } : data)
            }
            title={onReview ? undefined : 'The confirmation sheet arrives with issue #31'}
          >
            Review Order
          </button>
        </div>
      </div>
    </div>
  )
}

export default OrderTicket
