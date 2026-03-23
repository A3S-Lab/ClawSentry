interface SkeletonCardProps {
  rows?: number
  height?: number
}

export default function SkeletonCard({ rows = 3, height }: SkeletonCardProps) {
  return (
    <div className="card" style={height ? { height } : undefined}>
      <div className="skeleton skeleton-text-sm" style={{ width: '40%', marginBottom: 12 }} />
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton skeleton-text" style={{ width: `${70 + (i % 3) * 10}%`, marginBottom: 8 }} />
      ))}
    </div>
  )
}
