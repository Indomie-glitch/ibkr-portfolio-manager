// The resizable, hideable list panes (hooks/useResizableWidth.js), by page. Each name is also the
// localStorage key for the list's width ("…Collapsed" for whether it's hidden).
export const HOLDINGS_LIST = 'holdingsListWidth'
export const MARKETS_LIST = 'marketsListWidth'
export const WATCHLIST_LIST = 'watchlistListWidth'

export const LIST_FOR_PAGE = { positions: HOLDINGS_LIST, markets: MARKETS_LIST, watchlist: WATCHLIST_LIST }
