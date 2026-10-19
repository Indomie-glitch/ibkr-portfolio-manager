import { formatMoney } from '../../lib/format.js'
import { currencySentence, pct } from '../../lib/riskFormat.js'

// RSK 05 Currency effect (Figma 106:1075): for the largest US holding, its price return in USD, the
// exchange rate's effect and the return in AUD; then the total currency effect on all US holdings.
export default function CurrencyPanel({ section, period }) {
  const top = section.holdings[0]
  if (!top) {
    return <p className="risk-panel-note">You have no US holdings, so exchange rates don’t change your returns.</p>
  }
  const sign = (v) => (v > 0 ? 'gain' : v < 0 ? 'loss' : '')
  const rows = [
    { label: `${top.name}’s price, in USD`, value: top.price_return, tone: sign(top.price_return) },
    { label: 'Exchange rate, AUD vs USD', value: top.fx_return, tone: sign(top.fx_return) },
    { label: 'Your return, in AUD', value: top.aud_return, tone: 'plain' },
  ]
  // Bars are drawn against the largest move rounded up to the next 10%
  const scale = Math.max(0.1, Math.ceil(Math.max(...rows.map((r) => Math.abs(r.value ?? 0))) * 10) / 10)
  const total = section.total_effect_aud
  return (
    <>
      {rows.map((r) => (
        <div className="risk-currency-row" key={r.label}>
          <div className="risk-currency-line">
            <span className="risk-currency-label">{r.label}</span>
            <span className={`risk-currency-value ${r.tone}`}>{pct(r.value, { signed: true })}</span>
          </div>
          <span className="risk-bar" aria-hidden="true">
            <span className={`risk-bar-fill ${r.tone}`} style={{ width: `${(Math.abs(r.value ?? 0) / scale) * 100}%` }} />
          </span>
        </div>
      ))}
      <div className="risk-total">
        <p className="risk-small-caps tight">Total currency effect · Portfolio</p>
        <p className={`risk-total-value ${sign(total)}`}>{formatMoney(total, 'AUD', { decimals: 0, signed: true })}</p>
        <p className="risk-total-note">{currencySentence(section, period)}</p>
      </div>
    </>
  )
}
