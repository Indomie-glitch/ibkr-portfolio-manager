import { useCallback, useRef, useState } from 'react'
import { useClickOutside, useMenuKeys } from '../hooks/useMenu.js'
import { GearIcon } from './icons.jsx'

// "JS" for jsmith_app: the first two letters of the name
const initials = (name) => (name.replace(/[^a-z0-9]/gi, '').slice(0, 2) || '?').toUpperCase()

// The account card at the bottom of the sidebar and its menu (Figma "Overview / Light / Account
// menu", node 44:904). items: [{ label, shortcut?, disabled?, onSelect }] or 'separator'.
function AccountCard({ name, status, dot, menuTitle, menuStatus, items }) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef(null)
  const buttonRef = useRef(null)
  const { active, setActive, choices, moveKey } = useMenuKeys(items, choose)
  useClickOutside(rootRef, useCallback(() => setOpen(false), []), open)

  function close() {
    setOpen(false)
    buttonRef.current?.focus()
  }

  function choose(item) {
    setOpen(false)
    // Back to the card first, so a sheet opened from the menu returns focus here when it closes
    buttonRef.current?.focus()
    item.onSelect()
  }

  // Like a macOS menu: arrows move, Return chooses, Escape closes
  function onKeyDown(e) {
    if (!open) {
      if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
        e.preventDefault()
        setOpen(true)
        setActive(choices[0] ?? -1)
      }
      return
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      close()
    } else {
      moveKey(e)
    }
  }

  return (
    <div className="account" ref={rootRef} onKeyDown={onKeyDown}>
      {open && (
        <div className="account-menu" role="menu" aria-label="Account">
          <div className="account-menu-header">
            <span className="account-menu-title">{menuTitle}</span>
            <span className="account-menu-status">{menuStatus}</span>
          </div>
          <div className="account-menu-separator" role="separator" />
          {items.map((item, i) =>
            item === 'separator' ? (
              <div key={`sep-${i}`} className="account-menu-separator" role="separator" />
            ) : (
              <button
                key={item.label}
                type="button"
                role="menuitem"
                className={`account-menu-item ${active === i ? 'active' : ''}`}
                disabled={item.disabled}
                title={item.disabledReason}
                onMouseEnter={() => !item.disabled && setActive(i)}
                onMouseLeave={() => setActive(-1)}
                onClick={() => choose(item)}
              >
                <span>{item.label}</span>
                {item.shortcut && <span className="account-menu-shortcut">{item.shortcut}</span>}
              </button>
            ),
          )}
        </div>
      )}
      <button
        ref={buttonRef}
        type="button"
        className="account-card"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => {
          setOpen((o) => !o)
          setActive(-1)
        }}
      >
        <span className="account-avatar" aria-hidden="true">
          {initials(name)}
          <span className={`account-avatar-dot ${dot}`} />
        </span>
        <span className="account-text">
          <span className="account-name">{name}</span>
          <span className="account-status">{status}</span>
        </span>
        <span className="account-gear" aria-hidden="true">
          <GearIcon />
        </span>
      </button>
    </div>
  )
}

export default AccountCard
