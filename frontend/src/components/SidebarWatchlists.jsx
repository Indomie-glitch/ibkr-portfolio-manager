import { useCallback, useEffect, useRef, useState } from 'react'
import {
  MAX_NAME,
  createWatchlist,
  deleteWatchlist,
  finishNaming,
  startNaming,
  useNamingWatchlist,
  useWatchlists,
} from '../lib/watchlists.js'
import { PlusIcon, StarIcon } from './icons.jsx'
import PopupMenu from './PopupMenu.jsx'

// The name field of a new (or renamed) watchlist, with the name selected (Figma M6 / 7 node 42:676).
// Return or a click elsewhere keeps the name; Escape keeps the old one.
function NameField({ list }) {
  const ref = useRef(null)
  const [value, setValue] = useState(list.name)
  const done = useRef(false)

  useEffect(() => {
    ref.current?.focus()
    ref.current?.select()
  }, [])

  function finish(name) {
    if (done.current) return
    done.current = true
    finishNaming(list.id, name)
  }

  return (
    <div className="sidebar-item naming">
      <StarIcon />
      <input
        ref={ref}
        className="rename-field"
        value={value}
        maxLength={MAX_NAME}
        aria-label="Watchlist name"
        onChange={(e) => setValue(e.target.value)}
        onBlur={() => finish(value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') finish(value)
          if (e.key === 'Escape') finish(list.name)
        }}
      />
    </div>
  )
}

// Watchlists in the sidebar (#88; Figma "Section Header / Watchlists" node 36:300 and M6 / 6):
// a + button to make one, and a row per watchlist with how many stocks it has
function SidebarWatchlists({ activeId, onOpen, onDeleted }) {
  const lists = useWatchlists()
  const naming = useNamingWatchlist()
  // Right-click menu: { id, x, y } or null
  const [menu, setMenu] = useState(null)
  const closeMenu = useCallback(() => setMenu(null), [])

  function add() {
    onOpen(createWatchlist())
  }

  const menuList = menu && lists.find((l) => l.id === menu.id)

  return (
    <>
      <div className="sidebar-section with-action">
        <span>Watchlists</span>
        <button type="button" className="sidebar-add" aria-label="New watchlist" title="New watchlist" onClick={add}>
          <PlusIcon />
        </button>
      </div>
      {/* Scrolls on its own when there are more watchlists than fit */}
      <div className="sidebar-lists">
        {lists.map((l) =>
          l.id === naming ? (
            <NameField key={l.id} list={l} />
          ) : (
            <button
              key={l.id}
              type="button"
              className={`sidebar-item ${activeId === l.id ? 'active' : ''}`}
              aria-current={activeId === l.id ? 'page' : undefined}
              onClick={() => onOpen(l.id)}
              onContextMenu={(e) => {
                e.preventDefault()
                setMenu({ id: l.id, x: e.clientX, y: e.clientY })
              }}
            >
              <StarIcon />
              <span className="sidebar-item-name">{l.name}</span>
              <span className="sidebar-count">{l.stocks.length}</span>
            </button>
          ),
        )}
      </div>
      {menuList && (
        <PopupMenu
          label={`${menuList.name} options`}
          items={[
            { label: 'Rename', onSelect: () => startNaming(menuList.id) },
            {
              label: 'Delete Watchlist',
              onSelect: () => {
                deleteWatchlist(menuList.id)
                onDeleted(menuList.id)
              },
            },
          ]}
          onClose={closeMenu}
          className="context-menu"
          style={{ left: menu.x, top: menu.y }}
        />
      )}
    </>
  )
}

export default SidebarWatchlists
