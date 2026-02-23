import { useState, useEffect } from 'react'
import { TrendingUp, TrendingDown, Activity, PieChart, BarChart3, RefreshCw, DollarSign, Unlock, Users } from 'lucide-react'

function App() {
  const [prices, setPrices] = useState([])
  const [mmi, setMmi] = useState(null)
  const [portfolio, setPortfolio] = useState(null)
  const [stats, setStats] = useState([])
  const [fundingRounds, setFundingRounds] = useState([])
  const [unlocks, setUnlocks] = useState([])
  const [vcOverlap, setVcOverlap] = useState(null)
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState('overview')

  const fetchData = async () => {
    try {
      setLoading(true)
      const [pricesRes, mmiRes, portfolioRes, statsRes, fundingRes, unlocksRes, overlapRes] = await Promise.all([
        fetch('/api/v1/market/prices?symbols=BTC,ETH,SOL,BNB,AVAX'),
        fetch('/api/v1/mmi/bitcoin'),
        fetch('/api/v1/portfolio/optimize', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ assets: ['BTC', 'ETH', 'SOL', 'BNB', 'AVAX'], strategy: 'hrp' })
        }),
        fetch('/api/v1/portfolio/stats?assets=BTC,ETH,SOL,BNB,AVAX'),
        fetch('/api/v1/vc/funding-rounds?limit=8'),
        fetch('/api/v1/vc/unlocks?days=30'),
        fetch('/api/v1/vc/overlap')
      ])
      const [pricesData, mmiData, portfolioData, statsData, fundingData, unlocksData, overlapData] = await Promise.all([
        pricesRes.json(), mmiRes.json(), portfolioRes.json(), statsRes.json(), fundingRes.json(), unlocksRes.json(), overlapRes.json()
      ])
      setPrices(pricesData.data || [])
      setMmi(mmiData)
      setPortfolio(portfolioData.result)
      setStats(statsData.data || [])
      setFundingRounds(fundingData.data || [])
      setUnlocks(unlocksData.data || [])
      setVcOverlap(overlapData.data)
    } catch (error) {
      console.error('Error:', error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 60000)
    return () => clearInterval(interval)
  }, [])

  const getMMIColor = (score) => {
    if (score >= 75) return 'text-red-500'
    if (score >= 55) return 'text-orange-500'
    if (score >= 45) return 'text-yellow-500'
    return 'text-green-500'
  }

  const formatAmount = (amount) => {
    if (!amount) return 'Undisclosed'
    if (amount >= 1e9) return `$${(amount / 1e9).toFixed(1)}B`
    if (amount >= 1e6) return `$${(amount / 1e6).toFixed(0)}M`
    return `$${(amount / 1e3).toFixed(0)}K`
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Header */}
      <div className="border-b border-gray-800 px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl flex items-center justify-center">
              <Activity className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-2xl font-bold">Looloomi AI</h1>
              <p className="text-sm text-gray-500">Institutional Portfolio Intelligence</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            {/* Tabs */}
            <div className="flex gap-2 bg-gray-900 rounded-lg p-1">
              <button 
                onClick={() => setActiveTab('overview')}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${activeTab === 'overview' ? 'bg-indigo-600 text-white' : 'text-gray-400 hover:text-white'}`}
              >
                Overview
              </button>
              <button 
                onClick={() => setActiveTab('vc')}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${activeTab === 'vc' ? 'bg-indigo-600 text-white' : 'text-gray-400 hover:text-white'}`}
              >
                VC Deal Flow
              </button>
            </div>
            <button onClick={fetchData} disabled={loading} className="p-2 rounded-lg bg-gray-800 hover:bg-gray-700">
              <RefreshCw className={loading ? 'w-5 h-5 animate-spin' : 'w-5 h-5'} />
            </button>
          </div>
        </div>
      </div>

      <div className="p-6">
        {/* Price Cards - Always visible */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-8">
          {prices.map((asset) => (
            <div key={asset.symbol} className="bg-gray-900 rounded-xl p-4 border border-gray-800">
              <div className="flex items-center justify-between mb-2">
                <span className="text-gray-400">{asset.symbol.replace('/USDT', '')}</span>
                {asset.change_24h >= 0 ? <TrendingUp className="w-4 h-4 text-green-500" /> : <TrendingDown className="w-4 h-4 text-red-500" />}
              </div>
              <div className="text-xl font-bold">${asset.price?.toLocaleString()}</div>
              <div className={asset.change_24h >= 0 ? 'text-green-500' : 'text-red-500'}>
                {asset.change_24h >= 0 ? '+' : ''}{asset.change_24h?.toFixed(2)}%
              </div>
            </div>
          ))}
        </div>

        {/* Overview Tab */}
        {activeTab === 'overview' && (
          <>
            <div className="grid md:grid-cols-3 gap-6 mb-8">
              {/* MMI */}
              <div className="bg-gray-900 rounded-xl p-6 border border-gray-800">
                <div className="flex items-center gap-2 mb-4">
                  <Activity className="w-5 h-5 text-indigo-500" />
                  <h2 className="font-semibold">MMI Score</h2>
                </div>
                {mmi && (
                  <div className="text-center">
                    <div className={`${getMMIColor(mmi.mmi_score)} text-5xl font-bold`}>{mmi.mmi_score}</div>
                    <div className="text-gray-400 mt-2">{mmi.signal}</div>
                  </div>
                )}
              </div>

              {/* Portfolio Allocation */}
              <div className="bg-gray-900 rounded-xl p-6 border border-gray-800">
                <div className="flex items-center gap-2 mb-4">
                  <PieChart className="w-5 h-5 text-indigo-500" />
                  <h2 className="font-semibold">HRP Allocation</h2>
                </div>
                {portfolio?.weights && (
                  <div className="space-y-3">
                    {Object.entries(portfolio.weights).sort((a, b) => b[1] - a[1]).map(([asset, weight]) => (
                      <div key={asset}>
                        <div className="flex justify-between text-sm mb-1"><span>{asset}</span><span>{(weight * 100).toFixed(1)}%</span></div>
                        <div className="h-2 bg-gray-800 rounded-full"><div className="h-full bg-indigo-500 rounded-full" style={{ width: `${weight * 100}%` }} /></div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Metrics */}
              <div className="bg-gray-900 rounded-xl p-6 border border-gray-800">
                <div className="flex items-center gap-2 mb-4">
                  <BarChart3 className="w-5 h-5 text-indigo-500" />
                  <h2 className="font-semibold">Portfolio Metrics</h2>
                </div>
                {portfolio && (
                  <div className="space-y-4">
                    <div>
                      <div className="text-sm text-gray-400">Expected Return</div>
                      <div className={`${portfolio.expected_annual_return >= 0 ? 'text-green-500' : 'text-red-500'} text-2xl font-bold`}>{portfolio.expected_annual_return?.toFixed(1)}%</div>
                    </div>
                    <div>
                      <div className="text-sm text-gray-400">Volatility</div>
                      <div className="text-2xl font-bold text-yellow-500">{portfolio.annual_volatility?.toFixed(1)}%</div>
                    </div>
                    <div>
                      <div className="text-sm text-gray-400">Sharpe Ratio</div>
                      <div className={`${portfolio.sharpe_ratio >= 0 ? 'text-green-500' : 'text-red-500'} text-2xl font-bold`}>{portfolio.sharpe_ratio?.toFixed(2)}</div>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Asset Table */}
            <div className="bg-gray-900 rounded-xl p-6 border border-gray-800">
              <h2 className="font-semibold mb-4">Asset Performance (90 Days)</h2>
              <table className="w-full">
                <thead>
                  <tr className="text-left text-gray-400 border-b border-gray-800">
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
                      <td className="py-3 text-right">${asset.price?.toLocaleString()}</td>
                      <td className={`${asset.return_90d >= 0 ? 'text-green-500' : 'text-red-500'} py-3 text-right`}>{asset.return_90d?.toFixed(1)}%</td>
                      <td className="py-3 text-right text-yellow-500">{asset.volatility?.toFixed(1)}%</td>
                      <td className={`${asset.sharpe >= 0 ? 'text-green-500' : 'text-red-500'} py-3 text-right`}>{asset.sharpe?.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {/* VC Deal Flow Tab */}
        {activeTab === 'vc' && (
          <div className="grid md:grid-cols-2 gap-6">
            {/* Recent Funding Rounds */}
            <div className="bg-gray-900 rounded-xl p-6 border border-gray-800">
              <div className="flex items-center gap-2 mb-4">
                <DollarSign className="w-5 h-5 text-green-500" />
                <h2 className="font-semibold">Recent Funding Rounds</h2>
              </div>
              <div className="space-y-3">
                {fundingRounds.map((round, i) => (
                  <div key={i} className="flex items-center justify-between py-2 border-b border-gray-800/50">
                    <div>
                      <div className="font-medium">{round.project}</div>
                      <div className="text-sm text-gray-400">{round.round_type} · {round.category}</div>
                    </div>
                    <div className="text-right">
                      <div className="font-bold text-green-500">{formatAmount(round.amount)}</div>
                      <div className="text-xs text-gray-500">{round.investors?.slice(0, 2).join(', ')}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Token Unlocks */}
            <div className="bg-gray-900 rounded-xl p-6 border border-gray-800">
              <div className="flex items-center gap-2 mb-4">
                <Unlock className="w-5 h-5 text-yellow-500" />
                <h2 className="font-semibold">Upcoming Token Unlocks</h2>
              </div>
              <div className="space-y-3">
                {unlocks.map((unlock, i) => (
                  <div key={i} className="flex items-center justify-between py-2 border-b border-gray-800/50">
                    <div>
                      <div className="font-medium">{unlock.protocol}</div>
                      <div className="text-sm text-gray-400">{unlock.type}</div>
                    </div>
                    <div className="text-right">
                      <div className="font-bold text-yellow-500">{formatAmount(unlock.amount_usd)}</div>
                      <div className="text-xs text-gray-500">{unlock.days_until} days</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* VC Overlap */}
            <div className="bg-gray-900 rounded-xl p-6 border border-gray-800 md:col-span-2">
              <div className="flex items-center gap-2 mb-4">
                <Users className="w-5 h-5 text-indigo-500" />
                <h2 className="font-semibold">High VC Overlap (Strong Signal)</h2>
              </div>
              <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
                {vcOverlap?.high_overlap?.map((item, i) => (
                  <div key={i} className="bg-gray-800/50 rounded-lg p-4">
                    <div className="font-semibold text-lg mb-2">{item.project}</div>
                    <div className="flex flex-wrap gap-1">
                      {item.vcs.map((vc, j) => (
                        <span key={j} className="px-2 py-1 bg-indigo-500/20 text-indigo-400 text-xs rounded-full">{vc}</span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="border-t border-gray-800 px-6 py-4 text-center text-gray-500 text-sm">
        Looloomi AI 2026 | Institutional-Grade Crypto Intelligence
      </div>
    </div>
  )
}

export default App