import { useEffect, useRef, useState } from 'react'
import { createChart } from 'lightweight-charts'

export default function PriceChart({ symbol = 'BTC' }) {
  const chartContainerRef = useRef()
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!chartContainerRef.current) return

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: 'solid', color: 'transparent' },
        textColor: '#a0a0a0',
      },
      grid: {
        vertLines: { color: '#1f1f2e' },
        horzLines: { color: '#1f1f2e' },
      },
      width: chartContainerRef.current.clientWidth,
      height: 300,
      timeScale: {
        borderColor: '#1f1f2e',
      },
      rightPriceScale: {
        borderColor: '#1f1f2e',
      },
    })

    const candlestickSeries = chart.addCandlestickSeries({
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderUpColor: '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    })

    // Fetch OHLCV data
    fetch(`/api/v1/market/ohlcv/${symbol}?timeframe=1d&limit=90`)
      .then(res => res.json())
      .then(data => {
        if (data.data) {
          const chartData = data.data.map(d => ({
            time: d.timestamp.split('T')[0],
            open: d.open,
            high: d.high,
            low: d.low,
            close: d.close,
          }))
          candlestickSeries.setData(chartData)
          setLoading(false)
        }
      })
      .catch(err => {
        console.error('Chart error:', err)
        setLoading(false)
      })

    const handleResize = () => {
      chart.applyOptions({ width: chartContainerRef.current.clientWidth })
    }

    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
    }
  }, [symbol])

  return (
    <div className="relative">
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-[#1a1a24]">
          <div className="text-gray-500">Loading chart...</div>
        </div>
      )}
      <div ref={chartContainerRef} />
    </div>
  )
}
