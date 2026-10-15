import { useState } from 'react'
import { formatDayMonth, formatNumber } from '../../format.js'
import { SectionLoading, SectionUnavailable } from './DisclosureSection.jsx'

const LONG_DESCRIPTION = 320 // characters; longer descriptions start collapsed

// "https://www.telstra.com.au/" -> "telstra.com.au"
function domain(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

function Fact({ label, children }) {
  return (
    <div className="fact">
      <dt>{label}</dt>
      <dd>{children ?? '—'}</dd>
    </div>
  )
}

// The profile is fetched by HoldingDetail (it also supplies the full name in the header)
function AboutSection({ profile, error, loading }) {
  const [expanded, setExpanded] = useState(false)

  if (loading) return <SectionLoading lines={4} />
  if (error || !profile) return <SectionUnavailable what="Company profile" reason={error} />

  const description = profile.description
  const long = description && description.length > LONG_DESCRIPTION

  return (
    <div className="about">
      <div className="about-description">
        <p className={long && !expanded ? 'clamped' : ''}>{description || 'No description available.'}</p>
        {long && (
          <button type="button" className="link-button" onClick={() => setExpanded(!expanded)}>
            {expanded ? 'Show less' : 'Show more'}
          </button>
        )}
      </div>
      <dl className="about-facts">
        <Fact label="Sector">{profile.sector}</Fact>
        <Fact label="Industry">{profile.industry}</Fact>
        <Fact label="Employees">{profile.employees != null ? formatNumber(profile.employees, 0) : null}</Fact>
        <Fact label="Fiscal year ends">{profile.fiscal_year_end ? formatDayMonth(profile.fiscal_year_end) : null}</Fact>
        <Fact label="Website">
          {profile.website ? (
            <a href={profile.website} target="_blank" rel="noopener noreferrer">
              {domain(profile.website)}
            </a>
          ) : null}
        </Fact>
      </dl>
    </div>
  )
}

export default AboutSection
