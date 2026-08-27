/**
 * PerformanceDashboard.jsx
 *
 * Real institutional buy-side metrics from signal_journal.
 * Sharpe · Sortino · CAGR · Max Drawdown · Win Rate · Profit Factor
 * Equity curve · Signal journal table · Attribution by regime / class / grade
 *
 * Data source: /api/v1/signals/performance  (empyrical-computed, 10 min cache)
 *              /api/v1/signals/journal       (paginated signal history)
 */

import { useState, useEffect, useCallback, useRef } from "react";
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";
import { T, FONTS } from "../tokens";

const API = "/api/v1";

/* ─── Palette ────────────────────────────────────────────────────────────── */
const C = {
  green:  "#00D98A",
  red:    "#FF3D5A",
  amber:  "#F59E0B",
  cyan:   "#38BDF8",
  violet: "#818CF8",
  border: "rgba(37,99,235,0.12)",
  card:   "rgba(5,7,22,0.88)",
  glow:   (color) => `0 0 18px ${color}26`,
};

/* ─── Helpers ─────────────────────────────────────────────────────────────── */
const isNum   = (v) => typeof v === "number" && isFinite(v);
const fmtPct  = (v) => isNum(v) ? `${v >= 0 ? "+" : ""}${v.toFixed(2)}%` : "—";
const fmtNum  = (v, d = 2) => isNum(v) ? v.toFixed(d) : "—";
const fmtK    = (v) => isNum(v) ? `$${(v / 1000).toFixed(1)}k` : "—";
const pColor  = (v) => !isNum(v) ? T.t3 : v >= 0 ? C.green : C.red;

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "2-digit" });
  } catch { return "—"; }
}

function fmtRelative(iso) {
  if (!iso) return "—";
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const days = Math.floor(diff / 86400000);
    if (days === 0) return "today";
    if (days === 1) return "1d ago";
    if (days < 30)  return `${days}d ago`;
    const wks = Math.floor(days / 7);
    return `${wks}w ago`;
  } catch { return "—"; }
}

/* ─── KPI Card ───────────────────────────────────────────────────────────── */
function KpiCard({ label, value, sub, color, tooltip }) {
  const [hov, setHov] = useState(false);
  return (
    <div
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      title={tooltip}
      style={{
        background: C.card,
        border: `1px solid ${hov ? "rgba(37,99,235,0.28)" : C.border}`,
        borderRadius: 8,
        padding: "16px 18px",
        minWidth: 110,
        flex: 1,
        transition: "border-color .15s",
        cursor: tooltip ? "help" : "default",
      }}
    >
      <div style={{
        fontFamily: FONTS.mono, fontSize: 9, letterSpacing: ".10em",
        textTransform: "uppercase", color: T.t3, marginBottom: 8,
      }}>
        {label}
      </div>
      <div style={{
        fontFamily: FONTS.mono, fontSize: 22, fontWeight: 400,
        color: color || T.t1, letterSpacing: "-0.02em", lineHeight: 1,
      }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.t3, marginTop: 5, opacity: 0.65 }}>
          {sub}
        </div>
      )}
    </div>
  );
}

