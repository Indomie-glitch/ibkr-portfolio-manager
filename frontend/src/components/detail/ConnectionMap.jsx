import { useEffect, useRef, useState } from 'react'
import { HEIGHT, WIDTH } from '../../lib/connections.js'

const MIN_ZOOM = 1
const MAX_ZOOM = 3

// Keeps the view inside the drawing at this zoom
function bounded(view) {
  const zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, view.zoom))
  const x = Math.min(0, Math.max(WIDTH - WIDTH * zoom, view.x))
  const y = Math.min(0, Math.max(HEIGHT - HEIGHT * zoom, view.y))
  return { zoom, x, y }
}

function Node({ node, hovered, selected, onHover, onOpen, onSelect }) {
  const openable = Boolean(node.open || node.link)
  // In select mode (the full page) a click selects any node and a double click opens it; otherwise a click opens it
  const clickable = onSelect ? true : openable
  const activate = () => (onSelect ? onSelect(node) : onOpen(node))
  const common = {
    className: `con-node con-${node.kind} ${node.mine ? 'mine' : ''} ${hovered ? 'hovered' : ''} ${selected ? 'selected' : ''} ${clickable ? 'clickable' : ''}`,
    onMouseEnter: () => onHover(node.id),
    onMouseLeave: () => onHover(null),
    onFocus: () => onHover(node.id),
    onBlur: () => onHover(null),
    onClick: clickable ? activate : undefined,
    onDoubleClick: onSelect && openable ? () => onOpen(node) : undefined,
    onKeyDown: clickable ? (e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), activate()) : undefined,
    tabIndex: 0,
    role: clickable ? 'button' : 'img',
    'aria-label': `${node.tooltip.title}. ${node.tooltip.body ?? ''}`,
  }

  if (node.kind === 'index' || node.kind === 'holding') {
    return (
      <g {...common}>
        <rect x={node.x - node.w / 2} y={node.y - node.h / 2} width={node.w} height={node.h} rx="4" />
        <text x={node.x} y={node.y} dominantBaseline="central" textAnchor="middle">
          {node.label}
        </text>
      </g>
    )
  }
  if (node.kind === 'self') {
    return (
      <g {...common}>
        <circle cx={node.x} cy={node.y} r={node.r} />
        <text className="con-self-symbol" x={node.x} y={node.y} dominantBaseline="central" textAnchor="middle">
          {node.label}
        </text>
        <text className="con-self-name" x={node.x} y={node.y + node.r + 14} textAnchor="middle">
          {node.sublabel}
        </text>
      </g>
    )
  }
  return (
    <g {...common}>
      <circle cx={node.x} cy={node.y} r={node.r} />
      <text
        className={node.labelOutside ? 'outside' : ''}
        x={node.labelOutside ? node.x + node.r + 4 : node.x}
        y={node.y}
        dominantBaseline="central"
        textAnchor={node.labelOutside ? 'start' : 'middle'}
      >
        {node.label}
      </text>
    </g>
  )
}

// The dashed ring round the selected node
function SelectionRing({ node }) {
  if (node.w) {
    return <rect className="con-ring" x={node.x - node.w / 2 - 5} y={node.y - node.h / 2 - 5} width={node.w + 10} height={node.h + 10} rx="9" />
  }
  return <circle className="con-ring" cx={node.x} cy={node.y} r={(node.r ?? 16) + 8} />
}

function Tooltip({ node, view, size }) {
  // The node's position on screen: drawing units -> zoom and pan -> the map's size in pixels
  const scale = size.width / WIDTH
  const x = (node.x * view.zoom + view.x) * scale
  const y = (node.y * view.zoom + view.y) * scale
  const width = 250
  const left = Math.max(8, Math.min(x - width / 2, size.width - width - 8))
  const below = y < size.height / 2
  const style = below ? { left, top: y + 28 } : { left, bottom: size.height - y + 28 }
  return (
    <div className="con-tooltip" role="tooltip" style={{ ...style, width }}>
      <p className="con-tooltip-title">{node.tooltip.title}</p>
      {node.tooltip.body && <p className="con-tooltip-body">{node.tooltip.body}</p>}
      {node.tooltip.forYou && (
        <>
          <p className="con-tooltip-label">For you</p>
          <p className="con-tooltip-body">{node.tooltip.forYou}</p>
        </>
      )}
    </div>
  )
}

