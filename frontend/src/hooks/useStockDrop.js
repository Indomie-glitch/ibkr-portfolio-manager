import { useRef, useState } from 'react'
import { droppedStock, isStockDrag } from '../lib/watchlists.js'

// A place stock rows can be dropped on (a watchlist in the sidebar).
// Returns whether a stock is being dragged over it (to highlight it) and the props to spread on it.
export function useStockDrop(onDrop) {
  const [over, setOver] = useState(false)
  // dragenter/dragleave also fire for the element's children, so count them
  const depth = useRef(0)

  const props = {
    onDragEnter: (e) => {
      if (!isStockDrag(e)) return
      e.preventDefault()
      depth.current += 1
      setOver(true)
    },
    onDragOver: (e) => {
      if (!isStockDrag(e)) return
      // Allowing the drop: without this the browser refuses it
      e.preventDefault()
      e.dataTransfer.dropEffect = 'copy'
    },
    onDragLeave: (e) => {
      if (!isStockDrag(e)) return
      depth.current = Math.max(0, depth.current - 1)
      if (depth.current === 0) setOver(false)
    },
    onDrop: (e) => {
      depth.current = 0
      setOver(false)
      const stock = droppedStock(e)
      if (!stock) return
      e.preventDefault()
      onDrop(stock)
    },
  }
  return [over, props]
}
