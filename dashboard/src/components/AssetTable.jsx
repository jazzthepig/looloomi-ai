import { TrendingUp, TrendingDown } from 'lucide-react'

export default function AssetTable({ stats }) {
  if (!stats?.length) return <div className="text-gray-500">Loading...</div>

  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="text-left text-sm text-gray-400 border-b border-gray-800">
            <th className="pb-3">Asset</th>
            <th className="pb-3 text-right">Price</th>
            <th className="pb-3 text-right">90d Return</th>
            <th className="pb-3 text-right">Volatility</th>
            <th className="pb-3 text-right">Sharpe</th>
          </tr>
        </thead>
        <tbody>
          {stats.map((asset) => (
            <tr key={asset.asset} className="border-b border-gray-800/50">
              <td className="py-3 font-medium">{asset.asset}</td>
              <td className="py-3 text-right font-mono">
                ${asset.price?.toLocaleString()}
              </td>
              <td className={`py-3 text-right ${asset.return_90d >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                <span className="flex items-center justify-end gap-1">
                  {asset.return_90d >= 0 ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                  {asset.return_90d?.toFixed(1)}%
                </span>
              </td>
              <td className="py-3 text-right text-yellow-500">
                {asset.volatility?.toFixed(1)}%
              </td>
              <td className={`py-3 text-right ${asset.sharpe >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                {asset.sharpe?.toFixed(2)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