// The relationship map: an SVG drawing that scales to the panel, with scroll to zoom (around the
// pointer), drag to pan and double-click on empty space to reset. children: overlays (the competitors'
// scope keys). onSelect + selectedId: the full page's select mode (click selects, double click opens);
// zoomButtons adds the + and − control.
export default function ConnectionMap({ shown, onOpen, onSelect, selectedId = null, zoomButtons = false, children }) {
  const boxRef = useRef(null)
  const [view, setView] = useState({ zoom: 1, x: 0, y: 0 })
  const [hovered, setHovered] = useState(null)
  const [size, setSize] = useState({ width: WIDTH, height: HEIGHT })
  const drag = useRef(null)

  useEffect(() => {
    const box = boxRef.current
    const observer = new ResizeObserver(([entry]) =>
      setSize({ width: entry.contentRect.width, height: entry.contentRect.height }))
    observer.observe(box)
    // Scrolling zooms instead of scrolling the page, so the listener can't be passive
    function wheel(event) {
      event.preventDefault()
      const rect = box.getBoundingClientRect()
      const px = ((event.clientX - rect.left) / rect.width) * WIDTH
      const py = ((event.clientY - rect.top) / rect.height) * HEIGHT
      setView((v) => {
        const zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, v.zoom * Math.exp(-event.deltaY * 0.002)))
        // Keep the drawing point under the pointer where it is
        const dx = (px - v.x) / v.zoom
        const dy = (py - v.y) / v.zoom
        return bounded({ zoom, x: px - dx * zoom, y: py - dy * zoom })
      })
    }
    box.addEventListener('wheel', wheel, { passive: false })
    return () => {
      observer.disconnect()
      box.removeEventListener('wheel', wheel)
    }
  }, [])

  function pointerDown(event) {
    if (event.target.closest('.con-node') || view.zoom === 1) return
    drag.current = { x: event.clientX, y: event.clientY, view }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  function pointerMove(event) {
    if (!drag.current) return
    const scale = WIDTH / size.width
    const start = drag.current
    setView(bounded({ ...start.view, x: start.view.x + (event.clientX - start.x) * scale, y: start.view.y + (event.clientY - start.y) * scale }))
  }

  function zoomBy(factor) {
    // Around the middle of what's showing
    setView((v) => {
      const zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, v.zoom * factor))
      const dx = (WIDTH / 2 - v.x) / v.zoom
      const dy = (HEIGHT / 2 - v.y) / v.zoom
      return bounded({ zoom, x: WIDTH / 2 - dx * zoom, y: HEIGHT / 2 - dy * zoom })
    })
  }

  const nodeById = new Map(shown.nodes.map((n) => [n.id, n]))
  const hoveredNode = hovered ? nodeById.get(hovered) : null
  const selectedNode = selectedId ? nodeById.get(selectedId) : null

  return (
    <div
      ref={boxRef}
      className={`con-map ${view.zoom > 1 ? 'zoomed' : ''}`}
      onPointerDown={pointerDown}
      onPointerMove={pointerMove}
      onPointerUp={() => (drag.current = null)}
      onDoubleClick={(event) => !event.target.closest('.con-node') && setView({ zoom: 1, x: 0, y: 0 })}
    >
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="group" aria-label="Connections map">
        <g transform={`translate(${view.x} ${view.y}) scale(${view.zoom})`}>
          {shown.edges.map((e) => {
            const a = nodeById.get(e.from)
            const b = nodeById.get(e.to)
            const lit = hovered && (e.from === hovered || e.to === hovered)
            return (
              <line key={`${e.from}-${e.to}`} className={`con-edge ${e.mine ? 'mine' : ''} ${lit ? 'lit' : ''}`}
                x1={a.x} y1={a.y} x2={b.x} y2={b.y} />
            )
          })}
          {shown.labels.map((l) => (
            <text key={l.text} className={`con-group-label ${l.mine ? 'mine' : ''} ${l.note ? 'note' : ''}`} x={l.x} y={l.y}>
              {l.text}
            </text>
          ))}
          {selectedNode && <SelectionRing node={selectedNode} />}
          {shown.nodes.map((n) => (
            <Node key={n.id} node={n} hovered={hovered === n.id} selected={selectedId === n.id} onHover={setHovered}
              onOpen={onOpen} onSelect={onSelect} />
          ))}
        </g>
      </svg>
      {children}
      {zoomButtons && (
        <div className="con-zoom" role="group" aria-label="Zoom">
          <button type="button" aria-label="Zoom in" onClick={() => zoomBy(1.4)} disabled={view.zoom >= MAX_ZOOM}>
            +
          </button>
          <button type="button" aria-label="Zoom out" onClick={() => zoomBy(1 / 1.4)} disabled={view.zoom <= MIN_ZOOM}>
            −
          </button>
        </div>
      )}
      {hoveredNode && <Tooltip node={hoveredNode} view={view} size={size} />}
    </div>
  )
}
