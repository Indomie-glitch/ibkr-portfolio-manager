import { useId } from 'react'

// Stacked chevrons for a news item's sentiment (#97; Figma "Sentiment Arrows", node 70:514):
// 1-3 chevrons for strength 1-3, pointing up in the gain colour for good news and down in the loss
// colour for bad news. Each chevron fades from its tip (100%) to its base (18%), and each one
// further back is fainter. Neutral news gets no arrows.

// Where each chevron's tip sits in the 26px box, front one first (copied from the Figma SVGs)
const TIPS = { 1: [7], 2: [3.5, 10.5], 3: [0, 7, 14] }
const OPACITY = [1, 0.78, 0.56]
const STRENGTH_WORDS = { 1: 'slightly', 2: 'clearly', 3: 'strongly' }

function chevron(tip) {
  return `M13 ${tip}L26 ${tip + 12}H20.5L13 ${tip + 5.5}L5.5 ${tip + 12}H0L13 ${tip}Z`
}

export function sentimentLabel(sentiment) {
  if (!sentiment || sentiment.direction === 'neutral') return null
  return `${STRENGTH_WORDS[sentiment.strength]} ${sentiment.direction === 'positive' ? 'good' : 'bad'} news`
}

function SentimentArrows({ sentiment }) {
  // Gradient ids must be unique on the page; useId's punctuation isn't safe inside url(#...)
  const id = `sentiment${useId().replace(/[^a-zA-Z0-9]/g, '')}`
  const label = sentimentLabel(sentiment)
  if (!label || !TIPS[sentiment.strength]) return null

  const positive = sentiment.direction === 'positive'
  const tips = TIPS[sentiment.strength]
  return (
    <span
      className={`sentiment-arrows ${positive ? 'gain' : 'loss'}`}
      role="img"
      aria-label={`AI: ${label}`}
      title={sentiment.reason ? `AI: ${label}. ${sentiment.reason}` : `AI: ${label}`}
    >
      <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">
        <defs>
          {tips.map((tip, i) => (
            <linearGradient key={tip} id={`${id}-${i}`} x1="13" y1={tip} x2="13" y2={tip + 12} gradientUnits="userSpaceOnUse">
              <stop stopColor="currentColor" />
              <stop offset="1" stopColor="currentColor" stopOpacity="0.18" />
            </linearGradient>
          ))}
        </defs>
        {/* Bad news is the same drawing flipped upside down */}
        <g transform={positive ? undefined : 'matrix(1 0 0 -1 0 26)'}>
          {tips.map((tip, i) => (
            <path key={tip} d={chevron(tip)} opacity={OPACITY[i]} fill={`url(#${id}-${i})`} />
          ))}
        </g>
      </svg>
    </span>
  )
}

export default SentimentArrows
