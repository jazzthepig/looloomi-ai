import { useState, useEffect, useCallback } from "react";
import { T, FONTS } from "../tokens";

const API_BASE = "/api/v1";

/* ─── CSS ────────────────────────────────────────────────────────────── */
const CSS = `
  @keyframes breathe  { 0%,100%{opacity:.28;transform:scale(1) translateY(0)} 50%{opacity:.44;transform:scale(1.06) translateY(-12px)} }
  @keyframes breathe2 { 0%,100%{opacity:.16;transform:scale(1)} 50%{opacity:.30;transform:scale(1.08) translateX(10px)} }
  @keyframes fadeUp   { from{opacity:0;transform:translateY(14px)} to{opacity:1;transform:translateY(0)} }
  @keyframes pulse    { 0%,100%{opacity:1} 50%{opacity:.35} }
  @keyframes shimmer  { 0%{background-position:-400px 0} 100%{background-position:400px 0} }
  @keyframes spin    { to{transform:rotate(360deg)} }

.fade-up  { animation: fadeUp .4s cubic-bezier(.16,1,.3,1) forwards; }
  .pulse-dot { animation: pulse 2.2s ease-in-out infinite; }
  .spinner { animation: spin 1s linear infinite; }
  .sk { background:linear-gradient(90deg,rgba(14,30,56,0.8) 30%,rgba(18,38,72,0.9) 50%,rgba(14,30,56,0.8) 70%);background-size:400px 100%;animation:shimmer 1.8s ease infinite;border-radius:4px;display:inline-block; }

  .quant-card { background:rgba(7,26,74,0.55);border:1px solid rgba(37,99,235,0.14);border-radius:10px;backdrop-filter:blur(24px);box-shadow:0 1px 0 rgba(255,255,255,0.04) inset,0 8px 40px rgba(0,0,0,0.36); }

  .badge { display:inline-flex;align-items:center;padding:2px 7px;border-radius:3px;font-size:10px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;font-family:'Syne',sans-serif; }
  .badge-live { background:rgba(0,232,122,.12);color:#00E87A;border:1px solid rgba(0,232,122,.25); }
  .badge-stale { background:rgba(245,158,11,.12);color:#F59E0B;border:1px solid rgba(245,158,11,.25); }
  .badge-trade-long { background:rgba(0,232,122,.10);color:#00E87A;border:1px solid rgba(0,232,122,.2); }
  .badge-trade-short { background:rgba(255,61,90,.10);color:#FF3D5A;border:1px solid rgba(255,61,90,.2); }

  .stat-card { background:rgba(15,40,96,0.60);border:1px solid rgba(99,102,241,0.16);border-radius:8px;backdrop-filter:blur(12px);padding:16px 20px;text-align:center;transition:border-color .18s ease; }
  .stat-card:hover { border-color:rgba(99,102,241,0.28); }
  .stat-label { font-size:10px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:rgba(199,210,254,0.45);margin-bottom:6px;font-family:'Syne',sans-serif; }
  .stat-value { font-size:28px;font-weight:700;font-family:'JetBrains Mono',monospace;color:#f0f4ff; }
  .stat-sub { font-size:11px;color:rgba(199,210,254,0.45);margin-top:4px;font-family:'JetBrains Mono',monospace; }

  @media (max-width: 768px) {
    .mobile-stack { flex-direction: column !important; }
    .mobile-2col { grid-template-columns: 1fr 1fr !important; }
    .mobile-full { width: 100% !important; }
    .mobile-stat-grid { grid-template-columns: 1fr 1fr !important; }
  }
`;

/* ─── Helpers ───────────────────────────────────────────────────────── */
const fmt = (n, decimals = 2) => (typeof n === "number" ? n.toFixed(decimals) : "—");
const fmtPct = (n) => (typeof n === "number" ? `${n >= 0 ? "+" : ""}${n.toFixed(2)}%` : "—");
const fmtAbs = (n) => (typeof n === "number" ? `${n >= 0 ? "+" : ""}$${Math.abs(n).toFixed(2)}` : "—");
const fmtTime = (ts) => {
  if (!ts) return "—";
  const d = new Date(ts.replace("Z", "+00:00"));
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
};

