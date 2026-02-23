export default function PortfolioAllocation({ portfolio }) {
  if (!portfolio?.weights) return <div className="text-gray-500">Loading...</div>

  const colors = {
    BTC: '#f7931a',
    ETH: '#627eea',
    SOL: '#00ffa3',
    BNB: '#f3ba2f',
    AVAX: '#e84142'
  }

  const weights = Object.entries(portfolio.weights)
    .sort((a, b) => b[1] - a[1])

  return (
    <div className="space-y-3">
      {weights.map(([asset, weight]) => (
        <div key={asset}>
          <div className="flex justify-between text-sm mb-1">
            <span className="flex items-center gap-2">
              <div 
                className="w-3 h-3 rounded-full" 
                style={{ backgroundColor: colors[asset] || '#6366f1' }}
              />
              {asset}
            </span>
            <span className="font-mono">{(weight * 100).toFixed(1)}%</span>
          </div>
          <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
            <div 
              className="h-full rounded-full transition-all duration-500"
              style={{ 
                width: `${weight * 100}%`,
                backgroundColor: colors[asset] || '#6366f1'
              }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}
