export function formatMoney(value, currency) {
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency,
  }).format(value)
}

export function formatNumber(value, decimals = 2) {
  return new Intl.NumberFormat(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value)
}