/* ─── Equity Curve Chart ─────────────────────────────────────────────────── */
function EquityCurve({ series, startEquity = 100_000 }) {
  if (!series || series.length < 2) {
    return (
      <div style={{
        height: 180, display: "flex", alignItems: "center", justifyContent: "center",
        background: C.card, borderRadius: 8, border: `1px solid ${C.border}`,
        fontFamily: FONTS.mono, fontSize: 10, color: T.t3, opacity: 0.5,
      }}>
        Accumulating signal history — equity curve appears after first closed positions
      </div>
    );
  }

  const maxEq  = Math.max(...series.map(p => p.equity));
  const minEq  = Math.min(...series.map(p => p.equity));
  const isPnl  = series[series.length - 1]?.equity >= startEquity;
  const stroke = isPnl ? C.green : C.red;

  const chartData = series.map((p, i) => ({
    i,
    equity:  p.equity,
    date:    fmtDate(p.date),
    symbol:  p.symbol,
    return:  p.return,
    label:   `${p.symbol ? p.symbol + " · " : ""}${p.return >= 0 ? "+" : ""}${p.return?.toFixed(2)}%`,
  }));

  return (
    <ResponsiveContainer width="100%" height={180}>
      <AreaChart data={chartData} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor={stroke} stopOpacity={0.18} />
            <stop offset="95%" stopColor={stroke} stopOpacity={0.01} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="rgba(255,255,255,0.03)" strokeDasharray="3 3" />
        <XAxis
          dataKey="date"
          tick={{ fontFamily: FONTS.mono, fontSize: 8, fill: T.t3 }}
          tickLine={false} axisLine={false}
          interval={Math.floor(chartData.length / 5)}
        />
        <YAxis
          domain={[minEq * 0.98, maxEq * 1.02]}
          tick={{ fontFamily: FONTS.mono, fontSize: 8, fill: T.t3 }}
          tickLine={false} axisLine={false}
          tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
          width={46}
        />
        <Tooltip
          contentStyle={{
            background: "rgba(5,7,22,0.95)",
            border: `1px solid ${C.border}`,
            borderRadius: 6,
            fontFamily: FONTS.mono, fontSize: 9,
          }}
          labelStyle={{ color: T.t3 }}
          formatter={(val, _, p) => [
            <span style={{ color: stroke }}>${val.toLocaleString()}</span>,
            p.payload.label,
          ]}
        />
        <ReferenceLine y={startEquity} stroke="rgba(255,255,255,0.08)" strokeDasharray="4 4" />
        <Area
          type="monotone" dataKey="equity"
          stroke={stroke} strokeWidth={1.5}
          fill="url(#eqGrad)"
          dot={false} activeDot={{ r: 3, fill: stroke }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

/* ─── Attribution Bar Chart ─────────────────────────────────────────────── */
function AttributionBar({ data, label }) {
  if (!data || Object.keys(data).length === 0) return null;

  const entries = Object.entries(data)
    .sort((a, b) => b[1].avg_return_pct - a[1].avg_return_pct)
    .slice(0, 8);

  const maxAbs = Math.max(...entries.map(([, v]) => Math.abs(v.avg_return_pct)), 0.1);

  return (
    <div>
      <div style={{ fontFamily: FONTS.mono, fontSize: 9, letterSpacing: ".10em", textTransform: "uppercase", color: T.t3, marginBottom: 10 }}>
        {label}
      </div>
      {entries.map(([key, v]) => {
        const pct    = v.avg_return_pct;
        const isPos  = pct >= 0;
        const width  = Math.abs(pct) / maxAbs * 100;
        return (
          <div key={key} style={{ marginBottom: 7 }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
              <span style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.t2 }}>{key}</span>
              <span style={{ display: "flex", gap: 10 }}>
                <span style={{ fontFamily: FONTS.mono, fontSize: 9, color: isPos ? C.green : C.red }}>
                  {fmtPct(pct)}
                </span>
                <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.t3, opacity: 0.6 }}>
                  {v.win_rate_pct}% WR · {v.trade_count}
                </span>
              </span>
            </div>
            <div style={{ height: 3, background: "rgba(255,255,255,0.05)", borderRadius: 2 }}>
              <div style={{
                height: "100%", width: `${width}%`, borderRadius: 2,
                background: isPos ? C.green : C.red,
                opacity: 0.65, transition: "width .4s ease",
              }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ─── Signal Journal Table ───────────────────────────────────────────────── */
const SIGNAL_COLOR = {
  "STRONG_OUTPERFORM": C.green,
  "OUTPERFORM":        "#6EE7B7",
};

function SignalRow({ sig, currentPrices }) {
  const isOpen    = !sig.exit_date;
  const entryPx   = sig.entry_price;
  const currPx    = currentPrices?.[sig.symbol];
  const unrealRet = isOpen && entryPx && currPx
    ? ((currPx - entryPx) / entryPx * 100)
    : null;
  const ret       = isOpen ? unrealRet : sig.return_pct;
  const retColor  = pColor(ret);
  const sigColor  = SIGNAL_COLOR[sig.signal] || T.t3;

  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "64px 1fr 72px 80px 72px 72px 80px",
      gap: 6,
      padding: "8px 12px",
      borderBottom: `1px solid rgba(255,255,255,0.04)`,
      alignItems: "center",
      transition: "background .12s",
    }}
      onMouseEnter={e => e.currentTarget.style.background = "rgba(37,99,235,0.04)"}
      onMouseLeave={e => e.currentTarget.style.background = "transparent"}
    >
      {/* Symbol */}
      <div>
        <div style={{ fontFamily: FONTS.display, fontSize: 12, fontWeight: 600, color: T.t1 }}>
          {sig.symbol}
        </div>
        <div style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.t3, marginTop: 1 }}>
          {sig.grade || "—"}
        </div>
      </div>

      {/* Signal + date */}
      <div>
        <span style={{
          fontFamily: FONTS.mono, fontSize: 8, fontWeight: 700, letterSpacing: ".05em",
          color: sigColor,
        }}>
          {sig.signal?.replace("_", " ") || "—"}
        </span>
        <div style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.t3, marginTop: 2 }}>
          {fmtDate(sig.signal_date)} · {sig.macro_regime?.replace("_", " ") || "—"}
        </div>
      </div>

      {/* CIS score */}
      <div style={{ textAlign: "right" }}>
        <div style={{ fontFamily: FONTS.mono, fontSize: 11, color: T.t2 }}>
          {isNum(sig.cis_score) ? sig.cis_score.toFixed(1) : "—"}
        </div>
        <div style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.t3 }}>CIS</div>
      </div>

      {/* Entry price */}
      <div style={{ textAlign: "right" }}>
        <div style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.t2 }}>
          {entryPx ? `$${entryPx < 1 ? entryPx.toFixed(4) : entryPx.toFixed(2)}` : "—"}
        </div>
        <div style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.t3 }}>entry</div>
      </div>

      {/* Return */}
      <div style={{ textAlign: "right" }}>
        <div style={{ fontFamily: FONTS.mono, fontSize: 11, color: retColor, fontWeight: 600 }}>
          {isNum(ret) ? fmtPct(ret) : "—"}
        </div>
        {isOpen && isNum(unrealRet) && (
          <div style={{ fontFamily: FONTS.mono, fontSize: 7, color: T.t3 }}>unrealized</div>
        )}
      </div>

      {/* Holding */}
      <div style={{ textAlign: "right" }}>
        <div style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.t2 }}>
          {isNum(sig.holding_days) ? `${sig.holding_days}d` : isOpen ? fmtRelative(sig.signal_date) : "—"}
        </div>
        <div style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.t3 }}>held</div>
      </div>

      {/* 30d Outcome */}
      <div style={{ textAlign: "center" }}>
        {sig.outcome_30d ? (
          <span style={{
            fontFamily: FONTS.mono, fontSize: 8, fontWeight: 700,
            padding: "2px 6px", borderRadius: 2,
            background: sig.outcome_30d === "WIN" ? "rgba(0,217,138,0.10)" :
                        sig.outcome_30d === "LOSS" ? "rgba(255,61,90,0.10)" :
                        "rgba(245,158,11,0.08)",
            color: sig.outcome_30d === "WIN" ? C.green :
                   sig.outcome_30d === "LOSS" ? C.red : C.amber,
            border: `1px solid ${sig.outcome_30d === "WIN" ? "rgba(0,217,138,0.20)" :
                                  sig.outcome_30d === "LOSS" ? "rgba(255,61,90,0.20)" :
                                  "rgba(245,158,11,0.15)"}`,
          }}>
            {sig.outcome_30d}
          </span>
        ) : (
          <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.t3, opacity: 0.3 }}>
            {isOpen ? "—" : "—"}
          </span>
        )}
      </div>

      {/* Status */}
      <div style={{ textAlign: "center" }}>
        {isOpen ? (
          <span style={{
            fontFamily: FONTS.mono, fontSize: 8, fontWeight: 700,
            padding: "2px 6px", borderRadius: 3,
            background: "rgba(0,217,138,0.08)", color: C.green,
            border: "1px solid rgba(0,217,138,0.18)",
          }}>
            OPEN
          </span>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 3 }}>
            <span style={{
              fontFamily: FONTS.mono, fontSize: 8,
              color: T.t3, opacity: 0.6,
            }}>
              {sig.exit_reason || "CLOSED"}
            </span>
            {sig.outcome_30d && (
              <span style={{
                fontFamily: FONTS.mono, fontSize: 7, fontWeight: 700,
                padding: "1px 5px", borderRadius: 2,
                background: sig.outcome_30d === "WIN" ? "rgba(0,217,138,0.12)" :
                            sig.outcome_30d === "LOSS" ? "rgba(255,61,90,0.12)" :
                            "rgba(245,158,11,0.10)",
                color: sig.outcome_30d === "WIN" ? C.green :
                       sig.outcome_30d === "LOSS" ? C.red : C.amber,
                border: `1px solid ${sig.outcome_30d === "WIN" ? "rgba(0,217,138,0.20)" :
                                      sig.outcome_30d === "LOSS" ? "rgba(255,61,90,0.20)" :
                                      "rgba(245,158,11,0.18)"}`,
              }}>
                {sig.outcome_30d}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/* ─── Status Banner ──────────────────────────────────────────────────────── */
function StatusBanner({ status, message, totalSignals, openSignals }) {
  if (status !== "building") return null;
  return (
    <div style={{
      padding: "14px 18px",
      background: "rgba(245,158,11,0.06)",
      border: "1px solid rgba(245,158,11,0.18)",
      borderRadius: 8,
      marginBottom: 24,
      display: "flex", alignItems: "center", gap: 14,
    }}>
      <div style={{ width: 6, height: 6, borderRadius: "50%", background: C.amber, flexShrink: 0 }} />
      <div>
        <div style={{ fontFamily: FONTS.mono, fontSize: 10, fontWeight: 700, color: C.amber, marginBottom: 3 }}>
          Track Record Building
        </div>
        <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.t3, lineHeight: 1.6 }}>
          {message || "Signal journal started. Metrics compute after first OUTPERFORM signals close."}
          {totalSignals > 0 && ` · ${openSignals || 0} open · ${(totalSignals || 0) - (openSignals || 0)} closed`}
        </div>
      </div>
    </div>
  );
}