/* ─── API ───────────────────────────────────────────────────────────── */
async function fetchQuantData() {
  const [status, trades, backtest] = await Promise.all([
    fetch(`${API_BASE}/quant/status`).then(r => r.ok ? r.json() : null).catch(() => null),
    fetch(`${API_BASE}/quant/trades?limit=30`).then(r => r.ok ? r.json() : null).catch(() => null),
    fetch(`${API_BASE}/quant/backtest`).then(r => r.ok ? r.json() : null).catch(() => null),
  ]);
  return { status, trades, backtest };
}

/* ─── Equity Card ───────────────────────────────────────────────────── */
function EquityCard({ equity, starting, dailyPnl, stale, updated }) {
  const hasEquity = equity != null && !isNaN(equity);
  const totalPnl = (hasEquity && starting > 0) ? ((equity - starting) / starting * 100) : null;
  const pnlColor = (totalPnl == null || totalPnl >= 0) ? T.green : T.red;
  const dailyColor = typeof dailyPnl === "number" ? (dailyPnl >= 0 ? T.green : T.red) : T.t3;

  return (
    <div className="quant-card fade-up" style={{ padding: "20px 24px", marginBottom: 16 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, letterSpacing: ".1em", color: T.secondary, textTransform: "uppercase" }}>Dry Run · BTC/ETH/SOL</span>
          <span className={`badge ${stale ? "badge-stale" : "badge-live"}`}>
            {stale ? "STALE" : "LIVE"}
          </span>
        </div>
        {updated && (
          <span style={{ fontSize: 10, fontFamily: FONTS.mono, color: T.t3 }}>
            {fmtTime(updated)}
          </span>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 16 }}>
        <div className="stat-card">
          <div className="stat-label">Equity</div>
          <div className="stat-value" style={{ color: equity >= starting ? T.green : T.red }}>
            ${typeof equity === "number" ? equity.toFixed(2) : "—"}
          </div>
          <div className="stat-sub" style={{ color: pnlColor }}>{fmtPct(totalPnl)} total</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Daily P&L</div>
          <div className="stat-value" style={{ fontSize: 22, color: dailyColor }}>
            {typeof dailyPnl === "number" ? fmtPct(dailyPnl) : "—"}
          </div>
          <div className="stat-sub" style={{ color: dailyColor }}>
            {typeof dailyPnl === "number" ? fmtAbs(dailyPnl * starting / 100) : ""}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Starting</div>
          <div className="stat-value" style={{ fontSize: 22, color: T.t2 }}>
            ${starting > 0 ? starting.toFixed(2) : "—"}
          </div>
          <div className="stat-sub">USDT paper</div>
        </div>
      </div>

      {/* Equity progress bar */}
      {starting > 0 && totalPnl != null && (
        <div style={{ marginTop: 8 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
            <span style={{ fontSize: 10, color: T.t3, fontFamily: FONTS.mono }}>P&L</span>
            <span style={{ fontSize: 10, color: pnlColor, fontFamily: FONTS.mono }}>{fmtPct(totalPnl)}</span>
          </div>
          <div style={{ height: 4, background: "rgba(255,255,255,0.06)", borderRadius: 2 }}>
            <div style={{
              height: "100%",
              width: `${Math.min(100, Math.max(0, 50 + totalPnl))}%`,
              background: totalPnl >= 0
                ? `linear-gradient(90deg, ${T.green}40, ${T.green})`
                : `linear-gradient(90deg, ${T.red}, ${T.red}40)`,
              borderRadius: 2,
              transition: "width .5s ease",
            }} />
          </div>
        </div>
      )}
    </div>
  );
}

/* ─── Open Trade Row ────────────────────────────────────────────────── */
function OpenTradeRow({ trade }) {
  const pnl = trade.pnl_abs ?? 0;
  const pnlPct = trade.pnl_pct ?? 0;
  const isLong = !trade.is_short;
  const pnlColor = pnl >= 0 ? T.green : T.red;

  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "1fr 80px 80px 80px 60px",
      gap: 8,
      padding: "10px 16px",
      borderBottom: `1px solid ${T.border}`,
      alignItems: "center",
    }}>
      <div>
        <span style={{ fontFamily: FONTS.display, fontSize: 13, fontWeight: 600, color: T.t1 }}>
          {trade.pair?.replace("USDT", "") || "—"}
        </span>
        <div style={{ fontSize: 10, color: T.t3, fontFamily: FONTS.mono, marginTop: 2 }}>
          {trade.amount ? `${parseFloat(trade.amount).toFixed(4)}` : "—"}
        </div>
      </div>
      <div style={{ textAlign: "right" }}>
        <div style={{ fontSize: 11, fontFamily: FONTS.mono, color: T.t2 }}>{trade.entry_price ? `$${parseFloat(trade.entry_price).toFixed(2)}` : "—"}</div>
        <div style={{ fontSize: 9, color: T.t3, fontFamily: FONTS.mono }}>entry</div>
      </div>
      <div style={{ textAlign: "right" }}>
        <div style={{ fontSize: 11, fontFamily: FONTS.mono, color: T.t2 }}>{trade.current_price ? `$${parseFloat(trade.current_price).toFixed(2)}` : "—"}</div>
        <div style={{ fontSize: 9, color: T.t3, fontFamily: FONTS.mono }}>current</div>
      </div>
      <div style={{ textAlign: "right" }}>
        <div style={{ fontSize: 11, fontFamily: FONTS.mono, color: pnlColor }}>{fmtPct(pnlPct * 100)}</div>
        <div style={{ fontSize: 9, color: T.t3, fontFamily: FONTS.mono }}>{fmtAbs(pnl)}</div>
      </div>
      <div>
        <span className={`badge ${isLong ? "badge-trade-long" : "badge-trade-short"}`}>
          {isLong ? "LONG" : "SHORT"}
        </span>
      </div>
    </div>
  );
}

