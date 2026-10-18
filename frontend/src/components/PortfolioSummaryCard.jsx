import {
  fetchPastPortfolioSummary,
  fetchPortfolioSummary,
  fetchPortfolioSummaryComparison,
  fetchPortfolioSummaryHistory,
  generatePortfolioSummary,
} from '../lib/api.js'
import { SummaryPanel } from './detail/SummaryPanel.jsx'
import { portfolioSummary } from './detail/summaryKinds.js'

const SOURCE = {
  key: 'portfolio',
  latest: fetchPortfolioSummary,
  history: fetchPortfolioSummaryHistory,
  past: fetchPastPortfolioSummary,
  compare: fetchPortfolioSummaryComparison,
  generate: generatePortfolioSummary,
  // Past summaries are labelled with the portfolio's value at the time
  historyItem: (item) => ({ ...item, price: item.net_liquidation }),
}

// The AI portfolio summary at the bottom of Overview (#22): the same panel as a stock's AI summary,
// with the portfolio's 8 sections. A holding cited in a point opens on Positions.
function PortfolioSummaryCard({ onOpenHolding }) {
  return (
    <SummaryPanel
      source={SOURCE}
      kind={portfolioSummary(onOpenHolding)}
      sectionId="portfolioSummary"
      title="AI portfolio summary"
      firstLabel="Summarise portfolio"
    />
  )
}

export default PortfolioSummaryCard
