// Text size steps. The whole page is zoomed (the CSS is in px, so rem scaling would not reach it).
export const TEXT_SIZES = [
  { value: 'small', label: 'Small', zoom: 0.9 },
  { value: 'default', label: 'Default', zoom: 1 },
  { value: 'large', label: 'Large', zoom: 1.15 },
  { value: 'larger', label: 'Larger', zoom: 1.3 },
]

export const DEFAULT_TEXT_SIZE = 'default'

export function isTextSize(value) {
  return TEXT_SIZES.some((s) => s.value === value)
}

export function zoomFor(value) {
  return (TEXT_SIZES.find((s) => s.value === value) ?? TEXT_SIZES[1]).zoom
}

// The size one step bigger (+1) or smaller (-1), stopping at the ends
export function stepTextSize(value, direction) {
  const index = TEXT_SIZES.findIndex((s) => s.value === value)
  const next = Math.min(TEXT_SIZES.length - 1, Math.max(0, (index < 0 ? 1 : index) + direction))
  return TEXT_SIZES[next].value
}
