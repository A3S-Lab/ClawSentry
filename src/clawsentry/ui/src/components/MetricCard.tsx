interface MetricCardProps {
  label: string
  value: string | number
  color?: string
}

export default function MetricCard({ label, value, color }: MetricCardProps) {
  return (
    <div className="card metric-card">
      <div className="card-header">{label}</div>
      <div className="metric-value" style={color ? { color } : undefined}>
        {value}
      </div>
    </div>
  )
}
