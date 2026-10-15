import { SparklesIcon } from './icons.jsx'

// Placeholder until AI summaries arrive in milestone 5
function AiSummaryCard({ title, buttonLabel, description }) {
  return (
    <section className="ai-card">
      <div className="ai-header">
        <SparklesIcon size={14} />
        <h2>{title}</h2>
        <div className="spacer" />
        <button type="button" className="button-primary" disabled title="Coming in milestone 5">
          <SparklesIcon size={13} /> {buttonLabel}
        </button>
      </div>
      <p className="ai-text">{description}</p>
    </section>
  )
}

export default AiSummaryCard
