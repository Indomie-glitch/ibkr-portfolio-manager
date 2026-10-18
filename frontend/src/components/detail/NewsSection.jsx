import { useState } from 'react'
import { fetchNews } from '../../lib/api.js'
import { formatAge } from '../../lib/format.js'
import { useFetch } from '../../hooks/useFetch.js'
import { ChevronIcon } from '../icons.jsx'
import SentimentArrows from './SentimentArrows.jsx'
import { SectionLoading, SectionUnavailable } from './DisclosureSection.jsx'

const FIRST_ITEMS = 4
// Badge colours that keep white text readable in both themes
const BADGE_COLORS = ['#1d1d1f', '#0a7a5a', '#e8622c', '#f58220', '#5856d6', '#007aff', '#af52de', '#8e5b3d']

// The same publisher always gets the same colour
function badgeColor(publisher) {
  let hash = 0
  for (const char of publisher) hash = (hash * 31 + char.charCodeAt(0)) >>> 0
  return BADGE_COLORS[hash % BADGE_COLORS.length]
}

function NewsSection({ holding, companyName }) {
  const { data, error, loading } = useFetch(() => fetchNews(holding.con_id), holding.con_id)
  const [showAll, setShowAll] = useState(false)

  if (loading) return <SectionLoading lines={4} />
  if (error) return <SectionUnavailable what="News" reason={error} />

  const items = data.items
  if (items.length === 0) {
    return <p className="section-empty">No recent headlines mention {companyName}.</p>
  }

  const visible = showAll ? items : items.slice(0, FIRST_ITEMS)
  return (
    <>
      <ul className="news-list">
        {visible.map((item) => {
          const publisher = item.publisher || 'News'
          return (
            <li key={item.url}>
              {/* Opens in the browser; noopener stops the article page from controlling this tab */}
              <a className="news-item" href={item.url} target="_blank" rel="noopener noreferrer">
                <span className="news-badge" style={{ background: badgeColor(publisher) }} aria-hidden="true">
                  {publisher.charAt(0).toUpperCase()}
                </span>
                <span className="news-text">
                  <span className="news-title">{item.title}</span>
                  <span className="news-meta">
                    {publisher}
                    {item.published && ` · ${formatAge(item.published)}`}
                  </span>
                </span>
                <SentimentArrows sentiment={item.sentiment} />
                <span className="news-chevron">
                  <ChevronIcon />
                </span>
              </a>
            </li>
          )
        })}
      </ul>
      {items.length > FIRST_ITEMS && (
        <button type="button" className="link-button" onClick={() => setShowAll(!showAll)}>
          {showAll ? 'Show fewer' : `Show all news (${items.length})`}
        </button>
      )}
    </>
  )
}

export default NewsSection
