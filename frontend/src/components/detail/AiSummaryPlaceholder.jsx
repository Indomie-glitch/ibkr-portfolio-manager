// Placeholder for the AI summary (milestone 5): headings with skeleton lines, as in the design
function AiSummaryPlaceholder({ name }) {
  const blocks = [
    { heading: `Where ${name} stands now`, lines: [100, 92, 55] },
    { heading: 'What could matter next', lines: [100, 86, 70] },
    { heading: 'What it means for your position', lines: [95, 50] },
  ]

  return (
    <div className="ai-placeholder">
      {blocks.map((block) => (
        <div className="ai-block" key={block.heading}>
          <p className="ai-block-heading">{block.heading}</p>
          {block.lines.map((width, i) => (
            <span key={i} className="skeleton-line accent" style={{ width: `${width}%` }} />
          ))}
        </div>
      ))}
      <p className="section-footnote">
        Generated from the company profile, key statistics, recent news and your position. Not financial advice.
      </p>
    </div>
  )
}

export default AiSummaryPlaceholder
