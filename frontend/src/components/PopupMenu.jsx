import { useEffect, useRef } from 'react'
import { useClickOutside, useMenuKeys } from '../hooks/useMenu.js'
import { MenuCheckIcon } from './icons.jsx'

// A macOS-style menu for the Watch button and right-click menus (#88; same look as the account
// menu, Figma M6 / 9 node 42:1091). It's placed by its parent (className / style) and takes focus so
// the keyboard works: arrows move, Return chooses, Escape or a click outside closes.
// items: { label, onSelect, checked?, icon?, count?, disabled? } or 'separator'.
function PopupMenu({ label, header, items, onClose, className = '', style }) {
  const ref = useRef(null)
  const { active, setActive, moveKey } = useMenuKeys(items, choose)
  // Leave room for the tick when any item can have one, so the names line up
  const checkSlot = items.some((item) => item !== 'separator' && ('checked' in item || item.icon))

  useEffect(() => {
    ref.current?.focus()
  }, [])
  useClickOutside(ref, onClose)

  function choose(item) {
    onClose()
    item.onSelect()
  }

  function onKeyDown(e) {
    if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      onClose()
    } else {
      moveKey(e)
    }
  }

  return (
    <div ref={ref} className={`popup-menu ${className}`} style={style} role="menu" aria-label={label} tabIndex={-1} onKeyDown={onKeyDown}>
      {header && <div className={`popup-menu-header ${checkSlot ? 'indented' : ''}`}>{header}</div>}
      {items.map((item, i) =>
        item === 'separator' ? (
          <div key={`sep-${i}`} className="account-menu-separator" role="separator" />
        ) : (
          <button
            key={`${i}-${item.label}`}
            type="button"
            role={'checked' in item ? 'menuitemcheckbox' : 'menuitem'}
            aria-checked={'checked' in item ? item.checked : undefined}
            className={`popup-menu-item ${active === i ? 'active' : ''}`}
            disabled={item.disabled}
            onMouseEnter={() => !item.disabled && setActive(i)}
            onMouseLeave={() => setActive(-1)}
            onClick={() => choose(item)}
          >
            {checkSlot && <span className="popup-menu-check">{item.icon ?? (item.checked && <MenuCheckIcon />)}</span>}
            <span className="popup-menu-label">{item.label}</span>
            {item.count != null && <span className="popup-menu-count">{item.count}</span>}
          </button>
        ),
      )}
    </div>
  )
}

export default PopupMenu
