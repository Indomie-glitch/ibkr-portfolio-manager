// Watchlist data (#88). Run with: npm test
import assert from 'node:assert/strict'
import { test } from 'vitest'
import { addList, addStockTo, draggableStock, droppedStock, isStockDrag, parseSaved, removeList, removeStockFrom, renameList, uniqueName } from './watchlists.js'

const aapl = { con_id: 265598, symbol: 'AAPL', name: 'Apple Inc', exchange: 'NASDAQ', currency: 'USD', market: 'US', quote: { last: 1 } }
const bhp = { con_id: 4036812, symbol: 'BHP', name: 'BHP Group', exchange: 'ASX', currency: 'AUD', market: 'ASX' }

test('names are trimmed, never empty and never repeated', () => {
  const lists = [{ id: 'a', name: 'New Watchlist', stocks: [] }, { id: 'b', name: 'Tech', stocks: [] }]
  assert.equal(uniqueName('  Mining  ', lists), 'Mining')
  assert.equal(uniqueName('   ', []), 'New Watchlist')
  assert.equal(uniqueName('new watchlist', lists), 'new watchlist 2')
  assert.equal(uniqueName('TECH', lists), 'TECH 2')
  // Keeping its own name isn't a clash
  assert.equal(uniqueName('Tech', lists, 'b'), 'Tech')
  assert.equal(uniqueName('x'.repeat(60), []).length, 40)
})

test('create, rename and delete', () => {
  let lists = addList([], 'a', 'Mining')
  lists = addList(lists, 'b', 'Mining')
  assert.deepEqual(lists.map((l) => l.name), ['Mining', 'Mining 2'])
  lists = renameList(lists, 'b', 'ASX dividends')
  assert.deepEqual(lists.map((l) => l.name), ['Mining', 'ASX dividends'])
  assert.deepEqual(removeList(lists, 'a').map((l) => l.id), ['b'])
})

test('stocks are added once, newest first, without extra fields', () => {
  let lists = addList([], 'a', 'Tech')
  lists = addStockTo(lists, 'a', aapl)
  lists = addStockTo(lists, 'a', bhp)
  lists = addStockTo(lists, 'a', aapl)
  assert.deepEqual(lists[0].stocks.map((s) => s.symbol), ['BHP', 'AAPL'])
  assert.equal(lists[0].stocks[1].quote, undefined)
  lists = removeStockFrom(lists, 'a', bhp.con_id)
  assert.deepEqual(lists[0].stocks.map((s) => s.symbol), ['AAPL'])
})

test('saved data that is broken or from elsewhere is ignored', () => {
  assert.deepEqual(parseSaved(null), [])
  assert.deepEqual(parseSaved('not json'), [])
  assert.deepEqual(parseSaved('{"a":1}'), [])
  const saved = JSON.stringify([{ id: 'a', name: 'Tech', stocks: [aapl, { symbol: 'X' }, null] }, { name: 'no id' }])
  const [list, ...rest] = parseSaved(saved)
  assert.equal(rest.length, 0)
  assert.deepEqual(list.stocks.map((s) => s.symbol), ['AAPL'])
})

// A stand-in for the browser's DataTransfer
function fakeDrag() {
  const data = new Map()
  return { dataTransfer: { types: [], setData(type, value) { data.set(type, value); this.types.push(type) }, getData: (type) => data.get(type) ?? '' } }
}

test('a dragged row carries the stock, and only our drags are accepted', () => {
  const e = fakeDrag()
  draggableStock(aapl).onDragStart(e)
  assert.equal(isStockDrag(e), true)
  assert.deepEqual(droppedStock(e), { con_id: 265598, symbol: 'AAPL', name: 'Apple Inc', exchange: 'NASDAQ', currency: 'USD', market: 'US' })
  assert.equal(e.dataTransfer.getData('text/plain'), 'AAPL')

  const text = fakeDrag()
  text.dataTransfer.setData('text/plain', 'hello')
  assert.equal(isStockDrag(text), false)
  assert.equal(droppedStock(text), null)
})
