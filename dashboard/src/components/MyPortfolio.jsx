/**
 * MyPortfolio — Personalized watchlist + P&L tracker
 *
 * Features:
 *   - Watchlist: pin any asset from the CIS universe (localStorage)
 *   - Position tracker: enter cost basis → live P&L vs current price
 *   - CIS grade change alerts: badge if grade shifted since added
 *   - Wallet-gated view (shows connect prompt if not signed in)
 *
 * Data:
 *   - Reads from cisUniverse prop (already fetched by parent App.jsx)
 *   - Persists watchlist + positions in localStorage as cc_portfolio
 *   - No extra API calls needed
 */

import { useState, useEffect, useCallback, useMemo } from "react";
import { useAuth } from "../context/AuthContext.jsx";
import { T, FONTS } from "../tokens";

// ── Constants ─────────────────────────────────────────────────────────────────
const LS_KEY = "cc_portfolio";
const GOLD   = "#C8A84B";
const GREEN  = "#00E87A";
const RED    = "#FF2D55";
const BLUE   = "#3894D2";

const GRADE_ORDER = ["A+", "A", "B+", "B", "C+", "C", "D", "F"];
const gradeColor = (g) => {
  if (!g) return T?.muted || "#666";
  if (g === "A+" || g === "A") return GREEN;
  if (g === "B+" || g === "B") return "#7FFFB2";
  if (g === "C+" || g === "C") return GOLD;
  if (g === "D") return "#FF8C42";
  return RED;
};

const signalColor = (s) => {
  if (!s) return T?.muted || "#666";
  if (s === "STRONG OUTPERFORM") return GREEN;
  if (s === "OUTPERFORM") return "#7FFFB2";
  if (s === "NEUTRAL") return GOLD;
  if (s === "UNDERPERFORM") return "#FF8C42";
  return RED;
};

