// The 10 sections, always in this order, in four groups
export const GROUPS = [
  {
    title: 'About the company',
    sections: [
      ['business_snapshot', 'Business snapshot'],
      ['financial_health', 'Financial health'],
      ['valuation', 'Valuation in context'],
    ],
  },
  {
    title: 'What’s happening now',
    sections: [
      ['news_digest', 'News digest'],
      ['price_moves', 'Why the price moved'],
      ['upcoming_events', 'Upcoming events'],
    ],
  },
  {
    title: 'Looking ahead',
    sections: [
      ['bull_bear', 'Bull and bear case'],
      ['key_risks', 'Key risks'],
    ],
  },
  {
    title: 'What it means for you',
    sections: [
      ['your_position', 'Your position'],
      ['changes_since_last', 'What changed since you last looked'],
    ],
  },
]

// The groups for a summary: a stock the investor doesn't own has no Your position section (#95)
export function groupsFor(owned) {
  if (owned) return GROUPS
  return GROUPS.map((group) =>
    group.sections.some(([key]) => key === 'your_position')
      ? { title: 'Since you last looked', sections: group.sections.filter(([key]) => key !== 'your_position') }
      : group,
  )
}