/* ─── Backtest Card ─────────────────────────────────────────────────── */
function BacktestCard({ data }) {
  if (!data) return null;
  const { spot, leveraged_3x, smc_enhanced, key_findings, strategy_upgrade_direction } = data;
  const lev = leveraged_3x?.summary;

  return (
    <div className="quant-card fade-up" style={{ marginBottom: 16 }}>
      <div style={{
        padding: "12px 16px",
        borderBottom: `1px solid ${T.border}`,
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <span style={{ fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, letterSpacing: ".08em", color: T.secondary, textTransform: "uppercase" }}>
          Backtest · 14 Months
        </span>
        <span style={{ fontSize: 9, fontFamily: FONTS.mono, color: T.t3 }}>{data.strategy}</span>
      </div>

      {/* Key metrics row */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 0 }}>
        <div style={{ padding: "14px 16px", borderRight: `1px solid ${T.border}` }}>
          <div className="stat-label">Total Return</div>
          <div className="stat-value" style={{ fontSize: 22, color: lev && lev.total_return >= 0 ? T.green : T.red }}>
            {lev ? `+${lev.total_return}%` : "—"}
          </div>
          <div className="stat-sub">3× leveraged</div>
        </div>
        <div style={{ padding: "14px 16px", borderRight: `1px solid ${T.border}` }}>
          <div className="stat-label">Annualized</div>
          <div className="stat-value" style={{ fontSize: 22, color: T.green }}>{lev?.annualized ? `${lev.annualized}%` : "—"}</div>
          <div className="stat-sub">CAGR</div>
        </div>
        <div style={{ padding: "14px 16px", borderRight: `1px solid ${T.border}` }}>
          <div className="stat-label">Win Rate</div>
          <div className="stat-value" style={{ fontSize: 22, color: T.green }}>{spot?.summary?.win_rate ?? "—"}%</div>
          <div className="stat-sub">{spot?.summary?.trades} trades</div>
        </div>
        <div style={{ padding: "14px 16px" }}>
          <div className="stat-label">Median Return</div>
          <div className="stat-value" style={{ fontSize: 22, color: T.cyan }}>{spot?.summary?.median_return ? `${spot.summary.median_return}%` : "—"}</div>
          <div className="stat-sub">per trade</div>
        </div>
      </div>

      {/* Per-asset performance */}
      {lev?.by_asset && (
        <div style={{ padding: "10px 16px", borderTop: `1px solid ${T.border}` }}>
          <div style={{ fontSize: 9, fontWeight: 600, letterSpacing: ".08em", textTransform: "uppercase", color: T.t3, marginBottom: 8, fontFamily: FONTS.display }}>By Asset</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }}>
            {lev.by_asset.map(a => (
              <div key={a.asset} style={{ background: "rgba(255,255,255,0.03)", borderRadius: 6, padding: "8px 10px" }}>
                <div style={{ fontFamily: FONTS.display, fontSize: 11, fontWeight: 600, color: T.t1 }}>{a.asset}</div>
                <div style={{ fontFamily: FONTS.mono, fontSize: 12, color: a.return >= 0 ? T.green : T.red, marginTop: 2 }}>
                  {a.return >= 0 ? "+" : ""}{a.return}%
                </div>
                <div style={{ fontSize: 9, color: T.t3, marginTop: 2 }}>{a.trades} trades · {a.win_rate}% WR</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Key findings */}
      {key_findings && key_findings.length > 0 && (
        <div style={{ padding: "10px 16px", borderTop: `1px solid ${T.border}` }}>
          <div style={{ fontSize: 9, fontWeight: 600, letterSpacing: ".08em", textTransform: "uppercase", color: T.t3, marginBottom: 6, fontFamily: FONTS.display }}>Key Findings</div>
          {key_findings.map((f, i) => (
            <div key={i} style={{ fontSize: 10, fontFamily: FONTS.mono, color: T.t2, marginBottom: 3, display: "flex", gap: 6 }}>
              <span style={{ color: T.primary }}>›</span>{f}
            </div>
          ))}
        </div>
      )}

      {/* SMC Enhanced */}
      {smc_enhanced && (
        <div style={{ padding: "10px 16px", borderTop: `1px solid ${T.border}`, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <span style={{ fontSize: 10, fontFamily: FONTS.display, fontWeight: 600, color: T.cyan }}>SMC Enhanced</span>
            <span style={{ fontSize: 9, fontFamily: FONTS.mono, color: T.t3, marginLeft: 8 }}>
              {smc_enhanced.summary.trades} trades · {smc_enhanced.summary.win_rate}% WR · median {smc_enhanced.summary.median_return}%
            </span>
          </div>
          <div style={{ fontSize: 9, fontFamily: FONTS.mono, color: T.green }}>{smc_enhanced.vs_original?.avg_return_improvement} avg return</div>
        </div>
      )}

      {/* Status badge */}
      <div style={{ padding: "8px 16px", borderTop: `1px solid ${T.border}`, display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{
          fontSize: 9, fontFamily: FONTS.mono, fontWeight: 600,
          padding: "2px 7px", borderRadius: 3,
          background: "rgba(0,232,122,.10)", color: T.green,
          border: `1px solid rgba(0,232,122,.2)`,
        }}>{data.status}</span>
        <span style={{ fontSize: 9, fontFamily: FONTS.mono, color: T.t3 }}>{data.description}</span>
      </div>
    </div>
  );
}


function TradeHistoryRow({ trade }) {
  const pnl = trade.profit_abs ?? 0;
  const pnlPct = trade.profit_ratio ?? 0;
  const pnlColor = pnl >= 0 ? T.green : T.red;
  const exitTime = trade.exit_date || trade.close_date || "";

  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "1fr 80px 80px 70px",
      gap: 8,
      padding: "8px 16px",
      borderBottom: `1px solid ${T.border}`,
      alignItems: "center",
    }}>
      <div>
        <span style={{ fontFamily: FONTS.display, fontSize: 12, fontWeight: 600, color: T.t1 }}>
          {trade.pair?.replace("USDT", "").replace(":USDT", "") || "—"}
        </span>
        <div style={{ fontSize: 9, color: T.t3, fontFamily: FONTS.mono, marginTop: 2 }}>
          {exitTime ? fmtTime(exitTime) : "open"}
        </div>
      </div>
      <div style={{ textAlign: "right" }}>
        <div style={{ fontSize: 11, fontFamily: FONTS.mono, color: T.t2 }}>
          {trade.open_rate ? `$${parseFloat(trade.open_rate).toFixed(0)}` : "—"}
        </div>
        <div style={{ fontSize: 9, color: T.t3, fontFamily: FONTS.mono }}>entry</div>
      </div>
      <div style={{ textAlign: "right" }}>
        <div style={{ fontSize: 11, fontFamily: FONTS.mono, color: T.t2 }}>
          {trade.close_rate ? `$${parseFloat(trade.close_rate).toFixed(0)}` : "—"}
        </div>
        <div style={{ fontSize: 9, color: T.t3, fontFamily: FONTS.mono }}>exit</div>
      </div>
      <div style={{ textAlign: "right" }}>
        <div style={{ fontSize: 11, fontFamily: FONTS.mono, color: pnlColor }}>{fmtPct(pnlPct * 100)}</div>
        <div style={{ fontSize: 9, color: T.t3, fontFamily: FONTS.mono }}>{fmtAbs(pnl)}</div>
      </div>
    </div>
  );
}

/* ─── Skeleton ──────────────────────────────────────────────────────── */
function SkeletonCard() {
  return (
    <div className="quant-card" style={{ padding: "20px 24px", marginBottom: 16 }}>
      <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
        <div className="sk" style={{ height: 18, width: 120 }} />
        <div className="sk" style={{ height: 18, width: 60 }} />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
        {[0, 1, 2].map(i => (
          <div key={i} style={{ padding: 16, background: "rgba(255,255,255,0.03)", borderRadius: 8 }}>
            <div className="sk" style={{ height: 10, width: 60, marginBottom: 8 }} />
            <div className="sk" style={{ height: 28, width: 100 }} />
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Main Component ────────────────────────────────────────────────── */
export default function QuantMonitor() {
  const [data, setData] = useState({ status: null, trades: null, backtest: null });
  const [loading, setLoading] = useState(true);
  const [stale, setStale] = useState(false);

  const fetchData = useCallback(async () => {
    const { status, trades, backtest } = await fetchQuantData();
    setData({ status, trades, backtest });
    setStale(status?._stale ?? false);
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30_000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const { status, trades } = data;
  const openTrades = status?.open_trades || [];
  const closedTrades = (trades?.trades || []).slice(0, 30);

  return (
    <div style={{ minHeight: "100vh", background: T.void, color: T.t1, padding: "0 0 48px" }}>
      <style>{CSS}</style>

      {/* Ambient background */}
      <div className="turrell-wrap">
        <div className="t-orb t-orb-1" />
        <div className="t-orb t-orb-2" />
        <div className="t-orb t-orb-3" />
      </div>

      {/* Header */}
      <div style={{
        position: "sticky", top: 0, zIndex: 10,
        background: "rgba(3,5,8,.88)", backdropFilter: "blur(16px)",
        borderBottom: `1px solid ${T.border}`,
        padding: "12px 20px",
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontFamily: FONTS.display, fontSize: 14, fontWeight: 700, letterSpacing: ".08em", color: T.primary }}>
            QUANT MONITOR
          </span>
          <span style={{
            fontSize: 9, fontFamily: FONTS.mono, fontWeight: 600,
            padding: "2px 7px", borderRadius: 3,
            background: "rgba(0,232,122,.10)", color: T.green,
            border: `1px solid rgba(0,232,122,.2)`,
            letterSpacing: ".08em",
          }}>DRY RUN</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ width: 6, height: 6, borderRadius: "50%", background: stale ? T.amber : T.green }} className={stale ? "" : "pulse-dot"} />
          <span style={{ fontSize: 10, color: stale ? T.amber : T.green, fontFamily: FONTS.mono }}>
            {stale ? "STALE" : "CONNECTED"}
          </span>
          <button
            onClick={fetchData}
            style={{
              background: "transparent", border: `1px solid ${T.border}`,
              borderRadius: 5, padding: "4px 8px", cursor: "pointer",
              color: T.t3, display: "flex", alignItems: "center",
            }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={loading ? "spinner" : ""}>
              <path d="M23 4v6h-6M1 20v-6h6M20.49 9A9 9 0 0 0 5.64 5.64L1 10M23 14l-4.64 4.36A9 9 0 0 1 3.51 15"/>
            </svg>
          </button>
        </div>
      </div>

      {/* Content */}
      <div style={{ maxWidth: 900, margin: "0 auto", padding: "20px 16px" }}>

        {/* Equity + Stats */}
        {loading ? <SkeletonCard /> : (
          <EquityCard
            equity={status?.balance?.equity}
            starting={status?.balance?.starting || 10000}
            dailyPnl={status?.daily_pnl}
            stale={stale}
            updated={status?.updated}
          />
        )}

        {/* Backtest Results */}
        {!loading && <BacktestCard data={data.backtest} />}

        {/* Open Trades */}
        <div className="quant-card fade-up" style={{ marginBottom: 16 }}>
          <div style={{
            padding: "12px 16px",
            borderBottom: `1px solid ${T.border}`,
            display: "flex", alignItems: "center", justifyContent: "space-between",
          }}>
            <span style={{ fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, letterSpacing: ".08em", color: T.secondary, textTransform: "uppercase" }}>
              Open Positions
            </span>
            <span style={{ fontSize: 10, fontFamily: FONTS.mono, color: T.t3 }}>{openTrades.length} active</span>
          </div>

          {openTrades.length === 0 ? (
            <div style={{ padding: "24px", textAlign: "center", color: T.t3, fontSize: 12, fontFamily: FONTS.mono }}>
              No open positions
            </div>
          ) : (
            <div>
              {/* Header */}
              <div style={{
                display: "grid",
                gridTemplateColumns: "1fr 80px 80px 80px 60px",
                gap: 8,
                padding: "6px 16px",
                borderBottom: `1px solid ${T.border}`,
              }}>
                {["Pair", "Entry", "Current", "P&L", "Side"].map(h => (
                  <div key={h} style={{ fontSize: 9, fontWeight: 600, letterSpacing: ".08em", textTransform: "uppercase", color: T.t3, fontFamily: FONTS.display, textAlign: h === "Pair" ? "left" : "right" }}>{h}</div>
                ))}
              </div>
              {openTrades.map((t, i) => <OpenTradeRow key={t.trade_id || i} trade={t} />)}
            </div>
          )}
        </div>

        {/* Trade History */}
        <div className="quant-card fade-up">
          <div style={{
            padding: "12px 16px",
            borderBottom: `1px solid ${T.border}`,
            display: "flex", alignItems: "center", justifyContent: "space-between",
          }}>
            <span style={{ fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, letterSpacing: ".08em", color: T.secondary, textTransform: "uppercase" }}>
              Trade History
            </span>
            <span style={{ fontSize: 10, fontFamily: FONTS.mono, color: T.t3 }}>{closedTrades.length} recent</span>
          </div>

          {closedTrades.length === 0 ? (
            <div style={{ padding: "24px", textAlign: "center", color: T.t3, fontSize: 12, fontFamily: FONTS.mono }}>
              No closed trades yet
            </div>
          ) : (
            <div>
              {/* Header */}
              <div style={{
                display: "grid",
                gridTemplateColumns: "1fr 80px 80px 70px",
                gap: 8,
                padding: "6px 16px",
                borderBottom: `1px solid ${T.border}`,
              }}>
                {["Pair", "Entry", "Exit", "P&L"].map(h => (
                  <div key={h} style={{ fontSize: 9, fontWeight: 600, letterSpacing: ".08em", textTransform: "uppercase", color: T.t3, fontFamily: FONTS.display, textAlign: h === "Pair" ? "left" : "right" }}>{h}</div>
                ))}
              </div>
              {closedTrades.map((t, i) => <TradeHistoryRow key={t.trade_id || i} trade={t} />)}
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{ marginTop: 24, textAlign: "center", color: T.t3, fontSize: 10, fontFamily: FONTS.mono, opacity: 0.5 }}>
          CometCloud Quant · Dry Run · Paper Trading · 10,000 USDT
        </div>
      </div>
    </div>
  );
}
