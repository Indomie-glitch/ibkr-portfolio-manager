// Icons from the Figma design, drawn with currentColor so they follow the text colour and theme.
function Icon({ size, viewBox, children, ...rest }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox={viewBox}
      fill="none"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  )
}

export function GridIcon({ size = 16 }) {
  return (
    <Icon size={size} viewBox="0 0 16 16" stroke="currentColor" strokeWidth="1.4">
      <rect x="2" y="2" width="5" height="5" rx="1.5" />
      <rect x="9" y="2" width="5" height="5" rx="1.5" />
      <rect x="2" y="9" width="5" height="5" rx="1.5" />
      <rect x="9" y="9" width="5" height="5" rx="1.5" />
    </Icon>
  )
}

export function ListIcon({ size = 16 }) {
  return (
    <Icon size={size} viewBox="0 0 16 16">
      <circle cx="3" cy="4" r="1" fill="currentColor" />
      <circle cx="3" cy="8" r="1" fill="currentColor" />
      <circle cx="3" cy="12" r="1" fill="currentColor" />
      <path d="M6 4H14M6 8H14M6 12H14" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </Icon>
  )
}

export function SparklesIcon({ size = 16 }) {
  return (
    <Icon size={size} viewBox="0 0 16 16" fill="currentColor">
      <path d="M7 1.5L8.3 5.2L12 6.5L8.3 7.8L7 11.5L5.7 7.8L2 6.5L5.7 5.2L7 1.5Z" />
      <path d="M12.5 10L13.1 11.6L14.5 12.2L13.1 12.8L12.5 14.5L11.9 12.8L10.5 12.2L11.9 11.6L12.5 10Z" />
    </Icon>
  )
}

export function TradeIcon({ size = 16 }) {
  return (
    <Icon size={size} viewBox="0 0 16 16">
      <path
        d="M2.5 5H12.5M10 7.5L12.5 5L10 2.5M13.5 11H3.5M6 13.5L3.5 11L6 8.5"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Icon>
  )
}

export function RefreshIcon({ size = 14 }) {
  return (
    <Icon size={size} viewBox="0 0 14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <path d="M11.375 7C11.3732 8.01208 11.0205 8.99223 10.3771 9.77347C9.73375 10.5547 8.83938 11.0887 7.84642 11.2845C6.85347 11.4803 5.82333 11.3258 4.93152 10.8473C4.0397 10.3688 3.34137 9.59589 2.95549 8.66026C2.56961 7.72464 2.52005 6.68416 2.81525 5.71609C3.11045 4.74802 3.73216 3.91223 4.57446 3.35112C5.41675 2.79002 6.42754 2.53829 7.43461 2.63883C8.44169 2.73936 9.38275 3.18595 10.0975 3.9025" />
      <path d="M11.375 2.1875V4.8125H8.75" strokeLinejoin="round" />
    </Icon>
  )
}

export function ChevronIcon({ size = 12 }) {
  return (
    <Icon size={size} viewBox="0 0 12 12">
      <path
        d="M4.5 2.625L7.875 6L4.5 9.375"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Icon>
  )
}

export function SearchIcon({ size = 14 }) {
  return (
    <Icon size={size} viewBox="0 0 14 14" stroke="currentColor" strokeWidth="1.5">
      <circle cx="6.125" cy="6.125" r="3.9375" />
      <path d="M9.1875 9.1875L12.25 12.25" strokeLinecap="round" />
    </Icon>
  )
}
