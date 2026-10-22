import { formatMoney } from '../../lib/format.js'
import { currencyPlaces, mixLabel, pct, ratio } from '../../lib/riskFormat.js'

// RSK 10 Optimisation and hedging (Figma 106:1339): other ways the same stocks could have been
// weighted, worked out from the period's data, and two hedges. Examples only: no ranking, no "best".
export default function MixesPanel({ section, meta }) {
  const { mixes, currency_hedge: hedge, cash, count } = section
  const current = mixes[0]
  return (
    <>
      <div className="risk-table" role="table" aria-label="Example mixes of your stocks">
        <div className="risk-mix-row risk-table-head" role="row">
          <span role="columnheader">Mix</span>
          <span role="columnheader" className="num">
            Volatility
          </span>
          <span role="columnheader" className="num">
            Return
          </span>
          <span role="columnheader" className="num">
            Sharpe
          </span>
        </div>
        {mixes.map((mix) => {
          const { name, caption } = mixLabel(mix, count)
          return (
            <div className={`risk-mix-row risk-table-row roomy ${mix.id === 'current' ? 'current' : ''}`} role="row" key={mix.id}>
              <span role="cell" className="risk-mix-name">
                <span>{name}</span>
                <span className="risk-mix-caption">{caption}</span>
              </span>
              <span role="cell" className="num risk-mono">
                {pct(mix.volatility)}
              </span>
              <span role="cell" className={`num risk-mono ${mix.annual_return >= 0 ? 'gain' : 'loss'}`}>
                {pct(mix.annual_return, { signed: true })}
              </span>
              <span role="cell" className="num risk-mono">
                {ratio(mix.sharpe)}
              </span>
            </div>
          )
        })}
      </div>
      <p className="risk-small-caps tight">Hedges</p>
      {hedge && (
        <div className="risk-plain">
          <p className="risk-hedge-title">Currency hedge on {currencyPlaces(hedge.currencies)} holdings</p>
          <p className="risk-hedge-text">
            Removes {meta.currency} vs {hedge.currencies.join('/')} swings. Over this period:{' '}
            {formatMoney(hedge.result_base, meta.currency, { decimals: 0, signed: true })};
            volatility {pct(current.volatility)} → {pct(hedge.volatility)}
          </p>
        </div>
      )}
      <div className="risk-plain">
        <p className="risk-hedge-title">Holding some cash or bonds</p>
        <p className="risk-hedge-text">
          {cash == null
            ? 'Cash doesn’t move with the share market, so a bigger cash share steadies the whole account.'
            : cash.share >= 0.05
              ? `Already ${pct(cash.share)} of your account is cash, which cushions the whole account`
              : `Cash is ${pct(cash.share)} of your account, so the account swings almost as much as your holdings`}
        </p>
      </div>
      <p className="risk-footnote">
        Examples worked out from this period’s data to show the trade off between risk and return. Past results don’t
        predict future ones, and this isn’t a recommendation.
      </p>
    </>
  )
}
