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

export function UpDownIcon({ size = 11 }) {
  return (
    <Icon size={size} viewBox="0 0 11 11">
      <path
        d="M3.4375 4.125L5.5 2.0625L7.5625 4.125M3.4375 6.875L5.5 8.9375L7.5625 6.875"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Icon>
  )
}

// Small arrow for the sorted table column; points up for ascending, down for descending
export function SortArrowIcon({ direction, size = 8 }) {
  return (
    <Icon size={size} viewBox="0 0 8 8">
      <path
        d={direction === 'asc' ? 'M1.5 5.25L4 2.75L6.5 5.25' : 'M1.5 2.75L4 5.25L6.5 2.75'}
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Icon>
  )
}

// Disclosure arrow for collapsible sections; CSS rotates it to point right when closed
export function DisclosureIcon({ size = 14 }) {
  return (
    <Icon size={size} viewBox="0 0 14 14">
      <path
        d="M3.0625 5.25L7 9.1875L10.9375 5.25"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Icon>
  )
}

// Not in the Figma file: an 8-tooth gear drawn to match the other icons
export function GearIcon({ size = 16 }) {
  // Figma "icon/gear" (account card, node 44:971)
  return (
    <Icon size={size} viewBox="0 0 16 16">
      <path
        d="M8 1.4L10.53 1.9L9.99 3.2L11.68 4.32L12.67 3.33L14.1 5.47L12.8 6.01L13.2 8H14.6L14.1 10.53L12.8 9.99L11.68 11.68L12.67 12.67L10.53 14.1L9.99 12.8L8 13.2V14.6L5.47 14.1L6.01 12.8L4.32 11.68L3.33 12.67L1.9 10.53L3.2 9.99L2.8 8H1.4L1.9 5.47L3.2 6.01L4.32 4.32L3.33 3.33L5.47 1.9L6.01 3.2L8 2.8V1.4Z"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinejoin="round"
      />
      <path
        d="M10.1 8C10.1 9.1598 9.1598 10.1 8 10.1C6.8402 10.1 5.9 9.1598 5.9 8C5.9 6.8402 6.8402 5.9 8 5.9C9.1598 5.9 10.1 6.8402 10.1 8Z"
        stroke="currentColor"
        strokeWidth="1.3"
      />
    </Icon>
  )
}

// ---------- Mac app setup screens (paths copied from the Figma M7 frames) ----------

export function PhoneIcon({ size = 36 }) {
  return (
    <Icon size={size} viewBox="0 0 36 36">
      <path
        d="M21.75 3.75H14.25C12.1789 3.75 10.5 5.42893 10.5 7.5V28.5C10.5 30.5711 12.1789 32.25 14.25 32.25H21.75C23.8211 32.25 25.5 30.5711 25.5 28.5V7.5C25.5 5.42893 23.8211 3.75 21.75 3.75Z"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <path d="M15.75 27.75H20.25" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </Icon>
  )
}

export function DownloadIcon({ size = 36 }) {
  return (
    <Icon size={size} viewBox="0 0 36 36">
      <path
        d="M18 6V22.5M24.75 15.75L18 22.5L11.25 15.75M7.5 29.25H28.5"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Icon>
  )
}

// Drawn on the 36px grid; strokes are scaled so they stay as thick as in Figma at 20 and 14px
export function WarningIcon({ size = 36 }) {
  const k = 36 / size
  return (
    <Icon size={size} viewBox="0 0 36 36">
      <path d="M18 5.25L32.25 30H3.75L18 5.25Z" stroke="currentColor" strokeWidth={1.6 * k} strokeLinejoin="round" />
      <path d="M18 14.25V21.75" stroke="currentColor" strokeWidth={1.8 * k} strokeLinecap="round" />
      <path
        d="M18 27.45C18.8284 27.45 19.5 26.7784 19.5 25.95C19.5 25.1216 18.8284 24.45 18 24.45C17.1716 24.45 16.5 25.1216 16.5 25.95C16.5 26.7784 17.1716 27.45 18 27.45Z"
        fill="currentColor"
      />
    </Icon>
  )
}

export function InfoIcon({ size = 16 }) {
  return (
    <Icon size={size} viewBox="0 0 16 16">
      <path
        d="M8 14.5C11.5899 14.5 14.5 11.5899 14.5 8C14.5 4.41015 11.5899 1.5 8 1.5C4.41015 1.5 1.5 4.41015 1.5 8C1.5 11.5899 4.41015 14.5 8 14.5Z"
        stroke="currentColor"
        strokeWidth="1.4"
      />
      <path d="M8 7.2V11.2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path
        d="M8 5.8C8.49706 5.8 8.9 5.39706 8.9 4.9C8.9 4.40294 8.49706 4 8 4C7.50294 4 7.1 4.40294 7.1 4.9C7.1 5.39706 7.50294 5.8 8 5.8Z"
        fill="currentColor"
      />
    </Icon>
  )
}

