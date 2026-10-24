import { useState } from 'react'
import { createPortal } from 'react-dom'
import { CAN_CONFIRM_OWNER } from '../desktop/appBorrowing.js'

// The sheets for "Block borrowing" in Settings (#289). Rendered on <body> so they sit above the
// Settings sheet. Turning blocking off explains borrowing first; Cancel is the default button.
function SheetFrame({ title, children, onCancel }) {
  return createPortal(
    <div
      className="sheet-backdrop borrow-backdrop"
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.stopPropagation()
          onCancel()
        }
      }}
    >
      <div className="sheet" role="alertdialog" aria-modal="true" aria-labelledby="borrow-sheet-title">
        <h2 id="borrow-sheet-title" className="sheet-title">
          {title}
        </h2>
        {children}
      </div>
    </div>,
    document.body,
  )
}

export function AllowBorrowingSheet({ onCancel, onConfirm, busy, error }) {
  // The browser version has no Touch ID, so BORROW is typed instead
  const [typed, setTyped] = useState('')
  const ready = CAN_CONFIRM_OWNER || typed.trim() === 'BORROW'
  return (
    <SheetFrame title="Allow orders to borrow?" onCancel={onCancel}>
      <div className="borrow-explainer">
        <p>With Block borrowing off, an order can cost more than the cash you have in its currency.</p>
        <ul>
          <li>IBKR lends you the difference. That includes buying a US stock with no US dollars: IBKR doesn’t convert your money, it lends you the dollars.</li>
          <li>Interest is charged on the loan every day until it’s paid back.</li>
          <li>You can lose more than the money you put in.</li>
          <li>If the loan gets too big compared with your account, IBKR can sell your holdings without asking.</li>
        </ul>
        <p>Orders that borrow will still show how much before you place them.</p>
      </div>
      {!CAN_CONFIRM_OWNER && (
        <label className="form-row borrow-type">
          <span>Type BORROW to confirm</span>
          <input
            className="settings-field"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            autoComplete="off"
            spellCheck="false"
            aria-label="Type BORROW to confirm"
          />
        </label>
      )}
      {error && <p className="error-text">{error}</p>}
      <div className="sheet-footer">
        <div className="spacer" />
        <button type="button" className="pill-button secondary danger-text" onClick={onConfirm} disabled={!ready || busy}>
          {busy && CAN_CONFIRM_OWNER ? 'Waiting for Touch ID…' : 'Allow borrowing'}
        </button>
        {/* Cancel is the default: focused, and the primary style */}
        {/* oxlint-disable-next-line jsx-a11y/no-autofocus */}
        <button type="button" className="pill-button primary" onClick={onCancel} autoFocus>
          Cancel
        </button>
      </div>
      {CAN_CONFIRM_OWNER && <p className="sheet-note">Next, macOS asks for Touch ID or your Mac password. Nothing is stored.</p>}
    </SheetFrame>
  )
}

export function BlockBorrowingSheet({ onCancel, onConfirm, busy, error }) {
  return (
    <SheetFrame title="Block borrowing again?" onCancel={onCancel}>
      <p className="borrow-explainer">Orders that would borrow from IBKR will be blocked again for this account.</p>
      {error && <p className="error-text">{error}</p>}
      <div className="sheet-footer">
        <div className="spacer" />
        <button type="button" className="pill-button secondary" onClick={onCancel}>
          Cancel
        </button>
        {/* oxlint-disable-next-line jsx-a11y/no-autofocus */}
        <button type="button" className="pill-button primary" onClick={onConfirm} disabled={busy} autoFocus>
          Block borrowing
        </button>
      </div>
    </SheetFrame>
  )
}
