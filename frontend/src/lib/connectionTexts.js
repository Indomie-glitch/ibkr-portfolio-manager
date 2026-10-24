// Texts for the Connections section and the full page (#114, #279): the ⓘ explainers
// (components/risk/InfoButton.jsx: what it is, what to consider) and the filter keys' labels.
export const MAP_EXPLAINER = {
  title: 'Connections',
  what: 'How this stock is linked to others: the indexes it’s in, the largest companies in its industry, the people who run it, and its board of directors. Lines in amber lead to stocks you own.',
  consider: 'A link shows a shared index, industry or person, not how the prices move together. Board members come from the company’s latest proxy statement or annual report; index lists and competitors are refreshed weekly.',
}
export const FILTER_LABELS = { all: 'ALL', indices: 'INDICES', competitors: 'COMPETITORS', people: 'PEOPLE' }

export const INSPECTOR_EXPLAINER = {
  title: 'Selected',
  what: 'The details of the node you clicked: for a person, their role here and the other boards the document lists, with a Wikipedia page when one is known; for a stock or index, the facts behind its link. A name in amber means you own it, or the person sits on the board of something you own.',
  consider: 'Descriptions are put together from the same documents and data as the map, not written by hand, so a person without a document has no description. Double-click a node to open its page; a person opens on Wikipedia.',
}

export const LIST_EXPLAINER = {
  title: 'All connections',
  what: 'Everything on the map as a list, with how each is connected to this stock and which of your holdings it touches. The ones touching your holdings come first, then indexes, competitors (largest first) and people.',
  consider: 'A link shows a shared index, industry, board or person, not how the prices move together. At depth 2 the list also has the other company boards the directors sit on.',
}

export const DEPTH_EXPLAINER = {
  title: 'Depth',
  what: 'Depth 1 is the stock’s own links. Depth 2 adds, for each director, the other company boards the document lists for them: small dots joined to the director.',
  consider: 'Those boards are named in the document without a ticker, so only the ones that match a company you own can be opened.',
}