/* ─── Skeleton ───────────────────────────────────────────────────────────── */
function Skeleton({ w = 80, h = 22 }) {
  return (
    <div style={{
      width: w, height: h, borderRadius: 4,
      background: "linear-gradient(90deg, rgba(14,30,56,0.8) 30%, rgba(18,38,72,0.9) 50%, rgba(14,30,56,0.8) 70%)",
      backgroundSize: "400px 100%",
      animation: "shimmer 1.8s ease infinite",
      display: "inline-block",
    }} />
  );
}

/* ─── Main Component ──────────────────────────────────────────────────────── */
export default function PerformanceDashboard() {
  const [perf,    setPerf]    = useState(null);
  const [signals, setSignals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [tab,     setTab]     = useState("overview");   // overview | journal | attribution
  const [journalStatus, setJournalStatus] = useState("all");  // all | open | closed
  const [journalPage,   setJournalPage]   = useState(0);
  const PAGE = 30;

  const fetchPerf = useCallback(async () => {
    try {
      const r = await fetch(`${API}/signals/performance`);
      if (r.ok) setPerf(await r.json());
    } catch { /* silent */ }
    finally { setLoading(false); }
  }, []);

  const fetchJournal = useCallback(async (status = "all", page = 0) => {
    try {
      const r = await fetch(
        `${API}/signals/journal?limit=${PAGE}&offset=${page * PAGE}&status=${status}`
      );
      if (r.ok) {
        const d = await r.json();
        setSignals(d.signals || []);
      }
    } catch { /* silent */ }
  }, []);

  useEffect(() => {
    fetchPerf();
    fetchJournal(journalStatus, journalPage);
    const iv = setInterval(() => { fetchPerf(); fetchJournal(journalStatus, journalPage); }, 300_000); // 5 min
    return () => clearInterval(iv);
  }, [fetchPerf, fetchJournal, journalStatus, journalPage]);

  const p = perf || {};
  const isBuilding = p.status === "building" || !p.status;
  // Prefer the HONEST benchmark-relative alpha curve; fall back to absolute. Same shape,
  // so the chart plots it unchanged. (Absolute craters in a down market — see backend note.)
  const usingAlpha = !!(p.alpha_equity_series && p.alpha_equity_series.length);
  const equitySeries = usingAlpha ? p.alpha_equity_series : (p.equity_series || []);
  const chartEnd = equitySeries.length ? equitySeries[equitySeries.length - 1].equity : 100_000;
  const closedCount  = p.closed_signals || 0;
  const openCount    = p.open_signals || 0;

  return (
    <div style={{ color: T.t1, paddingBottom: 32 }}>
      <style>{`@keyframes shimmer{0%{background-position:-400px 0}100%{background-position:400px 0}}`}</style>

      {/* ── Header ── */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontFamily: FONTS.display, fontSize: 13, fontWeight: 600, color: T.t1 }}>
              Signal Performance
            </span>
            <span style={{
              fontFamily: FONTS.mono, fontSize: 8, fontWeight: 700, letterSpacing: ".06em",
              padding: "2px 7px", borderRadius: 3,
              background: "rgba(148,163,184,0.10)",
              color: T.t3,
              border: "1px solid rgba(148,163,184,0.22)",
            }}>
              {isBuilding ? "BUILDING" : "PAPER · UNVALIDATED"}
            </span>
          </div>
          <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.t3, marginTop: 4, opacity: 0.65 }}>
            Observational signal track record — NOT live capital · {closedCount + openCount} total signals
          </div>
        </div>

        <div style={{ display: "flex", gap: 6 }}>
          <button onClick={fetchPerf} style={{
            fontFamily: FONTS.mono, fontSize: 9, color: T.t3, padding: "4px 10px",
            background: "transparent", border: `1px solid ${C.border}`, borderRadius: 4, cursor: "pointer",
          }}>
            Refresh
          </button>
        </div>
      </div>

      {/* ── Building banner ── */}
      <StatusBanner
        status={p.status}
        message={p.message}
        totalSignals={p.total_signals}
        openSignals={openCount}
      />

      {/* ── Provenance banner (S-252) ─────────────────────────────────────
          页面此前直接以 8 个红数字开场:−1.31 Sharpe · −38.30% DD · −26.19% 累计。
          而那些数是用 95 行算的,其中 83 行的出口价来自被禁价源
          (coingecko market_chart S-195 / yfinance 已死 S-230),可信的只有 12 行。

          12 个样本上的 Sharpe 是噪声的名字,不是战绩。那个 −26.19% 既不是坏消息
          也不是好消息 —— 它是一个不可测量的量被渲染成了一个可信的数,而它恰好
          指向自我贬低,所以从来没有人怀疑过它。

          不藏数字(the graveyard is the asset),但要先说清楚它测在什么上面。 */}
      {p.measurable && p.measurable.verdict !== "measured" && (
        <div style={{
          marginBottom: 16, padding: "12px 16px", borderRadius: 6,
          border: `1px solid ${C.amber}33`, background: `${C.amber}0a`,
        }}>
          <div style={{ fontFamily: FONTS.mono, fontSize: 10, color: C.amber,
                        fontWeight: 700, marginBottom: 6, letterSpacing: 0.4 }}>
            可测样本 {p.measurable.n_measurable} / {p.measurable.n_total}
            {" · "}不足以给出结论
          </div>
          <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.t3, lineHeight: 1.6 }}>
            下方数字用全部 {p.measurable.n_total} 条算出,其中{" "}
            <strong style={{ color: T.t2 }}>
              {(p.measurable.source_mix?.barred ?? 0) + (p.measurable.source_mix?.unsourced ?? 0)} 条
            </strong>{" "}
            的出口价来自我们自己规则里已禁用的价源,
            <strong style={{ color: T.t2 }}> {p.measurable.source_mix?.trusted ?? 0} 条</strong> 可信。
            按 ≥{p.measurable.min_measurable} 个可信样本的门槛,
            <strong style={{ color: C.amber }}> 我们现在既不能声称有效,也不能声称无效。</strong>
          </div>
        </div>
      )}

      {/* ── KPI Strip ── */}
      {p.measurable && p.measurable.verdict !== "measured" && (
        <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.t3, marginBottom: 6 }}>
          以下为<strong style={{ color: T.t2 }}>含被禁价源</strong>的计算结果 ·
          留作可审计记录 · <strong style={{ color: C.amber }}>不可对外声称</strong>
        </div>
      )}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 24,
                    opacity: p.measurable && p.measurable.verdict !== "measured" ? 0.72 : 1 }}>
        <KpiCard
          label={isNum(p.alpha_sharpe) ? "Alpha Sharpe" : "Sharpe Ratio"}
          value={loading ? <Skeleton w={50} /> : fmtNum(isNum(p.alpha_sharpe) ? p.alpha_sharpe : p.sharpe, 2)}
          sub={isNum(p.alpha_sharpe) ? "α vs BTC/SPY" : "risk-adj return"}
          color={(isNum(p.alpha_sharpe) ? p.alpha_sharpe : p.sharpe) >= 1.0 ? C.green : (isNum(p.alpha_sharpe) ? p.alpha_sharpe : p.sharpe) >= 0 ? C.amber : isNum(p.alpha_sharpe) || isNum(p.sharpe) ? C.red : T.t3}
          tooltip="Benchmark-relative alpha Sharpe. OUTPERFORM signals are RELATIVE claims — scoring absolute return in a down market understates them (that's the artifact). Fair measure = alpha vs BTC/SPY."
        />
        <KpiCard
          label="Sortino"
          value={loading ? <Skeleton w={50} /> : fmtNum(p.sortino, 2)}
          sub="downside-adj"
          color={isNum(p.sortino) ? (p.sortino >= 1.5 ? C.green : p.sortino >= 0 ? C.amber : C.red) : T.t3}
          tooltip="Like Sharpe but penalizes downside volatility only. > 1.5 is strong."
        />
        <KpiCard
          label="CAGR"
          value={loading ? <Skeleton w={50} /> : fmtPct(p.cagr_pct)}
          sub="annualized"
          color={pColor(p.cagr_pct)}
          tooltip="Compound annual growth rate of signal portfolio."
        />
        <KpiCard
          label="Max Drawdown"
          value={loading ? <Skeleton w={50} /> : fmtPct(p.max_drawdown_pct)}
          sub="worst peak→trough"
          color={isNum(p.max_drawdown_pct) ? (p.max_drawdown_pct > -10 ? C.green : p.max_drawdown_pct > -20 ? C.amber : C.red) : T.t3}
          tooltip="Largest peak-to-trough decline in cumulative signal P&L."
        />
        <KpiCard
          label={isNum(p.alpha_win_rate_pct) ? "Alpha Win Rate" : "Win Rate"}
          value={loading ? <Skeleton w={50} /> : isNum(p.alpha_win_rate_pct) ? `${p.alpha_win_rate_pct.toFixed(1)}%` : isNum(p.win_rate_pct) ? `${p.win_rate_pct.toFixed(1)}%` : "—"}
          sub={isNum(p.alpha_win_rate_pct) ? "beat benchmark 30d" : `${p.winning_signals || 0}W · ${p.losing_signals || 0}L`}
          color={(isNum(p.alpha_win_rate_pct) ? p.alpha_win_rate_pct : p.win_rate_pct) >= 55 ? C.green : (isNum(p.alpha_win_rate_pct) ? p.alpha_win_rate_pct : p.win_rate_pct) >= 40 ? C.amber : isNum(p.alpha_win_rate_pct) || isNum(p.win_rate_pct) ? C.red : T.t3}
          tooltip="Share of signals that beat their benchmark (BTC/SPY) over 30d — the fair measure for relative OUTPERFORM calls, vs the absolute win rate which collapses in a down market."
        />
        <KpiCard
          label="Profit Factor"
          value={loading ? <Skeleton w={50} /> : fmtNum(p.profit_factor, 2)}
          sub="gross profit / loss"
          color={isNum(p.profit_factor) ? (p.profit_factor >= 1.5 ? C.green : p.profit_factor >= 1 ? C.amber : C.red) : T.t3}
          tooltip="Gross profit ÷ gross loss. > 1.5 = strong edge. < 1.0 = net negative."
        />
        <KpiCard
          label="Avg Return"
          value={loading ? <Skeleton w={50} /> : fmtPct(p.avg_return_pct)}
          sub={`avg hold ${isNum(p.avg_holding_days) ? `${p.avg_holding_days}d` : "—"}`}
          color={pColor(p.avg_return_pct)}
          tooltip="Mean return per closed signal."
        />
        <KpiCard
          label="Portfolio"
          value={loading ? <Skeleton w={60} /> : fmtK(p.current_equity)}
          sub={`from $100k base`}
          color={isNum(p.current_equity) ? (p.current_equity >= 100_000 ? C.green : C.red) : T.t3}
          tooltip="Simulated $100k portfolio tracking cumulative signal returns."
        />
      </div>

      {/* ── 30d Outcome Summary (after first signals age out) ── */}
      {(p.outcome_30d_win_rate != null || p.outcome_30d_count > 0) && (
        <div style={{
          display: "flex", gap: 10, marginBottom: 20,
          background: C.card, border: `1px solid ${C.border}`,
          borderRadius: 8, padding: "12px 16px",
          flexWrap: "wrap",
        }}>
          <div style={{ fontFamily: FONTS.mono, fontSize: 8, letterSpacing: ".10em", textTransform: "uppercase", color: T.t3, alignSelf: "center", marginRight: 4 }}
               title={p.outcome_30d_basis === "benchmark_relative" ? "OUTPERFORM is a relative claim, so wins are scored as alpha vs benchmark (BTC for crypto, SPY for TradFi) — not absolute return." : "Absolute 30-day return."}>
            30d Outcomes{p.outcome_30d_basis === "benchmark_relative" ? " · vs BTC/SPY" : ""}
          </div>
          {[
            { label: "Resolved",  val: p.outcome_30d_count,        color: T.t2 },
            { label: p.outcome_30d_basis === "benchmark_relative" ? "Alpha Win" : "Win Rate", val: isNum(p.outcome_30d_win_rate) ? `${p.outcome_30d_win_rate.toFixed(0)}%` : "—", color: isNum(p.outcome_30d_win_rate) ? (p.outcome_30d_win_rate >= 55 ? C.green : p.outcome_30d_win_rate >= 40 ? C.amber : C.red) : T.t3 },
            { label: "Avg α",    val: isNum(p.outcome_30d_avg_alpha) ? fmtPct(p.outcome_30d_avg_alpha) : "—", color: pColor(p.outcome_30d_avg_alpha) },
            { label: "Avg Ret",  val: fmtPct(p.outcome_30d_avg_return), color: pColor(p.outcome_30d_avg_return) },
            { label: "W",        val: p.outcome_30d_wins || 0,   color: C.green },
            { label: "L",        val: p.outcome_30d_losses || 0,  color: C.red   },
          ].map(({ label, val, color }) => (
            <div key={label} style={{ textAlign: "center", minWidth: 52 }}>
              <div style={{ fontFamily: FONTS.mono, fontSize: 14, color, fontWeight: 600 }}>{val}</div>
              <div style={{ fontFamily: FONTS.mono, fontSize: 7, color: T.t3, opacity: 0.5, letterSpacing: ".08em" }}>{label}</div>
            </div>
          ))}
          {p.outcome_30d_pending > 0 && (
            <div style={{ textAlign: "center", minWidth: 52, alignSelf: "center", marginLeft: 4 }}>
              <div style={{ fontFamily: FONTS.mono, fontSize: 14, color: C.amber }}>{p.outcome_30d_pending}</div>
              <div style={{ fontFamily: FONTS.mono, fontSize: 7, color: T.t3, opacity: 0.5, letterSpacing: ".08em" }}>pending</div>
            </div>
          )}
        </div>
      )}

      {/* ── Tab bar ── */}
      <div style={{
        display: "flex", gap: 0, marginBottom: 20,
        borderBottom: `1px solid ${C.border}`,
      }}>
        {[["overview","Overview"],["journal","Signal Journal"],["attribution","Attribution"]].map(([k,l]) => (
          <button key={k} onClick={() => setTab(k)} style={{
            fontFamily: FONTS.mono, fontSize: 10, padding: "8px 16px",
            background: "transparent", border: "none",
            borderBottom: `2px solid ${tab === k ? C.cyan : "transparent"}`,
            color: tab === k ? C.cyan : T.t3, cursor: "pointer",
            letterSpacing: ".04em", transition: "all .15s",
          }}>
            {l}
          </button>
        ))}
      </div>

      {/* ── OVERVIEW tab ── */}
      {tab === "overview" && (
        <div>
          {/* Equity Curve */}
          <div style={{
            background: C.card, border: `1px solid ${C.border}`,
            borderRadius: 8, padding: "16px 18px", marginBottom: 20,
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 14 }}>
              <div style={{ fontFamily: FONTS.mono, fontSize: 9, letterSpacing: ".10em", textTransform: "uppercase", color: T.t3 }}>
                {usingAlpha ? "Cumulative Alpha vs BTC/SPY · $100k Base" : "Cumulative Signal Returns · $100k Base"}
              </div>
              {equitySeries.length > 0 && (
                <div style={{ fontFamily: FONTS.mono, fontSize: 12, color: chartEnd >= 100_000 ? C.green : C.red }}>
                  {fmtPct((chartEnd - 100_000) / 1000)} total
                </div>
              )}
            </div>
            <EquityCurve series={equitySeries} startEquity={100_000} />
            {equitySeries.length > 0 && (
              <div style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.t3, opacity: 0.4, marginTop: 8 }}>
                {usingAlpha ? "Each point = one resolved signal. Curve compounds benchmark-relative alpha (vs BTC/SPY) on $100k."
                            : "Each data point = one closed signal. Curve compounds $100k starting equity."}
              </div>
            )}
          </div>

          {/* Avg win/loss breakdown */}
          {(isNum(p.avg_win_pct) || isNum(p.avg_loss_pct)) && (
            <div style={{
              background: C.card, border: `1px solid ${C.border}`,
              borderRadius: 8, padding: "14px 18px", marginBottom: 20,
              display: "flex", gap: 28, flexWrap: "wrap",
            }}>
              {[
                { label: "Avg Win",  val: p.avg_win_pct,  color: C.green },
                { label: "Avg Loss", val: p.avg_loss_pct, color: C.red   },
                { label: "Calmar",   val: p.calmar,       color: isNum(p.calmar) && p.calmar > 0 ? C.green : C.red },
              ].map(({ label, val, color }) => (
                <div key={label}>
                  <div style={{ fontFamily: FONTS.mono, fontSize: 9, letterSpacing: ".08em", textTransform: "uppercase", color: T.t3, marginBottom: 5 }}>{label}</div>
                  <div style={{ fontFamily: FONTS.mono, fontSize: 18, color, letterSpacing: "-0.02em" }}>
                    {label === "Calmar" ? fmtNum(val, 2) : fmtPct(val)}
                  </div>
                </div>
              ))}
              <div>
                <div style={{ fontFamily: FONTS.mono, fontSize: 9, letterSpacing: ".08em", textTransform: "uppercase", color: T.t3, marginBottom: 5 }}>Open / Closed</div>
                <div style={{ fontFamily: FONTS.mono, fontSize: 18, color: T.t2, letterSpacing: "-0.02em" }}>
                  {openCount} / {closedCount}
                </div>
              </div>
            </div>
          )}

          {/* Regime attribution preview */}
          {p.by_regime && Object.keys(p.by_regime).length > 0 && (
            <div style={{
              background: C.card, border: `1px solid ${C.border}`,
              borderRadius: 8, padding: "16px 18px",
            }}>
              <AttributionBar data={p.by_regime} label="Performance by Macro Regime" />
            </div>
          )}
        </div>
      )}

      {/* ── SIGNAL JOURNAL tab ── */}
      {tab === "journal" && (
        <div>
          {/* Filter + pagination controls */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
            {[["all","All"],["open","Open"],["closed","Closed"]].map(([k,l]) => (
              <button key={k} onClick={() => { setJournalStatus(k); setJournalPage(0); fetchJournal(k, 0); }} style={{
                fontFamily: FONTS.mono, fontSize: 9, padding: "4px 10px", borderRadius: 4,
                border: `1px solid ${journalStatus === k ? "rgba(56,189,248,0.35)" : C.border}`,
                background: journalStatus === k ? "rgba(56,189,248,0.08)" : "transparent",
                color: journalStatus === k ? C.cyan : T.t3, cursor: "pointer", fontWeight: journalStatus === k ? 700 : 400,
              }}>
                {l}
              </button>
            ))}
            <div style={{ marginLeft: "auto", fontFamily: FONTS.mono, fontSize: 9, color: T.t3, opacity: 0.5 }}>
              {signals.length} signals
            </div>
          </div>

          {/* Table header */}
          <div style={{
            display: "grid",
            gridTemplateColumns: "64px 1fr 72px 80px 72px 72px 64px",
            gap: 6, padding: "6px 12px",
            borderBottom: `1px solid rgba(255,255,255,0.06)`,
          }}>
            {["Asset","Signal","CIS","Entry","Return","Held","30d","Status"].map(h => (
              <div key={h} style={{
                fontFamily: FONTS.mono, fontSize: 8, fontWeight: 600, letterSpacing: ".10em",
                textTransform: "uppercase", color: T.t3, opacity: 0.5,
                textAlign: ["CIS","Entry","Return","Held"].includes(h) ? "right" : "center",
              }}>
                {h}
              </div>
            ))}
          </div>

          {/* Rows */}
          {signals.length === 0 ? (
            <div style={{
              padding: "36px 0", textAlign: "center",
              fontFamily: FONTS.mono, fontSize: 10, color: T.t3, opacity: 0.5,
            }}>
              {loading ? "Loading signals…" : "No signals yet — CIS scheduler will populate this when OUTPERFORM assets appear."}
            </div>
          ) : (
            signals.map(sig => <SignalRow key={sig.id} sig={sig} currentPrices={{}} />)
          )}

          {/* Pagination */}
          {signals.length === PAGE && (
            <div style={{ display: "flex", justifyContent: "center", marginTop: 12 }}>
              <button onClick={() => { const next = journalPage + 1; setJournalPage(next); fetchJournal(journalStatus, next); }} style={{
                fontFamily: FONTS.mono, fontSize: 9, color: T.t3, padding: "4px 14px",
                background: "transparent", border: `1px solid ${C.border}`, borderRadius: 4, cursor: "pointer",
              }}>
                Next page
              </button>
            </div>
          )}
        </div>
      )}

      {/* ── ATTRIBUTION tab ── */}
      {tab === "attribution" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          {[
            [p.by_regime, "By Macro Regime"],
            [p.by_class,  "By Asset Class"],
            [p.by_grade,  "By CIS Grade"],
          ].map(([data, label]) => (
            data && Object.keys(data).length > 0 ? (
              <div key={label} style={{
                background: C.card, border: `1px solid ${C.border}`,
                borderRadius: 8, padding: "16px 18px",
              }}>
                <AttributionBar data={data} label={label} />
              </div>
            ) : (
              <div key={label} style={{
                background: C.card, border: `1px solid ${C.border}`,
                borderRadius: 8, padding: "16px 18px",
                fontFamily: FONTS.mono, fontSize: 9, color: T.t3, opacity: 0.45,
              }}>
                {label} · accumulating data
              </div>
            )
          ))}

          {/* Methodology note */}
          <div style={{
            gridColumn: "1 / -1",
            padding: "12px 16px", borderRadius: 8,
            background: "rgba(5,7,22,0.6)",
            border: `1px solid rgba(255,255,255,0.04)`,
          }}>
            <div style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.t3, lineHeight: 1.8, opacity: 0.6 }}>
              <strong style={{ color: T.t2, opacity: 1 }}>Methodology</strong> · Signals logged when CIS ≥ 60 (OUTPERFORM) or CIS ≥ 75 (STRONG OUTPERFORM).
              Signals close on downgrade (CIS &lt; 52). Entry/exit prices from the full-model feed (T1) or the market feed (T2).
              Equity curve compounds $100k notional across closed signal sequence.
              Sharpe and Sortino computed via empyrical (Quantopian open-source, period=signal).
              This is a signal track record, not a live trading account. Past signal performance does not guarantee future results.
            </div>
          </div>
        </div>
      )}

      {/* Footer */}
      <div style={{ marginTop: 24, fontFamily: FONTS.mono, fontSize: 8, color: T.t3, opacity: 0.3, letterSpacing: ".06em" }}>
        CometCloud AI · Signal Journal · empyrical open-source risk metrics · {p.as_of ? `as of ${fmtDate(p.as_of)}` : "live"}
      </div>
    </div>
  );
}
