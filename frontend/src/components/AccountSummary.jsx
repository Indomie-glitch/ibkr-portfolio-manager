import { formatMoney } from '../format.js'

const FIELDS = [
  { key: 'net_liquidation', label: 'Net liquidation' },
  { key: 'cash', label: 'Cash' },
  { key: 'positions_value', label: 'Positions value' },
  { key: 'buying_power', label: 'Buying power' },
]

function AccountSummary({ account }) {
  return (
    <section className="summary">
      {FIELDS.map(({ key, label }) => (
        <div className="card" key={key}>
          <div className="card-label">{label}</div>
          <div className="card-value">
            {account[key] === undefined
              ? '—'
              : formatMoney(account[key], account.currency)}
          </div>
        </div>
      ))}
    </section>
  )
}

export default AccountSummary