// Filled circle in currentColor (green in Settings) with a white tick
export function CheckCircleIcon({ size = 14 }) {
  return (
    <Icon size={size} viewBox="0 0 14 14">
      <path
        d="M7 13.125C10.3827 13.125 13.125 10.3827 13.125 7C13.125 3.61726 10.3827 0.875 7 0.875C3.61726 0.875 0.875 3.61726 0.875 7C0.875 10.3827 3.61726 13.125 7 13.125Z"
        fill="currentColor"
      />
      <path d="M4.2 7.175L6.125 9.1L9.8 5.075" stroke="white" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </Icon>
  )
}

export function ChevronsIcon({ size = 12 }) {
  return (
    <Icon size={size} viewBox="0 0 12 12">
      <path
        d="M3.75 4.5L6 2.25L8.25 4.5M3.75 7.5L6 9.75L8.25 7.5"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Icon>
  )
}

// macOS-style activity spinner: eight spokes fading out, turned in steps by CSS (.spinner)
const SPOKES = [
  ['M7 3.85V1.05', 0.25],
  ['M9.23125 4.76875L11.2088 2.79125', 0.35],
  ['M10.15 7H12.95', 0.45],
  ['M9.23125 9.23125L11.2088 11.2088', 0.55],
  ['M7 10.15V12.95', 0.65],
  ['M4.76875 9.23125L2.79125 11.2088', 0.75],
  ['M3.85 7H1.05', 0.85],
  ['M4.76875 4.76875L2.79125 2.79125', 0.95],
]

export function SpinnerIcon({ size = 14 }) {
  return (
    <Icon size={size} viewBox="0 0 14 14" className="spinner">
      {SPOKES.map(([d, opacity]) => (
        <path key={d} d={d} stroke="currentColor" strokeOpacity={opacity} strokeWidth="1.8" strokeLinecap="round" />
      ))}
    </Icon>
  )
}

// The quantity stepper's arrows (Figma order ticket)
export function StepUpIcon({ size = 12 }) {
  return (
    <Icon size={size} viewBox="0 0 12 12">
      <path d="M3.43 8.14L6 5.57L8.57 8.14" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </Icon>
  )
}

export function StepDownIcon({ size = 12 }) {
  return (
    <Icon size={size} viewBox="0 0 12 12">
      <path d="M3.43 5.57L6 8.14L8.57 5.57" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </Icon>
  )
}

// The large check in the "Order filled" sheet
export function CheckIcon({ size = 30 }) {
  return (
    <Icon size={size} viewBox="0 0 30 30">
      <path d="M7.5 15.625L12.5 20.625L22.5 9.375" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </Icon>
  )
}

// Sidebar: Orders (Figma icon/orders)
export function OrdersIcon({ size = 16 }) {
  return (
    <Icon size={size} viewBox="0 0 16 16">
      <path
        d="M4.5 2H11.5C12.6046 2 13.5 2.89543 13.5 4V12C13.5 13.1046 12.6046 14 11.5 14H4.5C3.39543 14 2.5 13.1046 2.5 12V4C2.5 2.89543 3.39543 2 4.5 2Z"
        stroke="currentColor"
        strokeWidth="1.4"
      />
      <path d="M5.5 5.5H10.5M5.5 8H10.5M5.5 10.5H8.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </Icon>
  )
}

// The Settings sheet's close button (Figma "icon/close", node 45:561)
export function CloseIcon({ size = 14 }) {
  return (
    <Icon size={size} viewBox="0 0 14 14">
      <path d="M4.375 4.375L7 7M7 7L9.625 9.625M7 7L9.625 4.375M7 7L4.375 9.625" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </Icon>
  )
}

// Show / hide the list on Positions and Markets (no Figma icon: drawn like macOS's sidebar symbol)
export function SidebarIcon({ size = 16 }) {
  return (
    <Icon size={size} viewBox="0 0 16 16">
      <rect x="1.75" y="2.75" width="12.5" height="10.5" rx="2.25" stroke="currentColor" strokeWidth="1.3" />
      <path d="M6 3V13" stroke="currentColor" strokeWidth="1.3" />
      <path d="M3.6 5.5H4.4M3.6 7.5H4.4M3.6 9.5H4.4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </Icon>
  )
}
