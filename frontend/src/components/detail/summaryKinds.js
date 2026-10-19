// What differs between a stock's AI summary and the portfolio summary (#22). Everything else (the
// panel, its buttons, history, compare, how sections and citations are drawn) is shared, so the two
// look and behave the same. SummaryPanel provides the kind; SummaryView and SummaryCompare read it.
import { createContext } from 'react'
import { PORTFOLIO_GROUPS, groupsFor } from '../../lib/summarySections.js'

// Data ids a stock summary cites -> label and the part of the page that shows that data
const STOCK_SOURCES = {
  'D:profile': { label: 'About', target: 'section-about' },
  'D:key_stats': { label: 'Key statistics', target: 'section-keyStats' },
  'D:financials': { label: 'Financial statements' },
  'D:valuation_history': { label: 'Past P/E' },
  'D:price_moves': { label: 'Price chart', target: 'price-chart' },
  'D:performance': { label: 'Performance', target: 'section-performance' },
  'D:events': { label: 'Upcoming events' },
  'D:position': { label: 'Your position', target: 'your-position' },
  'D:since_last': { label: 'Previous summary' },
  'D:missing': { label: 'Missing data' },
}

export const STOCK_SUMMARY = {
  name: 'stock',
  // withPosition: false for a stock the investor doesn't own (no Your position section, #95)
  groups: (withPosition) => groupsFor(withPosition),
  source: (id) => STOCK_SOURCES[id] ?? { label: id },
  intro: (name, withPosition) =>
    `No summary yet. Summarise writes a briefing on ${name} from the data on this page: the business, its finances ` +
    `and valuation, recent news and price moves, upcoming events, the case for and against${
      withPosition ? ', risks, and what it means for your position.' : ' and risks.'
    }`,
  basis: (withPosition) =>
    `the company profile, key statistics, financial statements, recent news, price history${
      withPosition ? ' and your position' : ''
    } shown in this app`,
  // The figure next to each summary's time in compare mode
  headline: (view) => view.facts?.['D:key_stats']?.last_price,
}

// Data ids the portfolio summary cites. H:<con_id> (a holding) is named by its symbol and opens it.
const PORTFOLIO_SOURCES = {
  'D:portfolio': { label: 'Portfolio', target: 'portfolio-value' },
  'D:allocation': { label: 'Allocation', target: 'allocation-card' },
  'D:pnl': { label: 'P&L', target: 'positions-table' },
  'D:market_moves': { label: 'Market moves' },
  'D:concentration': { label: 'Concentration', target: 'allocation-card' },
  'D:events': { label: 'Upcoming events' },
  'D:income': { label: 'Dividends' },
  'D:risk': { label: 'Risk analysis' },
  'D:since_last': { label: 'Previous summary' },
  'D:missing': { label: 'Missing data' },
}

export function portfolioSummary(onOpenHolding) {
  return {
    name: 'portfolio',
    groups: () => PORTFOLIO_GROUPS,
    source: (id, facts) => {
      if (id.startsWith('H:')) {
        const holding = facts?.[id]
        const conId = Number(id.slice(2))
        return {
          label: holding?.symbol ?? 'Holding',
          title: holding?.name ? `Open ${holding.name}` : undefined,
          onClick: onOpenHolding ? () => onOpenHolding(conId) : undefined,
        }
      }
      return PORTFOLIO_SOURCES[id] ?? { label: id }
    },
    intro: () =>
      'No summary yet. Summarise portfolio writes a briefing on your whole portfolio from the data on this page: ' +
      'its value and allocation, what drove your P&L, concentration, upcoming events, dividends, key risks, and ' +
      'what changed since the last one.',
    basis: () => 'your account, positions, company data and price history shown in this app',
    headline: (view) => view.facts?.['D:portfolio']?.net_liquidation,
  }
}

export const SummaryKind = createContext(STOCK_SUMMARY)
