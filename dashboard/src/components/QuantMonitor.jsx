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
          <div style={{ fontFamily: FONTS.mono, fontSize: 9, letterSpacing: "0.16em", color: T.t3, textTransform: "uppercase", marginBottom: 10, opacity: 0.6 }}>
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
          <div style={{ fontFamily: FONTS.mono, fontSize: 9, letterSpacing: "0.14em", color: T.t3, textTransform: "uppercase", marginBottom: 10, opacity: 0.6 }}>Daily P&amp;L</div>
          <div style={{ fontFamily: FONTS.mono, fontSize: 28, fontWeight: 400, color: dailyColor, letterSpacing: "-0.02em", lineHeight: 1 }}>
            {typeof dailyPnl === "number" ? fmtPct(dailyPnl) : "—"}
          </div>
          <div style={{ fontFamily: FONTS.mono, fontSize: 9, marginTop: 7, color: dailyColor, opacity: 0.75 }}>
            {typeof dailyPnl === "number" ? fmtAbs(dailyPnl * starting / 100) : "—"}
          </div>
        </div>

        {/* Starting */}
        <div style={{ paddingRight: 36, paddingBottom: 4 }}>
          <div style={{ fontFamily: FONTS.mono, fontSize: 9, letterSpacing: "0.14em", color: T.t3, textTransform: "uppercase", marginBottom: 10, opacity: 0.6 }}>Starting</div>
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
            <div style={{ fontFamily: FONTS.mono, fontSize: 9, letterSpacing: "0.14em", color: T.t3, textTransform: "uppercase", marginBottom: 8, opacity: 0.6 }}>{s.label}</div>
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

/* ─── Paper Trading Panel ───────────────────────────────────────────── */
const COMMON_SYMS = ["BTC","ETH","SOL","ARB","OP","LINK","AAVE","MKR","UNI","PENDLE","ONDO","TAO","RENDER","INJ","LDO"];