const fmtPrice = (p) => {
  if (!p || p === 0) return "—";
  if (p >= 1000) return `$${p.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
  if (p >= 1)    return `$${p.toFixed(2)}`;
  return `$${p.toFixed(4)}`;
};

const fmtPct = (p) => {
  if (p == null) return "—";
  const sign = p >= 0 ? "+" : "";
  return `${sign}${p.toFixed(2)}%`;
};

const fmtUSD = (v) => {
  if (!v || isNaN(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1e6) return `${v >= 0 ? "+" : "-"}$${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${v >= 0 ? "+" : "-"}$${(abs / 1e3).toFixed(1)}K`;
  return `${v >= 0 ? "+" : "-"}$${abs.toFixed(2)}`;
};

// Normalize T1 / T2 field differences
function norm(a) {
  return {
    ...a,
    symbol:     a.asset_id || a.symbol || "?",
    name:       a.name || a.asset_id || a.symbol,
    score:      a.cis_score ?? a.score ?? 0,
    asset_class: a.asset_class || a.class || "—",
    price:      a.price || 0,
    change_24h: a.change_24h || 0,
  };
}

// ── Persistence ───────────────────────────────────────────────────────────────
function loadPortfolio() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    return raw ? JSON.parse(raw) : { watchlist: [], positions: {}, gradeSnapshot: {} };
  } catch { return { watchlist: [], positions: {}, gradeSnapshot: {} }; }
}

function savePortfolio(data) {
  try { localStorage.setItem(LS_KEY, JSON.stringify(data)); } catch {}
}

// ── Sub-components ────────────────────────────────────────────────────────────

function GradeBadge({ grade, prev }) {
  const color = gradeColor(grade);
  const prevIdx = GRADE_ORDER.indexOf(prev);
  const currIdx = GRADE_ORDER.indexOf(grade);
  const delta = prevIdx !== -1 && currIdx !== -1 ? prevIdx - currIdx : 0;
  const arrow = delta > 0 ? "↑" : delta < 0 ? "↓" : null;

  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      <span style={{
        fontFamily: FONTS.mono, fontSize: 11, fontWeight: 700,
        color, background: `${color}18`, border: `1px solid ${color}40`,
        borderRadius: 4, padding: "2px 6px",
      }}>
        {grade || "—"}
      </span>
      {arrow && (
        <span style={{
          fontSize: 10, fontWeight: 700,
          color: delta > 0 ? GREEN : RED,
        }}>
          {arrow}
        </span>
      )}
    </span>
  );
}

function WatchCard({ asset, position, onEdit, onRemove, prevGrade }) {
  const a = norm(asset);
  const price = a.price;
  const chg = a.change_24h;
  const chgColor = chg >= 0 ? GREEN : RED;

  // P&L calc
  const pos = position || {};
  const units    = parseFloat(pos.units   || 0);
  const entry    = parseFloat(pos.entry   || 0);
  const hasPnl   = units > 0 && entry > 0 && price > 0;
  const pnlUSD   = hasPnl ? (price - entry) * units : null;
  const pnlPct   = hasPnl ? ((price - entry) / entry) * 100 : null;

  return (
    <div style={{
      background: "rgba(255,255,255,0.025)",
      border: `1px solid rgba(255,255,255,0.07)`,
      borderRadius: 12,
      padding: "16px 18px",
      display: "flex", flexDirection: "column", gap: 10,
      position: "relative",
      transition: "border-color 0.2s",
    }}
    onMouseEnter={e => e.currentTarget.style.borderColor = "rgba(56,148,210,0.25)"}
    onMouseLeave={e => e.currentTarget.style.borderColor = "rgba(255,255,255,0.07)"}
    >
      {/* Remove button */}
      <button onClick={() => onRemove(a.symbol)} style={{
        position: "absolute", top: 10, right: 10,
        background: "none", border: "none", cursor: "pointer",
        color: "rgba(255,255,255,0.2)", fontSize: 14, padding: "2px 6px",
        borderRadius: 4, lineHeight: 1,
        transition: "color 0.15s",
      }}
      onMouseEnter={e => e.currentTarget.style.color = RED}
      onMouseLeave={e => e.currentTarget.style.color = "rgba(255,255,255,0.2)"}
      >
        ×
      </button>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div>
          <div style={{ fontFamily: FONTS.display, fontSize: 14, fontWeight: 700, color: "#EFF8FF" }}>
            {a.symbol}
          </div>
          <div style={{ fontFamily: FONTS.body, fontSize: 10, color: T.muted, marginTop: 1 }}>
            {a.name} · {a.asset_class}
          </div>
        </div>
      </div>

      {/* Score row */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <GradeBadge grade={a.grade} prev={prevGrade} />
        <span style={{
          fontFamily: FONTS.mono, fontSize: 11,
          color: signalColor(a.signal),
        }}>
          {a.signal || "—"}
        </span>
      </div>

      {/* Price row */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontFamily: FONTS.mono, fontSize: 13, fontWeight: 600, color: "#EFF8FF" }}>
          {fmtPrice(price)}
        </span>
        <span style={{ fontFamily: FONTS.mono, fontSize: 11, color: chgColor }}>
          {fmtPct(chg)} 24h
        </span>
      </div>

      {/* CIS score bar */}
      <div style={{ height: 2, background: "rgba(255,255,255,0.06)", borderRadius: 2 }}>
        <div style={{
          height: "100%", borderRadius: 2,
          width: `${Math.max(0, Math.min(100, a.score))}%`,
          background: gradeColor(a.grade),
          transition: "width 0.6s ease",
        }} />
      </div>
      <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.muted, marginTop: -6 }}>
        CIS {a.score?.toFixed(1) || "—"}
      </div>

      {/* P&L */}
      {hasPnl ? (
        <div style={{
          background: pnlUSD >= 0 ? "rgba(0,232,122,0.06)" : "rgba(255,45,85,0.06)",
          border: `1px solid ${pnlUSD >= 0 ? "rgba(0,232,122,0.15)" : "rgba(255,45,85,0.15)"}`,
          borderRadius: 6, padding: "6px 10px",
          display: "flex", justifyContent: "space-between", alignItems: "center",
        }}>
          <span style={{ fontFamily: FONTS.body, fontSize: 10, color: T.muted }}>
            {units} @ {fmtPrice(entry)}
          </span>
          <span style={{ fontFamily: FONTS.mono, fontSize: 11, fontWeight: 700,
            color: pnlUSD >= 0 ? GREEN : RED }}>
            {fmtUSD(pnlUSD)} · {fmtPct(pnlPct)}
          </span>
        </div>
      ) : (
        <button onClick={() => onEdit(a.symbol)} style={{
          background: "transparent",
          border: "1px dashed rgba(56,148,210,0.25)",
          borderRadius: 6, padding: "5px 10px",
          color: BLUE, fontFamily: FONTS.body, fontSize: 10, cursor: "pointer",
          transition: "all 0.15s",
          textAlign: "center",
        }}
        onMouseEnter={e => e.currentTarget.style.borderColor = "rgba(56,148,210,0.5)"}
        onMouseLeave={e => e.currentTarget.style.borderColor = "rgba(56,148,210,0.25)"}
        >
          + Add position
        </button>
      )}
    </div>
  );
}

// ── Position Edit Modal ───────────────────────────────────────────────────────
function PositionModal({ symbol, asset, existing, onSave, onClose }) {
  const a = asset ? norm(asset) : null;
  const [units, setUnits] = useState(existing?.units || "");
  const [entry, setEntry] = useState(existing?.entry || "");

  const pnlPct = a?.price && entry && units
    ? ((a.price - parseFloat(entry)) / parseFloat(entry)) * 100
    : null;

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 9000,
      background: "rgba(2,2,8,0.85)", backdropFilter: "blur(8px)",
      display: "flex", alignItems: "center", justifyContent: "center",
    }} onClick={onClose}>
      <div style={{
        background: "#060d1a", border: "1px solid rgba(56,148,210,0.2)",
        borderRadius: 16, padding: "28px 28px 24px",
        width: 320, position: "relative",
      }} onClick={e => e.stopPropagation()}>
        <div style={{ fontFamily: FONTS.display, fontSize: 15, fontWeight: 700, color: "#EFF8FF", marginBottom: 4 }}>
          {symbol} Position
        </div>
        {a && (
          <div style={{ fontFamily: FONTS.mono, fontSize: 11, color: T.muted, marginBottom: 20 }}>
            Current: {fmtPrice(a.price)} · Grade {a.grade}
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <label style={{ fontFamily: FONTS.body, fontSize: 11, color: T.secondary }}>
            Units / Quantity
            <input
              type="number" value={units} onChange={e => setUnits(e.target.value)}
              placeholder="e.g. 0.5"
              style={inputStyle}
            />
          </label>
          <label style={{ fontFamily: FONTS.body, fontSize: 11, color: T.secondary }}>
            Entry Price (USD)
            <input
              type="number" value={entry} onChange={e => setEntry(e.target.value)}
              placeholder="e.g. 62000"
              style={inputStyle}
            />
          </label>

          {pnlPct !== null && (
            <div style={{
              background: pnlPct >= 0 ? "rgba(0,232,122,0.06)" : "rgba(255,45,85,0.06)",
              border: `1px solid ${pnlPct >= 0 ? "rgba(0,232,122,0.2)" : "rgba(255,45,85,0.2)"}`,
              borderRadius: 8, padding: "8px 12px", textAlign: "center",
            }}>
              <span style={{ fontFamily: FONTS.mono, fontSize: 13, fontWeight: 700,
                color: pnlPct >= 0 ? GREEN : RED }}>
                {fmtPct(pnlPct)} unrealized
              </span>
            </div>
          )}
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 20 }}>
          <button onClick={onClose} style={{ ...btnBase, flex: 1, background: "rgba(255,255,255,0.04)", color: T.muted }}>
            Cancel
          </button>
          {existing && (
            <button onClick={() => onSave(symbol, null)} style={{ ...btnBase, background: "rgba(255,45,85,0.1)", color: RED, border: "1px solid rgba(255,45,85,0.2)" }}>
              Clear
            </button>
          )}
          <button
            onClick={() => onSave(symbol, { units: parseFloat(units) || 0, entry: parseFloat(entry) || 0 })}
            disabled={!units || !entry}
            style={{ ...btnBase, flex: 1, background: "rgba(200,168,75,0.15)", color: GOLD, border: "1px solid rgba(200,168,75,0.3)", opacity: (!units || !entry) ? 0.4 : 1 }}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

const inputStyle = {
  display: "block", width: "100%", marginTop: 6,
  background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.1)",
  borderRadius: 6, padding: "8px 10px",
  color: "#EFF8FF", fontFamily: FONTS.mono, fontSize: 12,
  outline: "none",
  boxSizing: "border-box",
};

const btnBase = {
  padding: "9px 16px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.1)",
  background: "transparent", cursor: "pointer", fontFamily: FONTS.display,
  fontSize: 12, fontWeight: 700, letterSpacing: "0.04em", transition: "all 0.15s",
};

// ── Asset Search ──────────────────────────────────────────────────────────────
function AssetSearch({ universe, watchlist, onAdd }) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  const results = useMemo(() => {
    if (!query.trim()) return [];
    const q = query.toLowerCase();
    return universe
      .filter(a => !watchlist.includes(a.symbol || a.asset_id))
      .filter(a => {
        const sym  = (a.symbol || a.asset_id || "").toLowerCase();
        const name = (a.name || "").toLowerCase();
        return sym.includes(q) || name.includes(q);
      })
      .slice(0, 8);
  }, [query, universe, watchlist]);

  return (
    <div style={{ position: "relative" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8,
        background: "rgba(255,255,255,0.04)", border: "1px solid rgba(56,148,210,0.2)",
        borderRadius: 8, padding: "8px 12px" }}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="rgba(56,148,210,0.6)" strokeWidth="2.5">
          <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
        </svg>
        <input
          value={query}
          onChange={e => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder="Search assets to watch…"
          style={{
            background: "none", border: "none", outline: "none",
            color: "#EFF8FF", fontFamily: FONTS.body, fontSize: 12,
            flex: 1,
          }}
        />
      </div>

      {open && results.length > 0 && (
        <div style={{
          position: "absolute", top: "calc(100% + 6px)", left: 0, right: 0,
          background: "#060d1a", border: "1px solid rgba(56,148,210,0.2)",
          borderRadius: 8, overflow: "hidden", zIndex: 500,
          boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
        }}>
          {results.map(a => {
            const n = norm(a);
            return (
              <div key={n.symbol}
                onMouseDown={() => { onAdd(n.symbol); setQuery(""); }}
                style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  padding: "9px 14px", cursor: "pointer",
                  borderBottom: "1px solid rgba(255,255,255,0.04)",
                  transition: "background 0.1s",
                }}
                onMouseEnter={e => e.currentTarget.style.background = "rgba(56,148,210,0.08)"}
                onMouseLeave={e => e.currentTarget.style.background = "transparent"}
              >
                <div>
                  <span style={{ fontFamily: FONTS.display, fontSize: 12, fontWeight: 700, color: "#EFF8FF" }}>
                    {n.symbol}
                  </span>
                  <span style={{ fontFamily: FONTS.body, fontSize: 10, color: T.muted, marginLeft: 8 }}>
                    {n.name}
                  </span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <GradeBadge grade={n.grade} />
                  <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.muted }}>
                    {n.asset_class}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Portfolio Summary Bar ─────────────────────────────────────────────────────
function SummaryBar({ watchedAssets, positions }) {
  const totals = useMemo(() => {
    let totalCost = 0, totalValue = 0, count = 0;
    watchedAssets.forEach(a => {
      const n = norm(a);
      const pos = positions[n.symbol];
      if (!pos || !pos.units || !pos.entry || !n.price) return;
      totalCost  += pos.units * pos.entry;
      totalValue += pos.units * n.price;
      count++;
    });
    const pnl    = totalValue - totalCost;
    const pnlPct = totalCost > 0 ? (pnl / totalCost) * 100 : 0;
    return { totalCost, totalValue, pnl, pnlPct, count };
  }, [watchedAssets, positions]);

  if (totals.count === 0) return null;

  const pnlPos = totals.pnl >= 0;

  return (
    <div style={{
      background: pnlPos ? "rgba(0,232,122,0.04)" : "rgba(255,45,85,0.04)",
      border: `1px solid ${pnlPos ? "rgba(0,232,122,0.12)" : "rgba(255,45,85,0.12)"}`,
      borderRadius: 10, padding: "12px 18px",
      display: "flex", flexWrap: "wrap", gap: "12px 32px", alignItems: "center",
    }}>
      <div style={{ fontFamily: FONTS.display, fontSize: 10, color: T.muted, letterSpacing: "0.1em", textTransform: "uppercase" }}>
        Portfolio Summary
      </div>
      {[
        { label: "Cost Basis",    value: `$${totals.totalCost.toLocaleString("en-US", { maximumFractionDigits: 0 })}` },
        { label: "Current Value", value: `$${totals.totalValue.toLocaleString("en-US", { maximumFractionDigits: 0 })}` },
        { label: "Unrealized P&L", value: `${fmtUSD(totals.pnl)} (${fmtPct(totals.pnlPct)})`,
          color: pnlPos ? GREEN : RED },
        { label: "Positions",     value: `${totals.count}` },
      ].map(({ label, value, color }) => (
        <div key={label}>
          <div style={{ fontFamily: FONTS.body, fontSize: 10, color: T.muted }}>{label}</div>
          <div style={{ fontFamily: FONTS.mono, fontSize: 13, fontWeight: 700, color: color || "#EFF8FF", marginTop: 1 }}>
            {value}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Empty State ───────────────────────────────────────────────────────────────
function EmptyState({ onFocus }) {
  return (
    <div style={{
      textAlign: "center", padding: "60px 24px",
      border: "1px dashed rgba(255,255,255,0.08)", borderRadius: 14,
    }}>
      <div style={{ fontSize: 32, marginBottom: 12, opacity: 0.4 }}>◎</div>
      <div style={{ fontFamily: FONTS.display, fontSize: 14, fontWeight: 700, color: T.secondary, marginBottom: 6 }}>
        Your watchlist is empty
      </div>
      <div style={{ fontFamily: FONTS.body, fontSize: 12, color: T.muted, maxWidth: 280, margin: "0 auto 20px" }}>
        Search for any asset from the CIS universe to track its score, grade, and P&L.
      </div>
      <button onClick={onFocus} style={{
        ...btnBase, color: BLUE,
        border: "1px solid rgba(56,148,210,0.3)",
        background: "rgba(56,148,210,0.06)",
      }}>
        + Add first asset
      </button>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────
export default function MyPortfolio({ cisUniverse = [] }) {
  const { isConnected, address } = useAuth();

  const [portfolio, setPortfolio] = useState(loadPortfolio);
  const [editSymbol, setEditSymbol] = useState(null);
  const [searchRef, setSearchRef] = useState(null);

  // Persist on change
  useEffect(() => { savePortfolio(portfolio); }, [portfolio]);

  // Universe map for quick lookup
  const universeMap = useMemo(() => {
    const m = {};
    cisUniverse.forEach(a => { m[a.symbol || a.asset_id] = a; });
    return m;
  }, [cisUniverse]);

  // Watched assets with live CIS data
  const watchedAssets = useMemo(() =>
    portfolio.watchlist
      .map(sym => universeMap[sym])
      .filter(Boolean),
    [portfolio.watchlist, universeMap]
  );

  const addToWatchlist = useCallback((symbol) => {
    setPortfolio(p => {
      if (p.watchlist.includes(symbol)) return p;
      const asset = universeMap[symbol];
      return {
        ...p,
        watchlist: [...p.watchlist, symbol],
        gradeSnapshot: {
          ...p.gradeSnapshot,
          [symbol]: asset?.grade || null,
        },
      };
    });
  }, [universeMap]);

  const removeFromWatchlist = useCallback((symbol) => {
    setPortfolio(p => {
      const { [symbol]: _g, ...gradeSnapshot } = p.gradeSnapshot;
      const { [symbol]: _pos, ...positions }   = p.positions;
      return { ...p, watchlist: p.watchlist.filter(s => s !== symbol), gradeSnapshot, positions };
    });
  }, []);

  const savePosition = useCallback((symbol, pos) => {
    setPortfolio(p => {
      if (!pos) {
        const { [symbol]: _, ...positions } = p.positions;
        return { ...p, positions };
      }
      return { ...p, positions: { ...p.positions, [symbol]: pos } };
    });
    setEditSymbol(null);
  }, []);

  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: "32px 24px" }}>

      {/* Header */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
          <div>
            <h2 style={{
              fontFamily: FONTS.display, fontSize: 22, fontWeight: 700,
              color: "#EFF8FF", margin: 0, letterSpacing: "-0.02em",
            }}>
              My Portfolio
            </h2>
            <p style={{ fontFamily: FONTS.body, fontSize: 12, color: T.muted, margin: "4px 0 0" }}>
              {isConnected
                ? `Watching ${portfolio.watchlist.length} asset${portfolio.watchlist.length !== 1 ? "s" : ""} · ${Object.keys(portfolio.positions).length} position${Object.keys(portfolio.positions).length !== 1 ? "s" : ""} tracked`
                : "Connect wallet to sync across devices"}
            </p>
          </div>

          {isConnected && (
            <div style={{
              display: "flex", alignItems: "center", gap: 6,
              background: "rgba(0,232,122,0.06)", border: "1px solid rgba(0,232,122,0.15)",
              borderRadius: 8, padding: "6px 12px",
            }}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: GREEN,
                boxShadow: `0 0 8px ${GREEN}`, flexShrink: 0, display: "inline-block" }} />
              <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: GREEN, fontWeight: 700 }}>
                {address?.slice(0,4)}…{address?.slice(-4)}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Data tier notice */}
      {cisUniverse.length === 0 && (
        <div style={{
          background: "rgba(200,168,75,0.06)", border: "1px solid rgba(200,168,75,0.2)",
          borderRadius: 8, padding: "10px 14px", marginBottom: 20,
          fontFamily: FONTS.body, fontSize: 11, color: GOLD,
        }}>
          ⚡ Loading CIS universe… Live prices will appear shortly.
        </div>
      )}

      {/* Summary bar */}
      {watchedAssets.length > 0 && (
        <div style={{ marginBottom: 20 }}>
          <SummaryBar watchedAssets={watchedAssets} positions={portfolio.positions} />
        </div>
      )}

      {/* Search */}
      <div style={{ marginBottom: 24 }} ref={setSearchRef}>
        <AssetSearch
          universe={cisUniverse}
          watchlist={portfolio.watchlist}
          onAdd={addToWatchlist}
        />
      </div>

      {/* Watchlist grid */}
      {watchedAssets.length === 0 ? (
        <EmptyState onFocus={() => searchRef?.querySelector("input")?.focus()} />
      ) : (
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
          gap: 14,
        }}>
          {watchedAssets.map(asset => {
            const n = norm(asset);
            return (
              <WatchCard
                key={n.symbol}
                asset={asset}
                position={portfolio.positions[n.symbol]}
                prevGrade={portfolio.gradeSnapshot[n.symbol]}
                onEdit={setEditSymbol}
                onRemove={removeFromWatchlist}
              />
            );
          })}
        </div>
      )}

      {/* Offline notice */}
      {!isConnected && watchedAssets.length > 0 && (
        <div style={{
          marginTop: 24, padding: "10px 14px",
          background: "rgba(56,148,210,0.04)", border: "1px solid rgba(56,148,210,0.12)",
          borderRadius: 8, fontFamily: FONTS.body, fontSize: 11, color: T.muted,
        }}>
          Connect your Phantom wallet to sync your watchlist across devices.
        </div>
      )}

      {/* Position edit modal */}
      {editSymbol && (
        <PositionModal
          symbol={editSymbol}
          asset={universeMap[editSymbol]}
          existing={portfolio.positions[editSymbol]}
          onSave={savePosition}
          onClose={() => setEditSymbol(null)}
        />
      )}
    </div>
  );
}
