// Takes the README screenshots (docs/screenshots) with headless Chrome, in light and dark mode.
//
//   node scripts/screenshots.mjs [outDir]
//
// Needs the backend (port 8000, connected to IB Gateway) and the frontend dev server (5173)
// running, and Google Chrome installed.
//
// Chrome's profile goes in a new folder under the system temp directory and is deleted at the end,
// never next to the screenshots: a profile in docs/ once ended up committed.
import { spawn } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

const outDir = resolve(process.argv[2] ?? 'docs/screenshots')
const APP_URL = 'http://localhost:5173/'
const PORT = 9335
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'

mkdirSync(outDir, { recursive: true })
const profileDir = mkdtempSync(join(tmpdir(), 'portfolio-screenshots-'))
const chrome = spawn(
  CHROME,
  ['--headless=new', `--remote-debugging-port=${PORT}`, '--hide-scrollbars', `--user-data-dir=${profileDir}`, 'about:blank'],
  { stdio: 'ignore' },
)
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

let ws
try {
  let targets
  for (let i = 0; i < 40 && !targets; i++) {
    try {
      targets = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()
    } catch {
      await sleep(250)
    }
  }
  if (!targets) throw new Error('Chrome did not start')
  ws = new WebSocket(targets.find((t) => t.type === 'page').webSocketDebuggerUrl)
  await new Promise((r) => ws.addEventListener('open', r))

  let id = 0
  const pending = new Map()
  ws.addEventListener('message', (e) => {
    const m = JSON.parse(e.data)
    if (pending.has(m.id)) {
      pending.get(m.id)(m.result)
      pending.delete(m.id)
    }
  })
  const send = (method, params = {}) =>
    new Promise((r) => {
      pending.set(++id, r)
      ws.send(JSON.stringify({ id, method, params }))
    })
  const evaluate = async (expr) =>
    (await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })).result?.value
  const save = async (name, clip) => {
    const { data } = await send('Page.captureScreenshot', { format: 'png', ...(clip && { clip, captureBeyondViewport: true }) })
    writeFileSync(join(outDir, `${name}.png`), Buffer.from(data, 'base64'))
    console.log('saved', name)
  }

  for (const scheme of ['light', 'dark']) {
    await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 2, mobile: false })
    await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: scheme }] })
    await send('Page.navigate', { url: APP_URL })
    await sleep(6000)
    await save(`overview-${scheme}`)

    await evaluate(`document.querySelector('.positions-table tbody tr')?.click()`)
    await sleep(4000)
    await save(`positions-${scheme}`)

    // The whole detail panel of the selected holding, at the width the README shows
    await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 2000, deviceScaleFactor: 2, mobile: false })
    await sleep(3000)
    const box = await evaluate(
      `(() => { const r = document.querySelector('.detail')?.getBoundingClientRect(); return r && { x: r.x, y: r.y + scrollY, width: r.width, height: r.height } })()`,
    )
    if (box) await save(`stock-detail-${scheme}`, { ...box, scale: 1 })
  }
} finally {
  ws?.close()
  chrome.kill()
  await sleep(500) // let Chrome release the profile before deleting it
  rmSync(profileDir, { recursive: true, force: true })
}