function PaperTrading() {
  const [positions, setPositions] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [mineData, setMineData] = useState(null);
  const [mineType, setMineType] = useState("grade_alpha");
  const [orderForm, setOrderForm] = useState({ symbol: "ETH", side: "LONG", size_usd: 500, sl: 4, tp: 10 });
  const [submitting, setSubmitting] = useState(false);
  const [lastResult, setLastResult] = useState(null);
  const [tab, setTab] = useState("positions"); // positions | order | mine

  const fetchPositions = useCallback(async () => {
    const [pos, met] = await Promise.all([
      fetch("/api/v1/trading/positions").then(r => r.ok ? r.json() : null).catch(() => null),
      fetch("/api/v1/trading/metrics").then(r => r.ok ? r.json() : null).catch(() => null),
    ]);
    setPositions(pos);
    setMetrics(met);
  }, []);

  const fetchMine = useCallback(async (type) => {
    setMineData(null);
    const d = await fetch(`/api/v1/trading/mine?type=${type}&hours=168`).then(r => r.ok ? r.json() : null).catch(() => null);
    setMineData(d);
  }, []);

  useEffect(() => { fetchPositions(); }, [fetchPositions]);
  useEffect(() => {
    if (tab === "mine") fetchMine(mineType);
  }, [tab, mineType, fetchMine]);

  const submitOrder = async () => {
    setSubmitting(true);
    setLastResult(null);
    try {
      const r = await fetch("/api/v1/trading/order", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: orderForm.symbol,
          side: orderForm.side,
          size_usd: parseFloat(orderForm.size_usd),
          stop_loss_pct: parseFloat(orderForm.sl) / 100,
          take_profit_pct: parseFloat(orderForm.tp) / 100,
          mode: "PAPER",
          note: "QuantMonitor UI order",
        }),
      });
      const d = await r.json();
      setLastResult(d);
      if (d.status === "filled") fetchPositions();
    } catch (e) {
      setLastResult({ status: "error", reason: e.message });
    } finally {
      setSubmitting(false);
    }
  };

  const closePosition = async (order_id) => {
    await fetch(`/api/v1/trading/positions/${order_id}`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: "ui_close" }),
    });
    fetchPositions();
  };

  const accentColor = tab === "positions" ? "#00D98A" : tab === "order" ? "#6366f1" : "#f59e0b";

  return (
    <div style={{ marginTop: 24, paddingTop: 20, borderTop: "1px solid rgba(37,99,235,0.08)" }}>
      {/* Section header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, letterSpacing: ".10em", color: "#C7D2FE", textTransform: "uppercase" }}>
            Paper Trading Agent
          </span>
          {metrics && (
            <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: metrics.total_pnl_usd >= 0 ? "#00D98A" : "#FF3D5A", opacity: 0.8 }}>
              {metrics.total_pnl_usd >= 0 ? "+" : ""}${(metrics.total_pnl_usd || 0).toFixed(2)} realized
            </span>
          )}
        </div>
        {/* Tabs */}
        <div style={{ display: "flex", borderRadius: 5, border: "1px solid rgba(37,99,235,0.14)", overflow: "hidden" }}>
          {[["positions","Positions"],["order","Order"],["mine","Mine"]].map(([k,l]) => (
            <button key={k} onClick={() => setTab(k)} style={{
              padding: "4px 10px", border: "none",
              background: tab === k ? "rgba(99,102,241,0.12)" : "transparent",
              color: tab === k ? "#C7D2FE" : "rgba(199,210,254,0.4)",
              fontSize: 10, fontFamily: FONTS.mono, cursor: "pointer",
              fontWeight: tab === k ? 600 : 400,
            }}>{l}</button>
          ))}
        </div>
      </div>

      {/* Portfolio bar */}
      {metrics && (
        <div style={{ display: "flex", gap: 20, marginBottom: 16, flexWrap: "wrap" }}>
          {[
            ["Portfolio", `$${(metrics.portfolio_usd || 10000).toFixed(0)}`],
            ["Cash", `$${(metrics.cash_usd || 0).toFixed(0)}`],
            ["Trades", metrics.total_trades],
            ["Win Rate", metrics.win_rate != null ? `${metrics.win_rate}%` : "—"],
            ["Avg Return", metrics.avg_return_pct != null ? `${metrics.avg_return_pct >= 0 ? "+" : ""}${metrics.avg_return_pct?.toFixed(2)}%` : "—"],
            ["Sharpe", metrics.sharpe_approx ?? "—"],
          ].map(([label, val]) => (
            <div key={label}>
              <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: "rgba(199,210,254,0.4)", letterSpacing: "0.10em", marginBottom: 3 }}>{label.toUpperCase()}</div>
              <div style={{ fontFamily: FONTS.mono, fontSize: 13, color: "#E8EAF0" }}>{val}</div>
            </div>
          ))}
        </div>
      )}

      {/* ── Positions tab ── */}
      {tab === "positions" && (
        <div>
          {!positions && <div style={{ fontFamily: FONTS.mono, fontSize: 10, color: "rgba(199,210,254,0.3)", padding: "12px 0" }}>Loading positions…</div>}
          {positions && positions.count === 0 && (
            <div style={{ fontFamily: FONTS.mono, fontSize: 10, color: "rgba(199,210,254,0.3)", padding: "12px 0" }}>
              No open positions. Use the Order tab to enter a trade.
            </div>
          )}
          {positions && positions.positions?.map(pos => {
            const pnlColor = (pos.unrealized_pnl || 0) >= 0 ? "#00D98A" : "#FF3D5A";
            const triggered = pos.sl_triggered || pos.tp_triggered;
            return (
              <div key={pos.order_id} style={{
                display: "flex", alignItems: "center", gap: 10,
                padding: "9px 12px", marginBottom: 5, borderRadius: 6,
                background: triggered ? "rgba(255,61,90,0.06)" : "rgba(15,30,70,0.6)",
                border: `1px solid ${triggered ? "rgba(255,61,90,0.20)" : "rgba(37,99,235,0.12)"}`,
              }}>
                <span style={{ fontFamily: FONTS.mono, fontSize: 11, fontWeight: 700, color: "#E8EAF0", minWidth: 44 }}>{pos.symbol}</span>
                <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: pos.side === "LONG" ? "#00D98A" : "#FF3D5A", minWidth: 36 }}>{pos.side}</span>
                <span style={{ fontFamily: FONTS.mono, fontSize: 9, color: "rgba(199,210,254,0.5)" }}>@ ${pos.entry_price?.toFixed(4)}</span>
                <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: pnlColor, marginLeft: "auto" }}>
                  {pos.unrealized_pnl >= 0 ? "+" : ""}${(pos.unrealized_pnl || 0).toFixed(2)} ({pos.unrealized_pct >= 0 ? "+" : ""}{(pos.unrealized_pct || 0).toFixed(2)}%)
                </span>
                <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: "rgba(199,210,254,0.3)", minWidth: 30 }}>
                  {pos.cis_grade} {pos.cis_score?.toFixed(0)}
                </span>
                {triggered && (
                  <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: "#FF3D5A" }}>
                    {pos.sl_triggered ? "SL" : "TP"} hit
                  </span>
                )}
                <button onClick={() => closePosition(pos.order_id)} style={{
                  fontFamily: FONTS.mono, fontSize: 8, color: "#FF3D5A",
                  background: "rgba(255,61,90,0.08)", border: "1px solid rgba(255,61,90,0.2)",
                  borderRadius: 3, padding: "2px 7px", cursor: "pointer",
                }}>Close</button>
              </div>
            );
          })}
          <button onClick={fetchPositions} style={{
            marginTop: 8, fontFamily: FONTS.mono, fontSize: 9, color: "rgba(199,210,254,0.4)",
            background: "none", border: "1px solid rgba(37,99,235,0.14)", borderRadius: 4,
            padding: "3px 10px", cursor: "pointer",
          }}>Refresh</button>
        </div>
      )}

      {/* ── Order tab ── */}
      {tab === "order" && (
        <div>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 14 }}>
            {/* Symbol */}
            <div>
              <div style={{ fontFamily: FONTS.mono, fontSize: 8, color: "rgba(199,210,254,0.4)", marginBottom: 4, letterSpacing: "0.10em" }}>SYMBOL</div>
              <select
                value={orderForm.symbol}
                onChange={e => setOrderForm(f => ({...f, symbol: e.target.value}))}
                style={{ fontFamily: FONTS.mono, fontSize: 11, color: "#E8EAF0", background: "rgba(15,30,70,0.8)", border: "1px solid rgba(37,99,235,0.18)", borderRadius: 4, padding: "5px 8px" }}
              >
                {COMMON_SYMS.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            {/* Side */}
            <div>
              <div style={{ fontFamily: FONTS.mono, fontSize: 8, color: "rgba(199,210,254,0.4)", marginBottom: 4, letterSpacing: "0.10em" }}>SIDE</div>
              <div style={{ display: "flex", borderRadius: 4, border: "1px solid rgba(37,99,235,0.18)", overflow: "hidden" }}>
                {["LONG","SHORT"].map(s => (
                  <button key={s} onClick={() => setOrderForm(f => ({...f, side: s}))} style={{
                    padding: "5px 12px", border: "none", fontFamily: FONTS.mono, fontSize: 10, cursor: "pointer",
                    background: orderForm.side === s ? (s === "LONG" ? "rgba(0,217,138,0.15)" : "rgba(255,61,90,0.15)") : "rgba(15,30,70,0.8)",
                    color: orderForm.side === s ? (s === "LONG" ? "#00D98A" : "#FF3D5A") : "rgba(199,210,254,0.4)",
                    fontWeight: orderForm.side === s ? 700 : 400,
                  }}>{s}</button>
                ))}
              </div>
            </div>
            {/* Size */}
            <div>
              <div style={{ fontFamily: FONTS.mono, fontSize: 8, color: "rgba(199,210,254,0.4)", marginBottom: 4, letterSpacing: "0.10em" }}>SIZE (USD)</div>
              <input type="number" min="10" max="5000" value={orderForm.size_usd}
                onChange={e => setOrderForm(f => ({...f, size_usd: e.target.value}))}
                style={{ fontFamily: FONTS.mono, fontSize: 11, color: "#E8EAF0", background: "rgba(15,30,70,0.8)", border: "1px solid rgba(37,99,235,0.18)", borderRadius: 4, padding: "5px 8px", width: 80 }}
              />
            </div>
            {/* SL/TP */}
            <div>
              <div style={{ fontFamily: FONTS.mono, fontSize: 8, color: "rgba(199,210,254,0.4)", marginBottom: 4, letterSpacing: "0.10em" }}>SL %</div>
              <input type="number" min="0.5" max="30" step="0.5" value={orderForm.sl}
                onChange={e => setOrderForm(f => ({...f, sl: e.target.value}))}
                style={{ fontFamily: FONTS.mono, fontSize: 11, color: "#FF3D5A", background: "rgba(15,30,70,0.8)", border: "1px solid rgba(255,61,90,0.18)", borderRadius: 4, padding: "5px 8px", width: 60 }}
              />
            </div>
            <div>
              <div style={{ fontFamily: FONTS.mono, fontSize: 8, color: "rgba(199,210,254,0.4)", marginBottom: 4, letterSpacing: "0.10em" }}>TP %</div>
              <input type="number" min="1" max="200" step="0.5" value={orderForm.tp}
                onChange={e => setOrderForm(f => ({...f, tp: e.target.value}))}
                style={{ fontFamily: FONTS.mono, fontSize: 11, color: "#00D98A", background: "rgba(15,30,70,0.8)", border: "1px solid rgba(0,217,138,0.18)", borderRadius: 4, padding: "5px 8px", width: 60 }}
              />
            </div>
          </div>

          <button
            onClick={submitOrder}
            disabled={submitting}
            style={{
              fontFamily: FONTS.mono, fontSize: 11, fontWeight: 700, letterSpacing: "0.08em",
              color: "#E8EAF0", background: submitting ? "rgba(99,102,241,0.12)" : "rgba(99,102,241,0.18)",
              border: "1px solid rgba(99,102,241,0.30)", borderRadius: 5, padding: "8px 20px",
              cursor: submitting ? "not-allowed" : "pointer", marginBottom: 14, transition: "all 0.15s",
            }}
          >
            {submitting ? "Submitting…" : `Submit ${orderForm.side} ${orderForm.symbol} $${orderForm.size_usd}`}
          </button>

          {/* Result */}
          {lastResult && (
            <div style={{
              padding: "10px 14px", borderRadius: 6, marginBottom: 8,
              background: lastResult.status === "filled" ? "rgba(0,217,138,0.06)" : "rgba(255,61,90,0.06)",
              border: `1px solid ${lastResult.status === "filled" ? "rgba(0,217,138,0.15)" : "rgba(255,61,90,0.15)"}`,
            }}>
              <div style={{ fontFamily: FONTS.mono, fontSize: 10, color: lastResult.status === "filled" ? "#00D98A" : "#FF3D5A", fontWeight: 700, marginBottom: 4 }}>
                {lastResult.status === "filled" ? "✓ Filled" : `✗ ${lastResult.status === "rejected" ? "Rejected" : "Error"}`}
              </div>
              {lastResult.status === "filled" ? (
                <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: "rgba(199,210,254,0.6)", lineHeight: 1.6 }}>
                  {lastResult.symbol} {lastResult.side} @ ${lastResult.fill_price?.toFixed(4)} · CIS {lastResult.cis_score} {lastResult.grade} · {lastResult.macro_regime}
                  <br />SL ${lastResult.stop_loss?.toFixed(4)} · TP ${lastResult.take_profit?.toFixed(4)} · ID: {lastResult.order_id}
                </div>
              ) : (
                <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: "rgba(255,61,90,0.8)" }}>{lastResult.reason}</div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Mine tab ── */}
      {tab === "mine" && (
        <div>
          <div style={{ display: "flex", gap: 6, marginBottom: 14, flexWrap: "wrap" }}>
            {[
              ["grade_alpha","Grade Alpha"],
              ["pillar_fitness","Pillar Fitness"],
              ["signal_accuracy","Signal Accuracy"],
              ["regime_performance","By Regime"],
            ].map(([k,l]) => (
              <button key={k} onClick={() => setMineType(k)} style={{
                fontFamily: FONTS.mono, fontSize: 9, padding: "4px 10px", borderRadius: 4,
                border: "1px solid rgba(37,99,235,0.14)",
                background: mineType === k ? "rgba(245,158,11,0.12)" : "transparent",
                color: mineType === k ? "#f59e0b" : "rgba(199,210,254,0.4)",
                cursor: "pointer", fontWeight: mineType === k ? 700 : 400,
              }}>{l}</button>
            ))}
          </div>

          {!mineData && <div style={{ fontFamily: FONTS.mono, fontSize: 10, color: "rgba(199,210,254,0.3)" }}>Mining…</div>}
          {mineData?.message && (
            <div style={{ fontFamily: FONTS.mono, fontSize: 10, color: "rgba(199,210,254,0.4)", padding: "10px 0" }}>
              {mineData.message} — close some trades first to generate analysis data.
            </div>
          )}
          {mineData && !mineData.message && (
            <div>
              <div style={{ fontFamily: FONTS.mono, fontSize: 8, color: "rgba(199,210,254,0.35)", marginBottom: 10, letterSpacing: "0.08em" }}>
                {mineData.trade_count} trades · {mineData.hours}h window · {mineData.source}
              </div>
              {/* Grade Alpha */}
              {mineData.by_grade && Object.entries(mineData.by_grade).map(([grade, stats]) => (
                <div key={grade} style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 5, padding: "6px 10px", borderRadius: 4, background: "rgba(15,30,70,0.5)" }}>
                  <span style={{ fontFamily: FONTS.mono, fontSize: 11, fontWeight: 700, color: "#C7D2FE", minWidth: 28 }}>{grade}</span>
                  <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: stats.avg_return_pct >= 0 ? "#00D98A" : "#FF3D5A" }}>
                    {stats.avg_return_pct >= 0 ? "+" : ""}{stats.avg_return_pct?.toFixed(2)}% avg
                  </span>
                  <span style={{ fontFamily: FONTS.mono, fontSize: 9, color: "rgba(199,210,254,0.4)" }}>{stats.win_rate_pct}% win · {stats.trade_count} trades</span>
                </div>
              ))}
              {/* Pillar Fitness */}
              {mineData.pillar_correlations && Object.entries(mineData.pillar_correlations).map(([pillar, corr]) => (
                <div key={pillar} style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 5, padding: "6px 10px", borderRadius: 4, background: "rgba(15,30,70,0.5)" }}>
                  <span style={{ fontFamily: FONTS.mono, fontSize: 10, fontWeight: 700, color: "#C7D2FE", minWidth: 24 }}>Pillar {pillar}</span>
                  <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: corr == null ? "rgba(199,210,254,0.3)" : corr > 0 ? "#00D98A" : "#FF3D5A" }}>
                    {corr == null ? "< 5 trades" : `ρ = ${corr.toFixed(3)}`}
                  </span>
                  {corr != null && <div style={{ flex: 1, height: 3, background: "rgba(37,99,235,0.15)", borderRadius: 2 }}>
                    <div style={{ height: "100%", width: `${Math.abs(corr)*100}%`, borderRadius: 2, background: corr > 0 ? "#00D98A" : "#FF3D5A", transition: "width 0.5s ease" }} />
                  </div>}
                </div>
              ))}
              {/* Regime Performance */}
              {mineData.by_regime && Object.entries(mineData.by_regime).map(([regime, stats]) => (
                <div key={regime} style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 5, padding: "6px 10px", borderRadius: 4, background: "rgba(15,30,70,0.5)" }}>
                  <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: "#C7D2FE", minWidth: 90 }}>{regime}</span>
                  <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: stats.avg_return_pct >= 0 ? "#00D98A" : "#FF3D5A" }}>
                    {stats.avg_return_pct >= 0 ? "+" : ""}{stats.avg_return_pct?.toFixed(2)}% avg
                  </span>
                  <span style={{ fontFamily: FONTS.mono, fontSize: 9, color: "rgba(199,210,254,0.4)" }}>{stats.win_rate_pct}% win · {stats.trade_count}T</span>
                </div>
              ))}
              {/* Signal Accuracy */}
              {mineData.by_signal && Object.entries(mineData.by_signal).map(([sig, stats]) => (
                <div key={sig} style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 5, padding: "6px 10px", borderRadius: 4, background: "rgba(15,30,70,0.5)" }}>
                  <span style={{ fontFamily: FONTS.mono, fontSize: 9, color: "#C7D2FE", minWidth: 110 }}>{sig}</span>
                  <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: stats.avg_return_pct >= 0 ? "#00D98A" : "#FF3D5A" }}>
                    {stats.avg_return_pct >= 0 ? "+" : ""}{stats.avg_return_pct?.toFixed(2)}% avg
                  </span>
                  {stats.accuracy_pct != null && <span style={{ fontFamily: FONTS.mono, fontSize: 9, color: "rgba(199,210,254,0.4)" }}>{stats.accuracy_pct}% accurate · {stats.trade_count}T</span>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ─── Simons IC Feedback Panel ──────────────────────────────────────── */
const PILLAR_LABELS = { F: "Fundamental", M: "Momentum", O: "On-chain / Risk", S: "Sentiment", A: "Alpha" };
const PILLAR_ORDER  = ["F", "M", "O", "S", "A"];
const PILLAR_HUE    = { F: "#6366f1", M: "#00D98A", O: "#f59e0b", S: "#38bdf8", A: "#a78bfa" };

function computeMultiplier(factors) {
  if (!factors || factors.length === 0) return 1.0;
  const active = factors.filter(f => f.pearson_r != null && Math.abs(f.pearson_r) > 0.10 && (f.sample_size || 0) >= 10);
  if (active.length === 0) return 1.0;
  const meanR = active.reduce((s, f) => s + (f.pearson_r || 0), 0) / active.length;
  return Math.round((1.0 + Math.max(-0.30, Math.min(0.30, meanR * 2.5))) * 10000) / 10000;
}

/* ─── Factor Lab ─────────────────────────────────────────────────────────── */
// Shows pending Gemma4-26b discovery requests and active factor hypotheses.
// Rendered at the bottom of SimonsPanel when discovery data is present.
function FactorLab() {
  const [disc, setDisc] = useState(null);

  useEffect(() => {
    const load = () =>
      fetch(`${API_BASE}/factors/discovery`)
        .then(r => r.ok ? r.json() : null).catch(() => null)
        .then(d => setDisc(d));
    load();
    const iv = setInterval(load, 120_000); // 2min — discovery is slow-moving
    return () => clearInterval(iv);
  }, []);

  if (!disc) return null;
  const hasPending    = disc.has_pending;
  const hypotheses    = disc.hypotheses ?? {};
  const pending       = disc.pending;
  const pillarsWithH  = Object.keys(hypotheses);
  if (!hasPending && pillarsWithH.length === 0) return null;

  const CONF_COLOR = { HIGH: "#00D98A", MEDIUM: "#f59e0b", LOW: "rgba(199,210,254,0.30)" };

  return (
    <div style={{
      marginTop: 16, padding: "14px 16px", borderRadius: 8,
      background: "rgba(5,7,22,0.60)",
      border: "1px solid rgba(99,102,241,0.12)",
    }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <span style={{ fontFamily: FONTS.display, fontSize: 10, fontWeight: 700, letterSpacing: ".10em", color: T.t2, textTransform: "uppercase" }}>
          Factor Lab
        </span>
        {hasPending && (
          <span style={{
            fontFamily: FONTS.mono, fontSize: 9, fontWeight: 700, letterSpacing: ".06em",
            padding: "1px 7px", borderRadius: 3,
            background: "rgba(245,158,11,0.10)", color: "#f59e0b",
            border: "1px solid rgba(245,158,11,0.22)",
          }}>
            QUEUED
          </span>
        )}
      </div>

      {/* Pending request */}
      {hasPending && (
        <div style={{
          marginBottom: 10, padding: "8px 10px", borderRadius: 6,
          background: "rgba(245,158,11,0.05)", border: "1px solid rgba(245,158,11,0.12)",
        }}>
          <div style={{ fontFamily: FONTS.mono, fontSize: 8, color: "#f59e0b", marginBottom: 3, fontWeight: 700 }}>
            Weak IC detected · Awaiting Gemma4-26b analysis
          </div>
          <div style={{ fontFamily: FONTS.mono, fontSize: 7, color: "rgba(199,210,254,0.40)" }}>
            Pillars: {(pending?.pillars || []).join(", ")} &nbsp;·&nbsp; Regime: {pending?.regime ?? "—"} &nbsp;·&nbsp; Mac Mini will process on next push cycle
          </div>
        </div>
      )}

      {/* Active hypotheses per pillar */}
      {pillarsWithH.map(pillar => {
        const item = hypotheses[pillar] ?? {};
        const hyps = item.hypotheses || [];
        const color = PILLAR_HUE[pillar] || "#6366f1";
        const age   = item.generated_at
          ? Math.round((Date.now() / 1000 - item.generated_at) / 3600)
          : null;
        return (
          <div key={pillar} style={{ marginBottom: 10 }}>
            <div style={{
              display: "flex", alignItems: "center", gap: 8, marginBottom: 6,
            }}>
              <span style={{ fontFamily: FONTS.mono, fontSize: 8, fontWeight: 700, color, letterSpacing: ".10em" }}>
                PILLAR {pillar}
              </span>
              <span style={{ fontFamily: FONTS.mono, fontSize: 7, color: "rgba(199,210,254,0.25)" }}>
                {hyps.length} hypothesis{hyps.length !== 1 ? "es" : ""}
                {age != null ? ` · generated ${age}h ago` : ""}
              </span>
            </div>
            {hyps.map((h, i) => (
              <div key={i} style={{
                display: "flex", gap: 10, alignItems: "flex-start",
                marginBottom: 5, padding: "8px 10px", borderRadius: 6,
                background: "rgba(255,255,255,0.025)",
                border: `1px solid ${color}14`,
              }}>
                {/* Confidence badge */}
                <span style={{
                  fontFamily: FONTS.mono, fontSize: 9, fontWeight: 700,
                  color: CONF_COLOR[h.confidence] ?? CONF_COLOR.LOW,
                  flexShrink: 0, paddingTop: 1,
                }}>
                  {h.confidence}
                </span>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.t1, marginBottom: 2, fontWeight: 600 }}>
                    {h.name}
                  </div>
                  <div style={{ fontFamily: FONTS.mono, fontSize: 7, color: "rgba(199,210,254,0.35)", marginBottom: 2, wordBreak: "break-all" }}>
                    {h.formula}
                  </div>
                  {h.regime_rationale && (
                    <div style={{ fontFamily: FONTS.mono, fontSize: 7, color: "rgba(199,210,254,0.25)", fontStyle: "italic" }}>
                      {h.regime_rationale}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        );
      })}

      <div style={{ fontFamily: FONTS.mono, fontSize: 7, color: "rgba(199,210,254,0.15)", marginTop: 4 }}>
        |r| &lt; 0.05 × 3 mine runs → Gemma4-26b hypothesis generation → test → evolve
      </div>
    </div>
  );
}

// ── Pipeline node labels for the loop flow strip ─────────────────────────────
const LOOP_NODES = [
  { id: "cis",    label: "CIS SCORE",   sub: "5-pillar scoring" },
  { id: "signal", label: "SIGNAL",      sub: "OUTPERFORM gate"  },
  { id: "trade",  label: "TRADE OPEN",  sub: "position entry"   },
  { id: "close",  label: "TRADE CLOSE", sub: "realized P&L"     },
  { id: "mine",   label: "MINE",        sub: "Pearson IC"       },
  { id: "ic",     label: "IC MULT",     sub: "weight adjust"    },
];

function SimonsPanel() {
  const [loop, setLoop]   = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = () =>
      fetch(`${API_BASE}/trading/loop-state`)
        .then(r => r.ok ? r.json() : null)
        .catch(() => null)
        .then(d => { setLoop(d); setLoading(false); });
    load();
    const iv = setInterval(load, 60_000);
    return () => clearInterval(iv);
  }, []);

  const active      = loop?.loop_active ?? false;
  const icMult      = loop?.ic_multipliers ?? {};
  const closed      = loop?.closed_trades ?? 0;
  const nextMine    = loop?.next_mine_at ?? 5;
  const mineRuns    = loop?.mine_periods ?? 0;
  const regime      = loop?.regime ?? "—";
  const gateThresh  = loop?.gate_threshold ?? 50;
  const activeFact  = loop?.active_factors ?? 0;
  const openPos     = loop?.open_positions ?? 0;

  // Node "live" state — what stages have data flowing through them
  const nodeAlive = {
    cis:    true,                  // always live
    signal: true,                  // always gating
    trade:  openPos > 0 || closed > 0,
    close:  closed > 0,
    mine:   mineRuns > 0,
    ic:     active,
  };

  return (
    <div className="fade-up" style={{ marginBottom: 28 }}>

      {/* ── Header ── */}
      <div style={{
        display: "flex", alignItems: "center", gap: 10,
        marginBottom: 14, paddingBottom: 10,
        borderBottom: "1px solid rgba(37,99,235,0.10)",
      }}>
        <span style={{ fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, letterSpacing: ".10em", color: T.t2, textTransform: "uppercase" }}>
          Simons IC Loop
        </span>
        <span style={{
          fontFamily: FONTS.mono, fontSize: 8, fontWeight: 600, letterSpacing: ".08em",
          padding: "1px 7px", borderRadius: 3,
          ...(active
            ? { background: "rgba(0,217,138,0.08)", color: "#00D98A", border: "1px solid rgba(0,217,138,0.18)" }
            : { background: "rgba(245,158,11,0.10)", color: "#f59e0b", border: "1px solid rgba(245,158,11,0.22)" }),
        }}>
          {active ? `LOOP ACTIVE · ${mineRuns} MINE RUNS` : closed >= 5 ? "MINE PENDING" : `AWAITING TRADES · ${nextMine} TO GO`}
        </span>
        {!loading && (
          <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.t3, opacity: 0.40, marginLeft: "auto" }}>
            {closed} closed · {openPos} open · {activeFact} active factors
          </span>
        )}
      </div>

      {loading && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(6,1fr)", gap: 6, marginBottom: 12 }}>
          {[0,1,2,3,4,5].map(i => <div key={i} style={{ height: 40, borderRadius: 5 }} className="sk" />)}
        </div>
      )}

      {/* ── Pipeline flow strip ── */}
      {!loading && (
        <div style={{
          display: "flex", alignItems: "center", gap: 0,
          marginBottom: 14, padding: "10px 12px",
          background: "rgba(5,7,22,0.70)",
          borderRadius: 8, border: "1px solid rgba(37,99,235,0.07)",
          overflowX: "auto",
        }}>
          {LOOP_NODES.map((node, i) => {
            const alive = nodeAlive[node.id];
            const c = alive ? (active ? "#00D98A" : "#f59e0b") : "rgba(199,210,254,0.15)";
            const isLast = i === LOOP_NODES.length - 1;
            return (
              <div key={node.id} style={{ display: "flex", alignItems: "center", flexShrink: 0 }}>
                <div style={{ textAlign: "center", minWidth: 88 }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 5, marginBottom: 4 }}>
                    <div style={{
                      width: 7, height: 7, borderRadius: "50%",
                      background: c,
                      boxShadow: alive ? `0 0 8px ${c}` : "none",
                      transition: "all .4s",
                    }} />
                    <span style={{ fontFamily: FONTS.mono, fontSize: 10, fontWeight: 700, letterSpacing: ".08em", color: c }}>
                      {node.label}
                    </span>
                  </div>
                  <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: "rgba(199,210,254,0.40)", letterSpacing: ".04em" }}>
                    {node.sub}
                  </div>
                </div>
                {!isLast ? (
                  <div style={{
                    flex: 1, height: 1, minWidth: 12, maxWidth: 28,
                    background: nodeAlive[LOOP_NODES[i+1]?.id]
                      ? `linear-gradient(90deg, ${c}, rgba(0,217,138,0.15))`
                      : "rgba(255,255,255,0.05)",
                    position: "relative",
                  }}>
                    {/* Arrow tip */}
                    <div style={{
                      position: "absolute", right: 0, top: "50%",
                      transform: "translateY(-50%)",
                      width: 0, height: 0,
                      borderTop: "3px solid transparent",
                      borderBottom: "3px solid transparent",
                      borderLeft: `4px solid ${nodeAlive[LOOP_NODES[i+1]?.id] ? c : "rgba(255,255,255,0.08)"}`,
                    }} />
                  </div>
                ) : (
                  /* Closing arc — IC feeds back into CIS */
                  <div style={{
                    width: 14, height: 1,
                    background: active
                      ? "linear-gradient(90deg, #00D98A40, transparent)"
                      : "rgba(255,255,255,0.04)",
                  }} />
                )}
              </div>
            );
          })}
          {/* Loop closed indicator */}
          <div style={{
            fontFamily: FONTS.mono, fontSize: 16, letterSpacing: ".08em",
            color: active ? "#00D98A" : "rgba(199,210,254,0.15)",
            marginLeft: 6, flexShrink: 0,
            lineHeight: 1,
          }}>
            ↺
          </div>
        </div>
      )}

      {/* ── Regime gate strip ── */}
      {!loading && (
        <div style={{
          display: "flex", gap: 16, alignItems: "center",
          padding: "8px 12px", marginBottom: 12,
          background: "rgba(5,7,22,0.45)",
          borderRadius: 6, border: "1px solid rgba(255,255,255,0.04)",
        }}>
          <div>
            <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: "rgba(199,210,254,0.35)", letterSpacing: ".08em", marginBottom: 2 }}>REGIME</div>
            <div style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.t2 }}>{regime.replace(/_/g, " ")}</div>
          </div>
          <div style={{ width: 1, height: 22, background: "rgba(255,255,255,0.06)" }} />
          <div>
            <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: "rgba(199,210,254,0.35)", letterSpacing: ".08em", marginBottom: 2 }}>CIS GATE</div>
            <div style={{ fontFamily: FONTS.mono, fontSize: 10, color: "#f59e0b" }}>≥ {gateThresh}</div>
          </div>
          <div style={{ width: 1, height: 22, background: "rgba(255,255,255,0.06)" }} />
          <div>
            <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: "rgba(199,210,254,0.35)", letterSpacing: ".08em", marginBottom: 2 }}>AUTO-MINE</div>
            <div style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.t2 }}>every 5 closes</div>
          </div>
          <div style={{ width: 1, height: 22, background: "rgba(255,255,255,0.06)" }} />
          <div>
            <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: "rgba(199,210,254,0.35)", letterSpacing: ".08em", marginBottom: 2 }}>NEXT MINE</div>
            <div style={{ fontFamily: FONTS.mono, fontSize: 10, color: nextMine <= 1 ? "#00D98A" : T.t2 }}>
              {closed < 5 ? `${nextMine} trades` : `${nextMine} trades`}
            </div>
          </div>
        </div>
      )}

      {/* ── IC multiplier grid ── */}
      {!loading && !active && (
        <div style={{
          padding: "14px 16px", borderRadius: 8,
          background: "rgba(5,7,22,0.60)",
          border: "1px solid rgba(99,102,241,0.10)",
          display: "flex", alignItems: "center", gap: 12,
        }}>
          <div style={{ color: "rgba(245,158,11,0.5)", fontSize: 14 }}>○</div>
          <div>
            <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: "rgba(199,210,254,0.45)", marginBottom: 2 }}>
              {closed < 5
                ? `All pillar multipliers neutral (1.0×) — ${nextMine} more close${nextMine === 1 ? "" : "s"} to activate`
                : `${closed} trades closed — mine has not run yet`}
            </div>
            <div style={{ fontFamily: FONTS.mono, fontSize: 8, color: "rgba(199,210,254,0.22)" }}>
              IC loop activates automatically on trade 5, 10, 15… no manual trigger needed
            </div>
          </div>
        </div>
      )}

      {!loading && active && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 8 }}>
          {PILLAR_ORDER.map(p => {
            const mult  = icMult[p] ?? 1.0;
            const color = PILLAR_HUE[p];
            const delta = mult - 1.0;
            const pct   = Math.abs(delta) / 0.30;
            const sign  = delta >= 0 ? "+" : "";

            return (
              <div key={p} style={{
                borderRadius: 8, padding: "12px 14px",
                background: "rgba(5,7,22,0.70)",
                border: `1px solid ${color}22`,
                display: "flex", flexDirection: "column", gap: 6,
                transition: "border-color .2s ease",
              }}
                onMouseEnter={e => e.currentTarget.style.borderColor = `${color}44`}
                onMouseLeave={e => e.currentTarget.style.borderColor = `${color}22`}
              >
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <span style={{ fontFamily: FONTS.mono, fontSize: 8, fontWeight: 700, letterSpacing: ".12em", color, textTransform: "uppercase" }}>{p}</span>
                  <span style={{ fontFamily: FONTS.mono, fontSize: 9, color: delta > 0.005 ? "#00D98A" : delta < -0.005 ? "#FF3D5A" : "rgba(199,210,254,0.30)" }}>
                    {sign}{(delta * 100).toFixed(0)}%
                  </span>
                </div>

                <div style={{ fontFamily: FONTS.mono, fontSize: 22, fontWeight: 400, color: delta > 0.005 ? "#00D98A" : delta < -0.005 ? "#FF3D5A" : "rgba(199,210,254,0.55)", letterSpacing: "-0.02em", lineHeight: 1 }}>
                  {sign}{delta.toFixed(3)}<span style={{ fontSize: 11, opacity: 0.5 }}>×</span>
                </div>

                {/* IC bar */}
                <div style={{ height: 2, background: "rgba(255,255,255,0.06)", borderRadius: 1 }}>
                  <div style={{
                    height: "100%",
                    width: `${Math.round(pct * 100)}%`,
                    background: delta >= 0 ? "#00D98A" : "#FF3D5A",
                    borderRadius: 1,
                    transition: "width .6s ease",
                    opacity: 0.7,
                  }} />
                </div>

                {/* Label */}
                <div style={{ fontFamily: FONTS.mono, fontSize: 7, color: "rgba(199,210,254,0.25)", letterSpacing: ".04em", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {PILLAR_LABELS[p]}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Formula hint */}
      {!loading && (
        <div style={{ marginTop: 8, fontFamily: FONTS.mono, fontSize: 7, color: "rgba(199,210,254,0.18)", letterSpacing: ".05em" }}>
          weight = base × regime × IC · IC = 1 + clamp(mean_active_r × 2.5, −0.30, +0.30) · auto-mines every 5 closes
        </div>
      )}

      {/* Factor Lab — LLM hypothesis generation */}
      {!loading && <FactorLab />}
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

        {/* Paper Trading Execution Loop */}
        <PaperTrading />

        {/* Simons IC Feedback Loop */}
        <SimonsPanel />

        {/* Footer */}
        <div style={{ paddingTop: 16, borderTop: `1px solid rgba(37,99,235,0.06)`, color: T.t3, fontSize: 9, fontFamily: FONTS.mono, opacity: 0.4, letterSpacing: "0.08em" }}>
          CometCloud Quant · Freqtrade Dry Run + Paper Agent · 10,000 USDT
        </div>
      </div>
    </div>
  );
}
