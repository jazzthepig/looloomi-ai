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
    <div className="fade-up" style={{
      paddingBottom: 24, marginBottom: 24,
      borderBottom: `1px solid rgba(37,99,235,0.08)`,
      position: "relative",
    }}>
      {/* Ambient glow */}
      <div style={{
        position: "absolute", top: -16, left: -32, width: "40%", bottom: 0,
        background: `radial-gradient(ellipse 80% 100% at 0% 50%, ${pnlColor}08, transparent 75%)`,
        pointerEvents: "none",
      }} />

      <div style={{ display: "flex", alignItems: "flex-end", gap: 0, flexWrap: "wrap", position: "relative" }}>
        {/* Equity */}
        <div style={{ paddingRight: 36, paddingBottom: 4 }}>
          <div style={{ fontFamily: FONTS.mono, fontSize: 7, letterSpacing: "0.22em", color: T.t3, textTransform: "uppercase", marginBottom: 10, opacity: 0.6 }}>
            Equity
          </div>
          <div style={{ fontFamily: FONTS.mono, fontSize: 38, fontWeight: 400, color: equity >= starting ? T.green : T.red, letterSpacing: "-0.025em", lineHeight: 1 }}>
            ${typeof equity === "number" ? equity.toFixed(2) : "—"}
          </div>
          {totalPnl != null && (
            <div style={{ fontFamily: FONTS.mono, fontSize: 9, marginTop: 7, color: pnlColor }}>
              {fmtPct(totalPnl)} total
            </div>
          )}
        </div>

        {/* Divider */}
        <div style={{ width: 1, height: 48, background: "rgba(37,99,235,0.12)", marginRight: 36, marginBottom: 8, flexShrink: 0 }} />

        {/* Daily P&L */}
        <div style={{ paddingRight: 36, paddingBottom: 4 }}>
          <div style={{ fontFamily: FONTS.mono, fontSize: 7, letterSpacing: "0.20em", color: T.t3, textTransform: "uppercase", marginBottom: 10, opacity: 0.6 }}>Daily P&amp;L</div>
          <div style={{ fontFamily: FONTS.mono, fontSize: 28, fontWeight: 400, color: dailyColor, letterSpacing: "-0.02em", lineHeight: 1 }}>
            {typeof dailyPnl === "number" ? fmtPct(dailyPnl) : "—"}
          </div>
          <div style={{ fontFamily: FONTS.mono, fontSize: 9, marginTop: 7, color: dailyColor, opacity: 0.75 }}>
            {typeof dailyPnl === "number" ? fmtAbs(dailyPnl * starting / 100) : "—"}
          </div>
        </div>

        {/* Starting */}
        <div style={{ paddingRight: 36, paddingBottom: 4 }}>
          <div style={{ fontFamily: FONTS.mono, fontSize: 7, letterSpacing: "0.20em", color: T.t3, textTransform: "uppercase", marginBottom: 10, opacity: 0.6 }}>Starting</div>
          <div style={{ fontFamily: FONTS.mono, fontSize: 28, fontWeight: 400, color: T.t2, letterSpacing: "-0.02em", lineHeight: 1 }}>
            ${starting > 0 ? starting.toFixed(0) : "—"}
          </div>
          <div style={{ fontFamily: FONTS.mono, fontSize: 9, marginTop: 7, color: T.t3, opacity: 0.6 }}>USDT paper</div>
        </div>

        {/* Status indicator — far right */}
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8, paddingBottom: 8 }}>
          <span style={{
            width: 5, height: 5, borderRadius: "50%",
            background: stale ? T.amber : T.green, flexShrink: 0,
            boxShadow: `0 0 6px ${stale ? T.amber : T.green}`,
            animation: stale ? "none" : "blink 2.2s ease-in-out infinite",
          }} />
          <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: stale ? T.amber : T.t3, letterSpacing: "0.10em", opacity: 0.7 }}>
            {stale ? "STALE" : "DRY RUN · BTC/ETH/SOL"}
          </span>
          {updated && (
            <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.t3, opacity: 0.45 }}>
              · {fmtTime(updated)}
            </span>
          )}
        </div>
      </div>

      {/* P&L thin progress bar */}
      {starting > 0 && totalPnl != null && (
        <div style={{ marginTop: 16, height: 2, background: "rgba(255,255,255,0.05)", borderRadius: 1 }}>
          <div style={{
            height: "100%",
            width: `${Math.min(100, Math.max(0, 50 + totalPnl / 2))}%`,
            background: pnlColor, borderRadius: 1, opacity: 0.5,
            transition: "width .5s ease",
          }} />
        </div>
      )}

      <style>{`@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.2} }`}</style>
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
  const { spot, leveraged_3x, smc_enhanced, key_findings } = data;
  const lev = leveraged_3x?.summary;

  return (
    <div className="fade-up" style={{ marginBottom: 24, paddingBottom: 24, borderBottom: `1px solid rgba(37,99,235,0.08)` }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 16, paddingBottom: 10, borderBottom: `1px solid rgba(37,99,235,0.08)` }}>
        <span style={{ fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, letterSpacing: ".10em", color: T.t2, textTransform: "uppercase" }}>
          Backtest
        </span>
        <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.t3, opacity: 0.5 }}>
          14 months · {data.strategy}
        </span>
        <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.green, opacity: 0.7, marginLeft: "auto" }}>{data.status}</span>
      </div>

      {/* Key metrics — inline strip */}
      <div style={{ display: "flex", gap: 0, flexWrap: "wrap", marginBottom: 16 }}>
        {[
          { label: "Total Return", value: lev ? `+${lev.total_return}%` : "—", sub: "3× leveraged", color: lev && lev.total_return >= 0 ? T.green : T.red },
          { label: "Annualized",   value: lev?.annualized ? `${lev.annualized}%` : "—", sub: "CAGR", color: T.green },
          { label: "Win Rate",     value: spot?.summary?.win_rate != null ? `${spot.summary.win_rate}%` : "—", sub: `${spot?.summary?.trades ?? "—"} trades`, color: T.green },
          { label: "Median Return",value: spot?.summary?.median_return ? `${spot.summary.median_return}%` : "—", sub: "per trade", color: T.cyan },
        ].map((s, i, arr) => (
          <div key={i} style={{
            paddingRight: 32,
            borderRight: i < arr.length - 1 ? `1px solid rgba(37,99,235,0.10)` : "none",
            marginRight: i < arr.length - 1 ? 32 : 0,
            paddingBottom: 4,
          }}>
            <div style={{ fontFamily: FONTS.mono, fontSize: 7, letterSpacing: "0.20em", color: T.t3, textTransform: "uppercase", marginBottom: 8, opacity: 0.6 }}>{s.label}</div>
            <div style={{ fontFamily: FONTS.mono, fontSize: 22, fontWeight: 400, color: s.color, letterSpacing: "-0.02em", lineHeight: 1, marginBottom: 5 }}>{s.value}</div>
            <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.t3, opacity: 0.6 }}>{s.sub}</div>
          </div>
        ))}
      </div>

      {/* Per-asset */}
      {lev?.by_asset && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontFamily: FONTS.mono, fontSize: 8, fontWeight: 600, letterSpacing: ".10em", textTransform: "uppercase", color: T.t3, marginBottom: 8, opacity: 0.6 }}>By Asset</div>
          <div style={{ display: "flex", gap: 24 }}>
            {lev.by_asset.map(a => (
              <div key={a.asset}>
                <div style={{ fontFamily: FONTS.display, fontSize: 11, fontWeight: 600, color: T.t2, marginBottom: 3 }}>{a.asset}</div>
                <div style={{ fontFamily: FONTS.mono, fontSize: 13, color: a.return >= 0 ? T.green : T.red }}>
                  {a.return >= 0 ? "+" : ""}{a.return}%
                </div>
                <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.t3, opacity: 0.6, marginTop: 2 }}>{a.trades}t · {a.win_rate}% WR</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Key findings */}
      {key_findings && key_findings.length > 0 && (
        <div>
          <div style={{ fontFamily: FONTS.mono, fontSize: 8, fontWeight: 600, letterSpacing: ".10em", textTransform: "uppercase", color: T.t3, marginBottom: 6, opacity: 0.6 }}>Key Findings</div>
          {key_findings.map((f, i) => (
            <div key={i} style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.t2, marginBottom: 4, display: "flex", gap: 8 }}>
              <span style={{ color: T.t3, opacity: 0.5 }}>›</span>{f}
            </div>
          ))}
        </div>
      )}

      {/* SMC Enhanced */}
      {smc_enhanced && (
        <div style={{ marginTop: 10, paddingTop: 10, borderTop: `1px solid rgba(37,99,235,0.08)`, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <span style={{ fontFamily: FONTS.display, fontSize: 10, fontWeight: 600, color: T.cyan }}>SMC Enhanced</span>
            <span style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.t3, marginLeft: 8 }}>
              {smc_enhanced.summary.trades} trades · {smc_enhanced.summary.win_rate}% WR · median {smc_enhanced.summary.median_return}%
            </span>
          </div>
          <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.green }}>{smc_enhanced.vs_original?.avg_return_improvement} avg return</div>
        </div>
      )}
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
    <div style={{ paddingBottom: 24, marginBottom: 24, borderBottom: `1px solid rgba(37,99,235,0.08)` }}>
      <div style={{ display: "flex", gap: 40 }}>
        {[90, 70, 60].map((w, i) => (
          <div key={i}>
            <div className="sk" style={{ height: 8, width: 40, marginBottom: 10 }} />
            <div className="sk" style={{ height: 36, width: w }} />
            <div className="sk" style={{ height: 8, width: 30, marginTop: 8 }} />
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
    <div style={{ color: T.t1, padding: "0 0 32px" }}>
      <style>{CSS}</style>

      {/* Header — minimal */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        paddingBottom: 24, marginBottom: 4,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontFamily: FONTS.display, fontSize: 13, fontWeight: 600, letterSpacing: "-0.01em", color: T.t1 }}>
            Quant Monitor
          </span>
          <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.t3, letterSpacing: "0.10em", opacity: 0.5 }}>
            · Freqtrade dry run
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ width: 5, height: 5, borderRadius: "50%", background: stale ? T.amber : T.green }} className={stale ? "" : "pulse-dot"} />
          <button
            onClick={fetchData}
            style={{
              background: "transparent", border: `1px solid rgba(37,99,235,0.14)`,
              borderRadius: 4, padding: "3px 7px", cursor: "pointer",
              color: T.t3, display: "flex", alignItems: "center",
            }}
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={loading ? "spinner" : ""}>
              <path d="M23 4v6h-6M1 20v-6h6M20.49 9A9 9 0 0 0 5.64 5.64L1 10M23 14l-4.64 4.36A9 9 0 0 1 3.51 15"/>
            </svg>
          </button>
        </div>
      </div>

      {/* Content */}
      <div>

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

        {/* Open Positions */}
        <div className="fade-up" style={{ marginBottom: 24 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 12, paddingBottom: 10, borderBottom: `1px solid rgba(37,99,235,0.10)` }}>
            <span style={{ fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, letterSpacing: ".10em", color: T.t2, textTransform: "uppercase" }}>
              Open Positions
            </span>
            <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.t3, opacity: 0.5 }}>{openTrades.length} active</span>
          </div>

          {openTrades.length === 0 ? null : (
            <div>
              <div style={{
                display: "grid", gridTemplateColumns: "1fr 80px 80px 80px 60px",
                gap: 8, padding: "0 0 6px",
                borderBottom: `1px solid rgba(37,99,235,0.08)`,
              }}>
                {["Pair", "Entry", "Current", "P&L", "Side"].map(h => (
                  <div key={h} style={{ fontFamily: FONTS.mono, fontSize: 8, fontWeight: 600, letterSpacing: ".10em", textTransform: "uppercase", color: T.t3, opacity: 0.5, textAlign: h === "Pair" ? "left" : "right" }}>{h}</div>
                ))}
              </div>
              {openTrades.map((t, i) => <OpenTradeRow key={t.trade_id || i} trade={t} />)}
            </div>
          )}
        </div>

        {/* Trade History */}
        <div className="fade-up" style={{ marginBottom: 24 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 12, paddingBottom: 10, borderBottom: `1px solid rgba(37,99,235,0.10)` }}>
            <span style={{ fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, letterSpacing: ".10em", color: T.t2, textTransform: "uppercase" }}>
              Trade History
            </span>
            <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.t3, opacity: 0.5 }}>{closedTrades.length} recent</span>
          </div>

          {closedTrades.length === 0 ? null : (
            <div>
              <div style={{
                display: "grid", gridTemplateColumns: "1fr 80px 80px 70px",
                gap: 8, padding: "0 0 6px",
                borderBottom: `1px solid rgba(37,99,235,0.08)`,
              }}>
                {["Pair", "Entry", "Exit", "P&L"].map(h => (
                  <div key={h} style={{ fontFamily: FONTS.mono, fontSize: 8, fontWeight: 600, letterSpacing: ".10em", textTransform: "uppercase", color: T.t3, opacity: 0.5, textAlign: h === "Pair" ? "left" : "right" }}>{h}</div>
                ))}
              </div>
              {closedTrades.map((t, i) => <TradeHistoryRow key={t.trade_id || i} trade={t} />)}
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{ paddingTop: 16, borderTop: `1px solid rgba(37,99,235,0.06)`, color: T.t3, fontSize: 9, fontFamily: FONTS.mono, opacity: 0.4, letterSpacing: "0.08em" }}>
          CometCloud Quant · Dry Run · Paper Trading · 10,000 USDT
        </div>
      </div>
    </div>
  );
}
