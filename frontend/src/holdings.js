// Combine /positions, /quotes and /account into one list the UI can render directly.
export function buildHoldings(positions, quotes, account) {
  const quoteById = new Map(quotes.map((q) => [q.con_id, q]))
  const fxRates = account?.fx_rates ?? {}

  const holdings = positions.map((p) => {
    const rate = fxRates[p.currency] ?? (p.currency === account?.currency ? 1 : null)
    // Convert a value in the holding's currency to the account's base currency (AUD)
    const toBase = (value) => (value != null && rate != null ? value * rate : null)
    const quote = quoteById.get(p.con_id) ?? null
    const last = quote?.last ?? p.market_price
    const costBasis = p.avg_cost * p.quantity
    return {
      ...p,
      quote,
      last,
      cost_basis: costBasis,
      market: p.exchange === 'ASX' ? 'ASX' : 'US',
      // Base-currency copies so USD and AUD holdings can be compared, summed and sorted
      avg_cost_base: toBase(p.avg_cost),
      last_base: toBase(last),
      cost_basis_base: toBase(costBasis),
      market_value_base: toBase(p.market_value),
      unrealized_pnl_base: toBase(p.unrealized_pnl),
    }
  })

  const totalBase = holdings.reduce((sum, h) => sum + (h.market_value_base ?? 0), 0)
  for (const h of holdings) {
    h.weight = totalBase && h.market_value_base != null ? (h.market_value_base / totalBase) * 100 : null
  }

  // Biggest holdings first
  holdings.sort((a, b) => (b.market_value_base ?? 0) - (a.market_value_base ?? 0))
  return { holdings }
}
