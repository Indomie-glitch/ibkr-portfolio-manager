import { useCallback, useState } from 'react'
import { addToWatchlist, createWatchlist, removeFromWatchlist, useWatchlists } from '../lib/watchlists.js'
import { PlusIcon, StarIcon } from './icons.jsx'
import PopupMenu from './PopupMenu.jsx'

// "Watch" / "In 2 watchlists" in a stock's header, with the menu that adds it to watchlists or
// takes it out (#88, Figma M6 / 9 node 42:1091). A tick marks the watchlists it's already in.
function WatchButton({ stock }) {
  const lists = useWatchlists()
  const [open, setOpen] = useState(false)
  const close = useCallback(() => setOpen(false), [])
  const inLists = lists.filter((l) => l.stocks.some((s) => s.con_id === stock.con_id))
  const label = inLists.length === 0 ? 'Watch' : `In ${inLists.length} watchlist${inLists.length === 1 ? '' : 's'}`

  const items = lists.map((l) => {
    const checked = inLists.includes(l)
    return {
      label: l.name,
      count: l.stocks.length,
      checked,
      onSelect: () => (checked ? removeFromWatchlist(l.id, stock.con_id) : addToWatchlist(l.id, stock)),
    }
  })
  if (items.length) items.push('separator')
  items.push({ label: 'New Watchlist…', icon: <PlusIcon />, onSelect: () => createWatchlist(stock) })

  return (
    <div className="watch-button-wrap">
      <button
        type="button"
        className={`pill-button secondary watch-button ${open ? 'open' : ''}`}
        aria-haspopup="menu"
        aria-expanded={open}
        // The menu closes itself on a click outside it, which includes this button
        onMouseDown={(e) => open && e.stopPropagation()}
        onClick={() => setOpen(!open)}
      >
        <StarIcon size={14} />
        {label}
      </button>
      {open && <PopupMenu label={`Add ${stock.symbol} to a watchlist`} header={`Add ${stock.symbol} to`} items={items} onClose={close} className="watch-menu" />}
    </div>
  )
}

export default WatchButton
