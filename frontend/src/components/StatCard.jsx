function StatCard({ label, value, caption }) {
  return (
    <div className="stat-card">
      <p className="stat-card-label">{label}</p>
      <p className="stat-card-value num">{value}</p>
      <p className="stat-card-caption">{caption}</p>
    </div>
  )
}

export default StatCard
