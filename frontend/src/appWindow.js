// Sizes the Mac app's window for each screen: the setup screens are small fixed windows (as in
// the Figma frames), the dashboard is large and resizable. Does nothing outside the app.
import { getCurrentWindow, LogicalSize } from '@tauri-apps/api/window'
import { IN_APP } from './api.js'

const SIZES = {
  startup: [360, 280],
  welcome: [560, 500],
  install: [560, 500],
  signin: [480, 600],
  dashboard: [1320, 860],
}

let current = null

export async function sizeWindowFor(screen) {
  if (!IN_APP || current === screen) return
  current = screen
  const window = getCurrentWindow()
  const [width, height] = SIZES[screen]
  const dashboard = screen === 'dashboard'
  try {
    await window.setMinSize(dashboard ? new LogicalSize(960, 640) : null)
    await window.setResizable(dashboard)
    await window.setSize(new LogicalSize(width, height))
    await window.center()
  } catch (err) {
    console.warn('Couldn’t resize the window', err)
  }
}
