import { drawdownDates, pct, ratio } from './riskFormat.js'

const betaSub = (market) => (beta) =>
  beta == null ? 'Not enough index prices' : `Moves ${Math.abs(beta * 10).toFixed(1)}% when the ${market} moves 10%`

// What the Risk page shows and where (Figma Risk / V5A): the two rows of headline tiles and the
// twelve panels in two columns. Each Milestone 8 issue fills in its tiles' value and caption and its
// panel's body; until then a tile shows "—" and a panel an empty frame.
//
// Tile: { id, label, caption, explainer, section, value?(section, meta) -> text, sub?(section, meta),
//         tone?(section) -> 'loss' | 'amber' | undefined }
// Panel: { code, id, title, section, explainer, column ('left' | 'right'), order (1-12) }

export const TILE_ROWS = [
  [
    {
      id: 'volatility', label: 'Volatility', caption: 'Typical yearly swing', explainer: 'volatility', section: 'volatility',
      value: (s) => pct(s.portfolio.volatility),
    },
    {
      id: 'beta_asx', label: 'Beta · ASX 200', caption: 'How much you move with the ASX', explainer: 'beta_asx', section: 'volatility',
      value: (s) => ratio(s.portfolio.beta_asx),
      sub: (s) => betaSub('ASX')(s.portfolio.beta_asx),
    },
    {
      id: 'beta_us', label: 'Beta · S&P 500', caption: 'How much you move with the S&P', explainer: 'beta_us', section: 'volatility',
      value: (s) => ratio(s.portfolio.beta_us),
      sub: (s) => betaSub('S&P')(s.portfolio.beta_us),
    },
    {
      id: 'effective_holdings', label: 'Effective holdings', caption: 'How many stocks you behave like', explainer: 'effective_holdings', section: 'concentration',
      value: (s) => `${s.effective_holdings.toFixed(1)} / ${s.count}`,
      sub: (s) => `Behaves like about ${Math.max(1, Math.round(s.effective_holdings))} ${Math.round(s.effective_holdings) === 1 ? 'stock' : 'stocks'}`,
      // Amber when the money is spread over less than half as many stocks as you own
      tone: (s) => (s.effective_holdings < s.count / 2 ? 'amber' : undefined),
    },
    {
      id: 'max_drawdown', label: 'Max drawdown', caption: 'Biggest fall in the period', explainer: 'max_drawdown', section: 'volatility',
      value: (s) => pct(s.max_drawdown.fall),
      sub: (s) => drawdownDates(s.max_drawdown),
      tone: (s) => (s.max_drawdown.fall < 0 ? 'loss' : undefined),
    },
  ],
  [
    {
      id: 'sharpe', label: 'Sharpe ratio', caption: 'Return per unit of risk', explainer: 'sharpe', section: 'performance',
      value: (s) => ratio(s.portfolio.sharpe),
      sub: (s) => `Return per unit of risk. ASX 200: ${ratio(s.benchmarks.ASX.sharpe)}`,
    },
    {
      id: 'tracking_asx', label: 'Tracking error · ASX 200', caption: 'How far you drift from the ASX', explainer: 'tracking_asx', section: 'performance',
      value: (s) => pct(s.tracking_error.ASX),
    },
    {
      id: 'tracking_us', label: 'Tracking error · S&P 500', caption: 'How far you drift from the S&P', explainer: 'tracking_us', section: 'performance',
      value: (s) => pct(s.tracking_error.US),
    },
    { id: 'var_1d', label: 'Value at risk · 1 day', caption: '1 day in 20 loses more than this', explainer: 'var', section: 'var' },
    { id: 'liquidity', label: 'Liquidity', caption: 'Time to sell everything', explainer: 'liquidity', section: 'liquidity' },
  ],
]

export const PANELS = [
  { code: 'RSK 01', id: 'concentration', title: 'Concentration', section: 'concentration', explainer: 'concentration', column: 'left', order: 1 },
  { code: 'RSK 02', id: 'exposure', title: 'Exposure', section: 'exposure', explainer: 'exposure', column: 'right', order: 2 },
  { code: 'RSK 03', id: 'correlation', title: 'Correlation', section: 'correlation', explainer: 'correlation', column: 'right', order: 3 },
  { code: 'RSK 04', id: 'volatility', title: 'Volatility and beta', section: 'volatility', explainer: 'volatility_beta', column: 'left', order: 4 },
  { code: 'RSK 05', id: 'currency', title: 'Currency effect', section: 'currency', explainer: 'currency', column: 'left', order: 5 },
  { code: 'RSK 06', id: 'factors', title: 'Hidden factors', section: 'factors', explainer: 'factors', column: 'left', order: 6 },
  { code: 'RSK 07', id: 'stress', title: 'Stress tests', section: 'stress', explainer: 'stress', column: 'right', order: 7 },
  { code: 'RSK 08', id: 'var', title: 'Value at Risk', section: 'var', explainer: 'var', column: 'left', order: 8 },
  { code: 'RSK 09', id: 'attribution', title: 'Attribution', section: 'attribution', explainer: 'attribution', column: 'right', order: 9 },
  { code: 'RSK 10', id: 'mixes', title: 'Optimisation and hedging', section: 'mixes', explainer: 'mixes', column: 'left', order: 10 },
  { code: 'RSK 11', id: 'bankruptcy', title: 'Bankruptcy risk', section: 'bankruptcy', explainer: 'bankruptcy', column: 'right', order: 11 },
  { code: 'RSK 12', id: 'liquidity', title: 'Liquidity', section: 'liquidity', explainer: 'liquidity', column: 'right', order: 12 },
]
