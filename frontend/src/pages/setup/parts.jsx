// Pieces shared by the setup screens (Figma page "Desktop app (M7)")
import appIcon from '../../assets/app-icon.png'

// The app icon (src-tauri/icon-source.png). The image has macOS's margin and shadow built in, so
// it's drawn 25% larger with the extra as negative margin: the visible square is `size` points.
export function AppIcon({ size }) {
  const drawn = Math.round(size * 1.25)
  return <img className="app-icon" src={appIcon} width={drawn} height={drawn} alt="" style={{ margin: (size - drawn) / 2 }} />
}

export function IconCircle({ tone = 'accent', children }) {
  return <div className={`icon-circle ${tone}`}>{children}</div>
}
