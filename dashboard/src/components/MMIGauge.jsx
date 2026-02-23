export default function MMIGauge({ mmi }) {
  if (!mmi) return <div className="text-gray-500">Loading...</div>
  const score = mmi.mmi_score || 0
  const signal = mmi.signal || ''
  const getColor = (s) => {
    if (s >= 75) return '#ef4444'
    if (s >= 55) return '#f97316'
    if (s >= 45) return '#eab308'
    if (s >= 25) return '#22c55e'
    return '#10b981'
  }
  const color = getColor(score)
  return (
    <div className="flex flex-col items-center">
      <div className="text-5xl font-bold" style={{ color }}>{score}</div>
      <div className="text-sm text-gray-400 mt-2">{signal}</div>
      <div className="w-full mt-6 space-y-2 text-sm">
        <div className="flex justify-between">
          <span className="text-gray-400">Fear & Greed</span>
          <span>{mmi.components?.sentiment?.fear_greed || '-'}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">30d Change</span>
          <span className={mmi.components?.historical?.price_change_30d >= 0 ? 'text-green-500' : 'text-red-500'}>
            {mmi.components?.historical?.price_change_30d?.toFixed(1)}%
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Volume Ratio</span>
          <span>{mmi.components?.onchain?.vol_ratio?.toFixed(2)}x</span>
        </div>
      </div>
    </div>
  )
}
