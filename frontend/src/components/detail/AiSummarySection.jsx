import { fetchPastSummary, fetchSummary, fetchSummaryComparison, fetchSummaryHistory, generateSummary } from '../../lib/api.js'
import { SummaryPanel } from './SummaryPanel.jsx'

// A stock's AI summary section in its detail (holdings, and any stock from Markets or a watchlist)
function AiSummarySection({ holding, name, owned = true }) {
  const conId = holding.con_id
  const source = {
    key: conId,
    latest: () => fetchSummary(conId),
    history: () => fetchSummaryHistory(conId),
    past: (id) => fetchPastSummary(conId, id),
    compare: (a, b) => fetchSummaryComparison(conId, a, b),
    generate: (onEvent) => generateSummary(conId, onEvent),
  }
  return <SummaryPanel source={source} sectionId="aiSummary" title="AI summary" firstLabel="Summarise" name={name} owned={owned} />
}

export default AiSummarySection
