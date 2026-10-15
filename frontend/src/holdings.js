// Combine /positions, /quotes and /account into one list the UI can render directly.
export function buildHoldings(positions, quotes, account) {
  const quoteById = new Map(quotes.map((q) => [q.con_id, q]))
  const fxRates = account?.fx_rates ?? {}

  const holdings = positions.map((p) => {
    const rate = fxRates[p.currency] ?? (p.currency === account?.currency ? 1 : null)
    const marketValueBase = p.market_value != null && rate != null ? p.market_value * rate : null
    return {
      ...p,
      quote: quoteById.get(p.con_id) ?? null,
      cost_basis: p.avg_cost * p.quantity,
      market: p.exchange === 'ASX' ? 'ASX' : 'US',
      // Market value converted to the account's base currency, for weights and allocation
      market_value_base: marketValueBase,
    }
  })

  const totalBase = holdings.reduce((sum, h) => sum + (h.market_value_base ?? 0), 0)
  for (const h of holdings) {
    h.weight = totalBase && h.market_value_base != null ? (h.market_value_base / totalBase) * 100 : null
  }

  // Biggest holdings first
  holdings.sort((a, b) => (b.market_value_base ?? 0) - (a.market_value_base ?? 0))
  return { holdings, totalBase }
}
