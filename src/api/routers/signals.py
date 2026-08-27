"""
CIS Signal Journal — institutional-grade performance tracking.

Records every OUTPERFORM / STRONG OUTPERFORM threshold crossing as a
tradeable signal with entry price, tracks open positions, closes them
on downgrade, and computes empyrical risk metrics for the buy-side dashboard.

Endpoints:
  GET  /api/v1/signals/journal       — paginated signal history (open + closed)
  GET  /api/v1/signals/performance   — Sharpe, Sortino, CAGR, maxDD, win rate, equity curve
  GET  /api/v1/signals/summary       — quick KPI strip (cached 10 min)

Called internally by cis.py after /internal/cis-scores processing:
  log_cis_signals(assets, regime, prices)
  close_cis_signals(assets, prices)
"""
import os
import json
import logging
import math
import time
from datetime import datetime, timezone, timedelta

import httpx
import numpy as np

from fastapi import APIRouter, Query, Header, HTTPException, Response

_logger = logging.getLogger(__name__)
router  = APIRouter()

_INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")

# ── Config ────────────────────────────────────────────────────────────────────
_SB_URL    = os.environ.get("SUPABASE_URL", "").rstrip("/")
_SB_KEY    = os.environ.get("SUPABASE_KEY", "")
_SB_TABLE  = "signal_journal"

# Signal thresholds (same as CLAUDE.md CIS spec)
_OUTPERFORM_THRESH        = 60.0
_STRONG_OUTPERFORM_THRESH = 75.0
_EXIT_THRESH              = 52.0    # close when score falls below this
_STOP_LOSS_PCT            = -0.15   # close if unrealized < -15%
_MAX_HOLDING_DAYS         = 90      # force-close stale open signals

# Dedup: skip if open signal for same asset within N days
_DEDUP_DAYS = 3

# Redis cache key for performance metrics
_REDIS_PERF_KEY = "signals:performance"
_REDIS_PERF_TTL = 600   # 10 min

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=10)
    return _client


def _sb_headers() -> dict:
    return {
        "apikey":        _SB_KEY,
        "Authorization": f"Bearer {_SB_KEY}",
        "Content-Type":  "application/json",
        "Prefer":        "return=minimal",
    }


def _safe(v):
    """Sanitize float for JSON (replace NaN/Inf with None)."""
    if v is None:
        return None
    try:
        f = float(v)
        return None if not math.isfinite(f) else round(f, 6)
    except (TypeError, ValueError):
        return None


# ── Supabase helpers ─────────────────────────────────────────────────────────

async def _sb_query(table: str, params: dict) -> list:
    """GET from Supabase PostgREST."""
    if not _SB_URL or not _SB_KEY:
        return []
    try:
        resp = await _get_client().get(
            f"{_SB_URL}/rest/v1/{table}",
            params=params,
            headers={
                "apikey":        _SB_KEY,
                "Authorization": f"Bearer {_SB_KEY}",
            },
            timeout=8,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        _logger.warning(f"[SIGNALS] Supabase GET error: {e}")
    return []


async def _sb_insert(rows: list) -> bool:
    if not _SB_URL or not _SB_KEY or not rows:
        return False
    try:
        resp = await _get_client().post(
            f"{_SB_URL}/rest/v1/{_SB_TABLE}",
            content=json.dumps(rows),
            headers=_sb_headers(),
            timeout=8,
        )
        return resp.status_code in (200, 201)
    except Exception as e:
        _logger.warning(f"[SIGNALS] Insert error: {e}")
        return False


async def _sb_update(row_id: int, data: dict) -> bool:
    if not _SB_URL or not _SB_KEY:
        return False
    try:
        resp = await _get_client().patch(
            f"{_SB_URL}/rest/v1/{_SB_TABLE}",
            content=json.dumps(data),
            params={"id": f"eq.{row_id}"},
            headers=_sb_headers(),
            timeout=8,
        )
        return resp.status_code in (200, 201, 204)
    except Exception as e:
        _logger.warning(f"[SIGNALS] Update error: {e}")
        return False


async def _get_open_signals() -> dict:
    """Fetch all open signals keyed by symbol (uppercase)."""
    rows = await _sb_query(_SB_TABLE, {
        "exit_date": "is.null",
        "select": "id,symbol,entry_price,cis_score,signal_date,signal",
        "order": "signal_date.desc",
        "limit": "200",
    })
    result = {}
    for row in rows:
        sym = (row.get("symbol") or "").upper()
        if sym and sym not in result:   # keep most recent open per symbol
            result[sym] = row
    return result


# ── Signal logging (called from cis.py) ─────────────────────────────────────

async def log_cis_signals(assets: list, regime: str, prices: dict) -> int:
    """
    Called after /internal/cis-scores push.
    Checks each asset — if OUTPERFORM and no recent open signal, logs entry.
    Also closes open signals for assets that have fallen below exit threshold.

    assets  — list of asset dicts from CIS universe
    regime  — current macro regime string
    prices  — dict {SYMBOL: current_price_usd}
    Returns count of new signals logged.
    """
    if not _SB_URL or not _SB_KEY:
        return 0

    open_signals = await _get_open_signals()
    now = datetime.now(timezone.utc)
    new_rows   = []
    close_ops  = []

    for asset in assets:
        sym    = (asset.get("symbol") or asset.get("asset_id") or "").upper()
        score  = asset.get("cis_score") or asset.get("score") or 0
        signal = asset.get("signal") or ""
        grade  = asset.get("grade") or ""

        if not sym:
            continue

        is_outperform = (
            "OUTPERFORM" in signal.upper() or score >= _OUTPERFORM_THRESH
        )
        is_strong = (
            "STRONG" in signal.upper() or score >= _STRONG_OUTPERFORM_THRESH
        )
        is_downgrade = (score < _EXIT_THRESH) and not is_outperform

        price = prices.get(sym) or prices.get(sym.lower())

        # ── Close open signal on downgrade ──────────────────────────────────
        if sym in open_signals and is_downgrade:
            open_row  = open_signals[sym]
            entry_px  = open_row.get("entry_price")
            ret_pct   = None
            if entry_px and price and entry_px > 0:
                ret_pct = round((price - entry_px) / entry_px * 100, 4)
            entry_dt  = open_row.get("signal_date")
            hold_days = None
            if entry_dt:
                try:
                    dt_entry = datetime.fromisoformat(entry_dt.replace("Z", "+00:00"))
                    hold_days = round((now - dt_entry).total_seconds() / 86400, 2)
                except Exception:
                    pass

            close_ops.append((open_row["id"], {
                "exit_price":  _safe(price),
                "exit_date":   now.isoformat(),
                "exit_reason": "DOWNGRADE",
                "return_pct":  _safe(ret_pct),
                "holding_days": _safe(hold_days),
            }))

        # ── Open new signal if not already open ─────────────────────────────
        elif is_outperform and sym not in open_signals:
            row = {
                "symbol":       sym,
                "asset_class":  asset.get("asset_class"),
                "grade":        grade,
                "signal":       "STRONG_OUTPERFORM" if is_strong else "OUTPERFORM",
                "cis_score":    _safe(score),
                "raw_cis_score": _safe(asset.get("raw_cis_score")),
                "las":          _safe(asset.get("las")),
                "pillar_f":     _safe(asset.get("pillar_f") or (asset.get("pillars") or {}).get("F") or asset.get("f")),
                "pillar_m":     _safe(asset.get("pillar_m") or (asset.get("pillars") or {}).get("M") or asset.get("m")),
                "pillar_o":     _safe(asset.get("pillar_o") or (asset.get("pillars") or {}).get("O") or asset.get("o")),
                "pillar_s":     _safe(asset.get("pillar_s") or (asset.get("pillars") or {}).get("S") or asset.get("s")),
                "pillar_a":     _safe(asset.get("pillar_a") or (asset.get("pillars") or {}).get("A") or asset.get("a")),
                "macro_regime": regime or asset.get("macro_regime"),
                "strategy":     "CIS_THRESHOLD",
                "data_tier":    asset.get("data_tier", 2),
                "entry_price":  _safe(price),
                "exit_price":   None,
                "exit_date":    None,
                "exit_reason":  None,
                "return_pct":   None,
                "holding_days": None,
                "signal_date":  now.isoformat(),
                "recorded_at":  now.isoformat(),
            }
            new_rows.append(row)

    # Execute inserts + closes
    inserted = 0
    if new_rows:
        ok = await _sb_insert(new_rows)
        if ok:
            inserted = len(new_rows)
            _logger.info(f"[SIGNALS] Logged {inserted} new signals (regime={regime})")
        else:
            _logger.warning("[SIGNALS] Signal insert failed")

    for row_id, update_data in close_ops:
        ok = await _sb_update(row_id, update_data)
        if ok:
            sym_closed = next(
                (r["symbol"] for r in open_signals.values() if r.get("id") == row_id), "?"
            )
            _logger.info(f"[SIGNALS] Closed signal id={row_id} sym={sym_closed} reason=DOWNGRADE ret={update_data.get('return_pct')}%")

    return inserted


# ── Performance computation ───────────────────────────────────────────────────

def _compute_metrics(closed: list, open_signals: list) -> dict:
    """
    Compute institutional-grade performance metrics from signal history.
    Uses empyrical if available; falls back to numpy implementation.
    """
    if not closed:
        return {
            "status": "building",
            "message": "Accumulating signal history — metrics available after first closed positions.",
            "total_signals": len(open_signals),
            "open_signals":  len(open_signals),
            "closed_signals": 0,
            "outcome_30d_count": 0,
            "outcome_30d_pending": len(open_signals),
        }

    # Sanitize: a closed signal whose price feed returned 0 produces a -100% sentinel
    # (the known price=0 artifact). Drop those and clip extremes so one bad data point
    # can't masquerade as a -94% blow-up. Keep only economically plausible returns.
    _raw = [r["return_pct"] for r in closed
            if r.get("return_pct") is not None and r["return_pct"] > -99.0]
    returns = np.array([max(-90.0, min(500.0, float(x))) / 100.0 for x in _raw])
    if len(returns) == 0:
        return {"status": "building", "message": "Waiting for valid price data on closed signals.", "total_signals": len(closed) + len(open_signals)}

    wins        = returns[returns > 0]
    losses      = returns[returns <= 0]
    win_rate    = round(len(wins) / len(returns) * 100, 1)
    avg_return  = round(float(np.mean(returns)) * 100, 3)
    avg_win     = round(float(np.mean(wins)) * 100, 3) if len(wins) else 0
    avg_loss    = round(float(np.mean(losses)) * 100, 3) if len(losses) else 0

    # Profit factor = gross profit / gross loss
    gross_profit = float(np.sum(wins)) if len(wins) else 0
    gross_loss   = abs(float(np.sum(losses))) if len(losses) else 0
    profit_factor = round(gross_profit / gross_loss, 3) if gross_loss > 0 else None

    # Equity curve — each signal sized as an equal slug of a diversified book, NOT a
    # full-notional sequential bet. Compounding each signal at 100% notional made one
    # bad signal wipe the curve (the -94% artifact). A signal-following book holds many
    # positions concurrently; model each as a fixed fraction so the curve reflects the
    # set's efficacy, not a single name's blow-up.
    POSITION_FRAC = 0.10
    equity_curve = []
    equity = 100_000.0
    peak   = equity
    max_dd = 0.0
    for r in returns:
        equity = equity * (1.0 + POSITION_FRAC * r)
        peak   = max(peak, equity)
        dd     = (equity - peak) / peak
        max_dd = min(max_dd, dd)
        equity_curve.append(round(equity, 2))

    # CAGR — annualized from first to last signal
    dates = [r["signal_date"] for r in closed if r.get("signal_date")]
    cagr  = None
    if len(dates) >= 2:
        try:
            dt0 = datetime.fromisoformat(dates[-1].replace("Z", "+00:00"))
            dt1 = datetime.fromisoformat(dates[0].replace("Z", "+00:00"))
            years = (dt1 - dt0).total_seconds() / (365.25 * 86400)
            if years > 0.05 and equity_curve:
                cagr = round((equity_curve[-1] / 100_000) ** (1 / years) - 1, 4)
        except Exception:
            pass

    # Per-signal Sharpe — mean / std of trade returns. NOTE: these are sparse,
    # event-driven signal returns, NOT daily periods, so we do NOT annualize.
    # (QA 2026-06-05: the old sqrt(252)/empyrical period="daily" annualization
    # exploded this to -24.5 — a nonsensical magnitude.) This reports a unitless
    # per-trade risk-adjusted return, which is the honest metric for a signal log.
    sharpe = None
    if len(returns) >= 5 and np.std(returns) > 0:
        sharpe = round(float(np.mean(returns) / np.std(returns)), 3)

    # Per-signal Sortino — mean / downside deviation (no annualization, same reason)
    sortino = None
    if len(returns) >= 5:
        neg = returns[returns < 0]
        if len(neg) > 0 and np.std(neg) > 0:
            sortino = round(float(np.mean(returns) / np.std(neg)), 3)

    # Calmar — CAGR / |maxDD|
    calmar = None
    if cagr is not None and max_dd < 0:
        calmar = round(cagr / abs(max_dd), 3)

    # Attribution by regime — CANONICALISE FIRST (S-248).
    #
    # 这里原本是 `reg = r.get("macro_regime") or "Unknown"`,拿原始字符串分组。
    # 实测 2026-08-27,库里同一个 regime 存着两种拼写:
    #
    #     EASING  n=1475 α=−1.43  ‖  Easing  n=1185 α=−5.43   差  4.00pp
    #     RISK_ON n= 856 α=+5.83  ‖  Risk-On n= 330 α=−6.17   差 12.01pp,符号相反
    #
    # 而拼写切换发生在 **2025-06-17**(`Risk-On` 覆盖 05-24→06-17,
    # `RISK_ON` 覆盖 06-29→10-09)。所以那不是两个 regime,是**两段相邻时间窗** ——
    # 这张「按 regime 归因」的表,有一部分在测时代而不是在测 regime,
    # 而标题不会告诉读者这件事。
    #
    # 合并了哪几种拼写要跟着结果走(`merged_spellings`),否则读者无从判断
    # 某一行是不是刚被合并过 —— 那是可审计性,不是装饰。
    # 写者路径必须用 strict:未知拼写返回 None → "UNKNOWN" 桶,而不是被悄悄折成
    # NEUTRAL(那是合法 regime,会让不可测的量冒充可测的 — S-123 / seth-vdb-r12-reply)。
    from src.data.cis.cis_provider import canonical_regime_strict

    by_regime: dict = {}
    _regime_spellings: dict = {}
    for r in closed:
        raw = r.get("macro_regime")
        reg = canonical_regime_strict(raw) or "UNKNOWN"
        ret = r.get("return_pct")
        if ret is None:
            continue
        if reg not in by_regime:
            by_regime[reg] = {"returns": [], "count": 0}
        by_regime[reg]["returns"].append(ret)
        by_regime[reg]["count"] += 1
        _regime_spellings.setdefault(reg, set()).add(str(raw))

    regime_stats = {}
    for reg, v in by_regime.items():
        rets = np.array(v["returns"])
        regime_stats[reg] = {
            "avg_return_pct": round(float(np.mean(rets)), 2),
            "win_rate_pct":   round(len(rets[rets > 0]) / len(rets) * 100, 1),
            "trade_count":    v["count"],
            # 每个数自报它测在什么上面 (S-248)。这一格用的是 return_pct ——
            # entry→exit 的绝对收益,持仓期由 exit_reason 决定(实测均值 8-12 天),
            # 【不是】同屏那个 30 天窗口的 α。同一块面板上两个数说着不同的话时,
            # 至少要让读者看得出它们说的不是同一件事。
            "measure": "exit_return_pct",
        }
        spellings = sorted(_regime_spellings.get(reg, ()))
        if len(spellings) > 1:
            # 这一行是合并出来的 —— 说出来,否则读者无从判断它是不是刚被合并过。
            regime_stats[reg]["merged_spellings"] = spellings

    # Attribution by asset class
    by_class: dict = {}
    for r in closed:
        cls = r.get("asset_class") or "Unknown"
        ret = r.get("return_pct")
        if ret is None:
            continue
        if cls not in by_class:
            by_class[cls] = {"returns": [], "count": 0}
        by_class[cls]["returns"].append(ret)
        by_class[cls]["count"] += 1

    class_stats = {}
    for cls, v in by_class.items():
        rets = np.array(v["returns"])
        class_stats[cls] = {
            "avg_return_pct": round(float(np.mean(rets)), 2),
            "win_rate_pct":   round(len(rets[rets > 0]) / len(rets) * 100, 1),
            "trade_count":    v["count"],
        }

    # Attribution by grade
    by_grade: dict = {}
    for r in closed:
        g   = r.get("grade") or "?"
        ret = r.get("return_pct")
        if ret is None:
            continue
        if g not in by_grade:
            by_grade[g] = {"returns": [], "count": 0}
        by_grade[g]["returns"].append(ret)
        by_grade[g]["count"] += 1

    grade_stats = {}
    for g, v in by_grade.items():
        rets = np.array(v["returns"])
        grade_stats[g] = {
            "avg_return_pct": round(float(np.mean(rets)), 2),
            "win_rate_pct":   round(len(rets[rets > 0]) / len(rets) * 100, 1),
            "trade_count":    v["count"],
        }

    # ── 30d outcome metrics ──────────────────────────────────────────────
    #outcome_30d signals: those with outcome_30d set (computed by signal_outcome_tracker)
    resolved_signals = [r for r in closed if r.get("outcome_30d") in ("WIN", "LOSS", "EXPIRED")]

    def _measurable_block(rows: list) -> dict:
        """能被声称的那一部分 —— 按价源分层,样本不足时给原因不给数 (S-252)。

        `track_record.measure()` 已经做完全部判断;这里只是把它接上,
        不在这里重实现 —— 今天已经因为"写了第四个 regime 规范化实现"
        被守卫抓过一次 (S-249)。
        """
        try:
            from src.data.signals.track_record import (
                MEASURE_ALPHA30, MIN_MEASURABLE, measure)
            trusted = measure(rows, which=MEASURE_ALPHA30, trusted_only=True)
            allrows = measure(rows, which=MEASURE_ALPHA30, trusted_only=False)
            out = trusted.as_payload()
            out["min_measurable"] = MIN_MEASURABLE
            # 被禁价源那部分【也报】,但明确标成不可声称 —— 藏起来等于假装没测过,
            # 而 CLAUDE.md 说 the graveyard is the asset。
            out["including_barred_sources"] = {
                "mean_pct": allrows.mean_pct,
                "win_rate_pct": allrows.win_rate_pct,
                "n": allrows.n_measurable,
                "claimable": False,
                "why_not": "83/95 行的出口价来自 coingecko market_chart(S-195,"
                           "采样点塌缩不是收盘)或 yfinance(S-230,已死)。"
                           "按我们自己的规则,这个数不能对外声称。",
            }
            return out
        except Exception as e:                                    # noqa: BLE001
            _logger.warning("[SIGNALS] measurable block failed: %s", e)
            # 算不出来时说算不出来,不要退回一个数
            return {"verdict": "unknown", "reason": "分层计算失败,详见日志"}
    pending_signals  = [r for r in open_signals if not r.get("outcome_30d")]
    out_wins   = [r for r in resolved_signals if r.get("outcome_30d") == "WIN"]
    out_losses = [r for r in resolved_signals if r.get("outcome_30d") == "LOSS"]
    out_exp    = [r for r in resolved_signals if r.get("outcome_30d") == "EXPIRED"]

    out_count     = len(resolved_signals)
    out_win_rate  = round(len(out_wins) / out_count * 100, 1) if out_count > 0 else None
    # NOTE: .get(key, 0) does NOT protect against key present with value None (EXPIRED
    # signals have return_pct_30d=None) — np.mean([..., None]) then 500s. Filter Nones.
    _r30 = [r.get("return_pct_30d") for r in resolved_signals if r.get("return_pct_30d") is not None]
    out_avg_ret   = round(float(np.mean(_r30)) / 100.0 * 100, 3) if _r30 else None
    # Benchmark-relative: WIN/LOSS now reflect alpha vs benchmark (BTC/SPY), not absolute
    # return — an OUTPERFORM signal is a relative claim (see outcome_tracker.py).
    _alphas = [r.get("alpha_30d") for r in resolved_signals if r.get("alpha_30d") is not None]
    out_avg_alpha = round(float(np.mean(_alphas)), 3) if _alphas else None

    outcome_stats = {
        "outcome_30d_count":     out_count,
        "outcome_30d_win_rate":  out_win_rate,          # now benchmark-relative
        "outcome_30d_basis":     "benchmark_relative" if _alphas else "absolute",
        "outcome_30d_avg_return": out_avg_ret,          # absolute, reference
        "outcome_30d_avg_alpha":  out_avg_alpha,        # avg outperformance vs benchmark
        "outcome_30d_wins":       len(out_wins),
        "outcome_30d_losses":     len(out_losses),
        "outcome_30d_expired":    len(out_exp),
        "outcome_30d_pending":    len(pending_signals) + sum(1 for r in closed if r.get("outcome_30d") is None and r.get("return_pct") is None),
    }

    # HONEST primary track record — benchmark-relative ALPHA. These are OUTPERFORM signals
    # (relative claims); scoring their ABSOLUTE return in a down/Tightening market is what
    # produces the −0.89-Sharpe / 2.6%-win-rate artifact. Lead the UI with alpha_*, not the
    # absolute sleeve. (Output-layer honesty — the absolute fields are kept for reference.)
    _aa = np.array(_alphas, dtype=float) if _alphas else np.array([])
    alpha_sharpe = (round(float(_aa.mean() / _aa.std() * np.sqrt(12)), 3)
                    if _aa.size > 3 and _aa.std() > 0 else None)
    alpha_win_rate = round(float((_aa > 0).mean() * 100), 1) if _aa.size else None

    # Equity curve with dates for chart.
    #
    # Sized by POSITION_FRAC like every other compounding loop in this function
    # (2026-08-19). It was not, and the omission is the interesting part: the
    # correction that introduced POSITION_FRAC landed on `equity_curve` above —
    # which feeds max_drawdown and CAGR — and on NEITHER of the two dated series
    # the chart actually renders. **The fix reached the statistics and missed the
    # picture.** Found only because a guard written for the alpha series swept
    # every compounding loop instead of the one that prompted it.
    equity_series = []
    eq = 100_000.0
    for r in closed:
        ret = r.get("return_pct")
        if ret is None:
            continue
        eq  = eq * (1 + POSITION_FRAC * (ret / 100.0))
        equity_series.append({
            "date":   r.get("exit_date") or r.get("signal_date"),
            "equity": round(eq, 2),
            "symbol": r.get("symbol"),
            "return": ret,
        })

    # Alpha equity curve — compounds benchmark-relative alpha. Alpha is the fair
    # curve for relative OUTPERFORM signals: the absolute series craters simply for
    # being long in a down market.
    #
    # ── SAME SIZING AS THE ABSOLUTE CURVE, AND IT WAS MISSING (2026-08-19) ──────
    # The absolute `equity_curve` above was fixed to size each signal as a fraction
    # of a diversified book, with a comment naming the failure it removed: "one bad
    # signal wipe[s] the curve (the -94% artifact)". THAT FIX WAS NEVER APPLIED
    # HERE. This loop compounded each signal at FULL notional, and the frontend
    # explicitly prefers this series and labels it "the HONEST curve".
    #
    # Measured on the live page 2026-08-19: 84 resolved signals, average 30d alpha
    # −4.09%. Compounded at full notional, 0.9591^84 = 0.030 → the chart read
    # **−97.45%**, while the MAX DRAWDOWN stat on the same screen read −37.31%
    # because that one comes from the fixed curve. Two curves, one page,
    # contradicting each other — and the wrong one is the one on the chart.
    #
    # The defect class is the point: the fix was applied to the INSTANCE, not the
    # class. Same shape as eleven missing tables, a probe that only checked reads,
    # and a schema_version defaulted in one writer and not the other. Whenever a
    # correction lands, the question is which OTHER call sites share the flaw.
    #
    # 84 resolved signals over ~85 days at 8.3 days average hold means roughly ten
    # positions are open at once — they are concurrent, not sequential, so a signal
    # can only ever move a slice of the book. POSITION_FRAC is defined once above
    # and reused here on purpose: two curves on one page must not disagree about
    # how large a position is.
    #
    # ⚠️ THIS DOES NOT MAKE THE SIGNALS GOOD. At 0.10 the curve reads about −29%
    # instead of −97%. The chart was wrong AND the underlying is negative: 26.6%
    # alpha win rate, −4.09% average 30d alpha. Fixing an artifact on top of a real
    # problem must not be mistaken for fixing the problem.
    alpha_equity_series = []
    aeq = 100_000.0
    for r in sorted(resolved_signals, key=lambda x: (x.get("exit_date") or x.get("signal_date") or "")):
        a = r.get("alpha_30d")
        if a is None:
            continue
        aeq *= (1 + POSITION_FRAC * (a / 100.0))
        alpha_equity_series.append({"date": r.get("exit_date") or r.get("signal_date"),
                                    "equity": round(aeq, 2), "symbol": r.get("symbol"), "alpha": a})

    avg_holding = None
    hold_days = [r.get("holding_days") for r in closed if r.get("holding_days") is not None]
    if hold_days:
        avg_holding = round(float(np.mean(hold_days)), 1)

    return {
        "status":          "live",
        "as_of":           datetime.now(timezone.utc).isoformat(),
        # HONEST primary track record — benchmark-relative alpha (fair measure of OUTPERFORM
        # signals). The absolute sharpe/win_rate below reflect a doomed long-only sleeve in a
        # down market and should NOT headline the UI.
        # ── 可测量的那一部分 (S-252) ────────────────────────────────────────
        # 页面此前用 95 行算出 −1.31 Sharpe / −26.19% 并把它当作战绩展示。
        # 而那 95 行里 **83 行用被禁价源**(coingecko market_chart S-195 /
        # yfinance 已死 S-230),可信的只有 12 行。12 个样本上的 Sharpe
        # 是噪声的名字,不是结论。
        #
        # 更糟的是它指向自我贬低,所以没人怀疑过它 —— 一个说自己不行的数字
        # 不会引发审查。**那个 −26.19% 既不是坏消息也不是好消息,
        # 它是一个不可测量的量被渲染成了一个可信的数。**
        #
        # 这里不改任何算法,只把"能声称的"和"不能声称的"分开报,
        # 让前端能先说可测样本有多少,再谈数字。
        "measurable": _measurable_block(resolved_signals),
        # ── 每个头条数字的度量口径 (S-248) ──────────────────────────────────
        # 实测 2026-08-27,同一条统计条上四个数用了三种度量,而 UI 没有逐项标注:
        #
        #     ALPHA SHARPE  −1.31    ← alpha_30d(30 天窗口,已减基准)
        #     ALPHA WIN     28.2%    ← outcome_30d(30 天窗口)
        #     MAX DRAWDOWN  −38.30%  ← 绝对 equity_curve(8 天退出价复利)
        #     AVG RETURN    −3.44%   ← return_pct(8 天退出,不含基准)
        #
        # 而 `signals.py` 上方的注释自己就写着「Two curves, one page,
        # contradicting each other」—— 问题被记录过,没有被消除,也没有标出来。
        #
        # 更要紧的是持仓期不一致:退出规则平均 8 天(exit_reason 几乎全是
        # DOWNGRADE),而判定窗口是 30 天。实测 23 个 WIN 行里 **12 个**
        # `return_pct<0` 而 `return_pct_30d>0` —— 曲线和胜率在同一批样本上符号相反。
        #
        # 这个 map 不改任何数,只让前端能逐项标注,读者不再把三种度量读成一种。
        "measure_basis": {
            "alpha_sharpe":        "alpha_30d · 30d window · benchmark-relative",
            "alpha_win_rate_pct":  "outcome_30d · 30d window · benchmark-relative",
            "avg_alpha_pct":       "alpha_30d · 30d window · benchmark-relative",
            "sharpe":              "return_pct · exit-based (~8d hold) · absolute",
            "win_rate_pct":        "return_pct · exit-based (~8d hold) · absolute",
            "max_drawdown_pct":    "return_pct · exit-based (~8d hold) · absolute",
            "avg_return_pct":      "return_pct · exit-based (~8d hold) · absolute",
            "_note": ("持仓期与判定窗口不一致:退出规则均值约 8 天,判定窗口 30 天。"
                      "23 个 WIN 样本里 12 个两种度量符号相反 (S-248)。"),
        },
        "alpha_sharpe":        alpha_sharpe,
        "alpha_win_rate_pct":  alpha_win_rate,
        "avg_alpha_pct":       out_avg_alpha,
        "headline_basis":      "benchmark_relative_alpha",
        "headline_note":       "Lead with alpha_* — absolute metrics reflect a long-only sleeve in a Tightening market. Live validated market-neutral track record: /api/v1/signals/causal-paper.",
        # Core KPIs (absolute — reference only)
        "sharpe":          sharpe,
        "sortino":         sortino,
        "cagr_pct":        round(cagr * 100, 2) if cagr is not None else None,
        "max_drawdown_pct": round(max_dd * 100, 2),
        "calmar":          calmar,
        "win_rate_pct":    win_rate,
        "profit_factor":   profit_factor,
        "avg_return_pct":  avg_return,
        "avg_win_pct":     avg_win,
        "avg_loss_pct":    avg_loss,
        "avg_holding_days": avg_holding,
        # Signal counts
        "total_signals":   len(closed) + len(open_signals),
        "closed_signals":  len(closed),
        "open_signals":    len(open_signals),
        "winning_signals": int(len(wins)),
        "losing_signals":  int(len(losses)),
        # Equity
        "starting_equity": 100_000,
        "current_equity":  round(equity_curve[-1], 2) if equity_curve else 100_000,
        "equity_series":   equity_series[-120:],   # absolute (reference)
        "alpha_equity_series": alpha_equity_series[-120:],   # HONEST curve — chart should use this
        # Attribution
        "by_regime":       regime_stats,
        "by_class":        class_stats,
        "by_grade":        grade_stats,
        # 30d outcome metrics (populated by signal_outcome_tracker.py after 30d)
        **outcome_stats,
        # Honest methodology framing (QA 2026-06-05). Closed-signal returns here
        # come from the DOWNGRADE-CLOSE path: a signal closes when its score falls
        # below the exit threshold. Winners that never downgrade stay open, so this
        # sample is selection-biased toward losers and is NOT a clean track record.
        # The forward, unbiased metric is the 30-day fixed-horizon outcome
        # (outcome_30d_*), which only becomes meaningful once signals mature
        # (first signals logged 2026-05-25 → first 30d outcomes ~2026-06-24).
        "methodology": {
            "closed_basis": "downgrade_close",
            "closed_basis_note": "selection-biased toward losers; not a track record",
            "forward_metric": "outcome_30d (30-day fixed horizon)",
            "forward_metric_ready": out_count >= 10,
            "forward_metric_first_resolves": "2026-06-24",
        },
    }


# ── REST endpoints ────────────────────────────────────────────────────────────

@router.get("/api/v1/signals/journal")
async def get_signal_journal(
    limit: int  = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    status: str = Query(default="all"),    # all | open | closed
    symbol: str = Query(default=None),
):
    """
    Paginated signal history with open/closed filter.
    Returns latest signals first.
    """
    params = {
        "order":  "signal_date.desc",
        "limit":  str(limit),
        "offset": str(offset),
        "select": "id,symbol,asset_class,grade,signal,cis_score,macro_regime,strategy,data_tier,entry_price,exit_price,exit_date,exit_reason,return_pct,holding_days,signal_date",
    }
    if status == "open":
        params["exit_date"] = "is.null"
    elif status == "closed":
        params["exit_date"] = "not.is.null"
    if symbol:
        params["symbol"] = f"eq.{symbol.upper()}"

    rows = await _sb_query(_SB_TABLE, params)
    return {
        "signals": rows,
        "count":   len(rows),
        "offset":  offset,
        "limit":   limit,
        "filter":  status,
    }


async def assemble_briefing(symbol: str = None) -> dict:
    """Assemble the tiered briefing from cached intelligence. Returns BOTH the rendered
    `sections` (with deterministic template narrative + a stable `id` per item) AND the
    compact `ai_facts` the LLM narrator writes prose from. Shared by the live feed endpoint
    and the background AI-briefing loop so both see identical structure/facts."""
    from src.api.store import redis_get_key
    now = datetime.now(timezone.utc).isoformat()
    sections = []
    ai_items = []   # compact facts for the LLM (id + numbers, NO prose)

    wl = await redis_get_key("conviction:watchlist") or {}
    pos = await redis_get_key("cis:positioning") or {}
    cis = await redis_get_key("cis:local_scores") or {}
    regime = (cis.get("macro") or {}).get("regime") or cis.get("macro_regime") or "Unknown"

    # crowding read for the context headline
    crowded_long = crowded_short = None
    cl_p = cs_p = 0.0
    if isinstance(pos, dict) and pos:
        rk = sorted(((s, (v or {}).get("positioning_pressure", 0)) for s, v in pos.items() if isinstance(v, dict)), key=lambda kv: kv[1])
        if rk:
            crowded_long, cl_p = rk[0]              # most negative pressure = crowded LONGS
            crowded_short, cs_p = rk[-1]            # most positive = crowded SHORTS

    # ── Market Context (tier 0 — the frame) ── (plain prose — NO markdown; feed renders text as-is)
    frame = (f"Macro regime is {regime}. The diversification that matters lives across asset "
             f"classes, not inside crypto — commodities sit ~0.22 correlated to BTC while crypto majors "
             f"co-move at ~0.79. ")
    if crowded_long:
        frame += f"Leverage is crowded long in {crowded_long} (flush risk on any shock)"
        frame += f" and crowded short in {crowded_short} (squeeze fuel). " if crowded_short else ". "
    sections.append({"tier": "context", "title": "Market Context",
                     "items": [{"id": "context:regime", "headline": f"{regime} — breadth beats beta",
                                "narrative": frame.strip(), "source": "Regime & Breadth", "timestamp": now}]})
    ai_items.append({"id": "context:regime", "kind": "market_context", "regime": regime,
                     "crowded_long": crowded_long, "crowded_short": crowded_short,
                     "crypto_btc_corr": 0.79, "commodity_btc_corr": 0.22,
                     "point": "cross-asset breadth matters more than crypto beta this regime"})

    # ── Conviction Watch (the next structural winner — thesis narrative) ──
    conv = []
    for c in (wl.get("candidates") or [])[:4]:
        if (c.get("conviction_score") or 0) <= 0.03:
            continue
        drivers = c.get("drivers") or []
        confirming = c.get("L4_trend", 0) > 0.6
        # compose without repetition (de-stutter the shared "reflexive loop" phrasing)
        _bits = []
        _th = (c.get("thesis") or "").strip()
        if _th:
            _bits.append(_th.rstrip(".") + ".")
        if drivers:
            _bits.append(f"The market is already voting — {drivers[0].strip().rstrip('.')}.")
        _fund = "Fundamentals accelerating" if (c.get("L3_fundamental_momentum") or 0) > 0.5 else "Fundamentals steady"
        _price = "price is confirming" if confirming else "price not yet confirming"
        _bits.append(f"{_fund}; {_price}.")
        if c.get("reflexive_loop") and not any("reflex" in (d or "").lower() for d in drivers):
            _bits.append("A reflexive fee→token loop reinforces it.")
        _bits.append("A discretionary conviction candidate — the setup, not a signal.")
        narrative = " ".join(_bits)
        iid = f"conviction:{c['symbol']}"
        conv.append({"id": iid, "symbol": c["symbol"], "headline": f"{c['symbol']} — structural-winner watch",
                     "narrative": narrative, "score": c.get("conviction_score"),
                     "layers": {"moat": c.get("L1_moat_quality"), "catalyst": c.get("L2_catalyst"),
                                "fundamentals": c.get("L3_fundamental_momentum"), "trend": c.get("L4_trend")},
                     "source": "Conviction Engine", "timestamp": wl.get("as_of") or now})
        ai_items.append({"id": iid, "kind": "conviction_candidate", "symbol": c["symbol"],
                         "thesis": (c.get("thesis") or "")[:200], "drivers": drivers[:3],
                         "moat_quality": c.get("L1_moat_quality"), "catalyst": c.get("L2_catalyst"),
                         "fundamental_momentum": c.get("L3_fundamental_momentum"), "trend": c.get("L4_trend"),
                         "reflexive_loop": bool(c.get("reflexive_loop")),
                         "note": "discretionary conviction candidate, not a signal"})
    if conv:
        sections.append({"tier": "conviction", "title": "Conviction Watch — the next structural winner", "items": conv})

    # ── Positioning & Flow (the story, not the number) ──
    posn = []
    if crowded_long:
        posn.append({"id": f"positioning:{crowded_long}", "symbol": crowded_long,
                     "headline": f"{crowded_long} — leveraged longs crowded",
                     "narrative": f"Positioning pressure {cl_p:+.2f}: leverage is one-sided long in {crowded_long}. "
                                  "Crowded longs are the fuel for a flush — vulnerable if the tape turns. We'd fade "
                                  "strength here, not chase it.", "direction": "UNDERPERFORM",
                     "source": "Positioning", "timestamp": now})
        ai_items.append({"id": f"positioning:{crowded_long}", "kind": "positioning", "symbol": crowded_long,
                         "crowding": "long", "pressure": round(cl_p, 2), "direction": "UNDERPERFORM",
                         "point": "crowded longs = flush risk if tape turns; fade strength, don't chase"})
    if crowded_short and crowded_short != crowded_long:
        posn.append({"id": f"positioning:{crowded_short}", "symbol": crowded_short,
                     "headline": f"{crowded_short} — shorts crowded, squeeze setup",
                     "narrative": f"Positioning pressure {cs_p:+.2f}: shorts are crowded in {crowded_short}. "
                                  "A crowded short is squeeze fuel — a catalyst can force covering. Watch for a "
                                  "volume-confirmed reversal.", "direction": "OUTPERFORM",
                     "source": "Positioning", "timestamp": now})
        ai_items.append({"id": f"positioning:{crowded_short}", "kind": "positioning", "symbol": crowded_short,
                         "crowding": "short", "pressure": round(cs_p, 2), "direction": "OUTPERFORM",
                         "point": "crowded shorts = squeeze fuel; watch for volume-confirmed reversal"})
    if posn:
        sections.append({"tier": "positioning", "title": "Positioning & Flow", "items": posn})

    # ── Cross-Asset Shifts (grade migration as narrative, NOT a CIS re-print) ──
    uni = cis.get("assets") or cis.get("universe") or []
    shifts = []
    if uni:
        def _sig(a): return (a.get("signal") or "").upper()
        strong = [a for a in uni if "STRONG OUTPERFORM" in _sig(a)]
        weak = [a for a in uni if "UNDERWEIGHT" in _sig(a) or "UNDERPERFORM" in _sig(a)]
        if strong:
            s_syms = [(a.get('symbol') or '').upper() for a in strong[:4]]
            shifts.append({"id": "cross:strong", "headline": "Where quality is strongest now",
                           "narrative": f"Across the {len(uni)}-asset universe, {', '.join(s_syms)} carry the strongest "
                                        f"quality reads in the {regime} regime — the names positioned best if the "
                                        f"tape turns constructive. (Regime lens and relative positioning only.)",
                           "symbols": s_syms, "source": "Cross-Asset", "timestamp": now})
            ai_items.append({"id": "cross:strong", "kind": "cross_asset_strength", "symbols": s_syms,
                             "regime": regime, "universe_size": len(uni),
                             "point": "strongest quality reads; regime lens, relative positioning only"})
        if weak:
            w_syms = [(a.get('symbol') or '').upper() for a in weak[:4]]
            shifts.append({"id": "cross:weak", "headline": "Where quality is eroding",
                           "narrative": f"{', '.join(w_syms)} are weakening across the universe — structural or positioning "
                                        f"drag. In a {regime} regime these are underweight candidates, not dip-buys.",
                           "symbols": w_syms, "source": "Cross-Asset", "timestamp": now})
            ai_items.append({"id": "cross:weak", "kind": "cross_asset_weakness", "symbols": w_syms,
                             "regime": regime, "point": "quality eroding; underweight candidates, not dip-buys"})
    if shifts:
        sections.append({"tier": "cross_asset", "title": "Cross-Asset Shifts", "items": shifts})

    # ── Tracked Calls (our own directional calls + honest outcomes) ──
    _sym = {"symbol": f"eq.{symbol.upper()}"} if symbol else {}
    closed_rows = await _sb_query(_SB_TABLE, {"exit_date": "not.is.null", "order": "signal_date.desc", "limit": "300", **_sym,
        "select": "id,symbol,grade,signal,macro_regime,signal_date,alpha_30d"})
    open_rows = await _sb_query(_SB_TABLE, {"exit_date": "is.null", "order": "signal_date.desc", "limit": "12", **_sym,
        "select": "id,symbol,grade,signal,macro_regime,signal_date"})
    calls = []
    for r in (open_rows or [])[:8]:
        sig = (r.get("signal") or "").upper()
        sym_u = (r.get("symbol") or "").upper()
        calls.append({"id": f"call:{sym_u}", "symbol": sym_u, "direction": sig or "NEUTRAL",
                      "headline": f"{sym_u} — {sig or 'NEUTRAL'}",
                      "narrative": f"Our positioning call in the {r.get('macro_regime') or regime} regime "
                                   f"(grade {r.get('grade') or '—'}). Resolves benchmark-relative at 30d; tracked below.",
                      "source": "CIS Intelligence", "timestamp": r.get("signal_date")})
    scored = [r for r in (closed_rows or []) if r.get("alpha_30d") is not None
              and (("OUTPERFORM" in (r.get("signal") or "").upper()) or ("UNDER" in (r.get("signal") or "").upper()))]
    hits = sum(1 for r in scored if (("OUTPERFORM" in r["signal"].upper() and "UNDER" not in r["signal"].upper() and r["alpha_30d"] > 0)
                                     or ("UNDER" in r["signal"].upper() and r["alpha_30d"] < 0)))
    n = len(scored)
    accuracy = {"resolved_30d_directional_pct": round(hits / n * 100, 1) if n else None, "n": n,
                "avg_alpha_30d_pct": round(sum(r["alpha_30d"] for r in scored) / n, 2) if n else None}
    if calls:
        sections.append({"tier": "calls", "title": "Our Tracked Calls (self-verifying)", "items": calls, "accuracy": accuracy})

    ai_facts = {"regime": regime, "accuracy": accuracy, "items": ai_items,
                "house_view": "the edge is breadth + positioning, not beta"}
    return {"now": now, "regime": regime, "sections": sections, "accuracy": accuracy, "ai_facts": ai_facts}


def _overlay_ai(sections: list, ai: dict) -> str:
    """Overlay LLM-written prose onto the deterministic sections, matched by item id. Returns
    the narrative_source ('ai' or 'template'). Numbers/symbols/directions are never touched."""
    items = (ai or {}).get("items") or {}
    if not items:
        return "template"
    hit = False
    for sec in sections:
        for it in sec.get("items") or []:
            prose = items.get(it.get("id"))
            if prose:
                it["narrative"] = prose
                it["ai"] = True
                hit = True
    return "ai" if hit else "template"


@router.get("/api/v1/signals/feed")
async def get_signal_feed(limit: int = Query(default=40, le=100),
                          symbol: str = Query(default=None), response: Response = None):
    """Signal feed v5 — a STRUCTURED, TIERED, NARRATIVE intelligence briefing (not a scoreboard,
    not a duplicate of CIS). Sections, each item a mini-story with CONTEXT ("what's happening")
    and NARRATIVE ("why it matters"), so a user or agent reads it without decoding us:
      · Market Context (regime + the week's frame)
      · Conviction Watch (the next structural winner — thesis narrative)
      · Positioning & Flow (funding crowding — the story, not the number)
      · Cross-Asset Shifts (grade migrations as narrative, not a per-asset scoreboard)
      · Tracked Calls (our own directional calls + honest resolved outcomes)
    The PROSE is AI-written (MiniMax / LM Studio) over deterministic, compliance-safe facts,
    cached to Redis by a background loop so the request stays fast; degrades to template
    narrative when the model is unreachable. Positioning language only; not advice."""
    if response is not None:
        response.headers["Cache-Control"] = "public, max-age=180, stale-while-revalidate=900"
    from src.api.store import redis_get_key
    b = await assemble_briefing(symbol)
    sections, now, regime, accuracy = b["sections"], b["now"], b["regime"], b["accuracy"]

    # overlay cached AI narrative (written by the background loop / Mac-side push), if fresh
    narrative_source = "template"
    ai_model = None
    headline = None
    try:
        ai = await redis_get_key("signal:ai_briefing")
        if isinstance(ai, dict) and (int(time.time()) - int(ai.get("_ts", 0))) < 7200:
            narrative_source = _overlay_ai(sections, ai)
            ai_model = ai.get("model")
            if narrative_source == "ai" and ai.get("headline"):
                headline = ai["headline"]
    except Exception as e:
        _logger.warning(f"[FEED] AI overlay skipped: {e}")

    if not headline:
        headline = f"{regime} regime — the edge is in breadth and positioning, not beta."

    # flattened view (mobile / simple consumers) — carries the narrative, not just a score
    flat = []
    for sec in sections:
        for it in (sec.get("items") or []):
            flat.append({"symbol": it.get("symbol"), "direction": it.get("direction"),
                         "headline": it.get("headline"), "narrative": it.get("narrative"),
                         "category": sec["tier"], "source": it.get("source"), "status": "live",
                         "outcome": it.get("outcome"), "timestamp": it.get("timestamp")})
    return {"version": "5.0-briefing", "generated_at": now, "regime": regime, "headline": headline,
            "accuracy": accuracy, "n_sections": len(sections), "sections": sections,
            "count": len(flat), "signals": flat[:limit],
            "narrative_source": narrative_source, "narrative_model": ai_model,
            "compliance": "positioning language only; conviction items are discretionary candidates, not advice"}


async def refresh_ai_briefing() -> dict:
    """Background job: assemble facts → LLM writes prose → cache to Redis `signal:ai_briefing`.
    Called by the startup loop AND on-demand via /internal/refresh-briefing. No-op (returns
    skipped) when no LLM endpoint is configured, so the feed simply uses templates."""
    from src.data.narrative.llm_narrator import compose_ai_briefing, configured
    if not configured():
        return {"status": "skipped", "reason": "no LLM endpoint (NARRATIVE_LLM_BASE_URL / LLM_BASE_URL unset)"}
    b = await assemble_briefing()
    ai = await compose_ai_briefing(b["ai_facts"])
    if not ai:
        return {"status": "unavailable", "reason": "model returned no compliant narrative; feed uses templates"}
    ai["_ts"] = int(time.time())
    try:
        from src.api.store import redis_set_key
        await redis_set_key("signal:ai_briefing", ai, ttl=7200)
    except Exception as e:
        _logger.warning(f"[FEED] cache AI briefing failed: {e}")
        return {"status": "generated_uncached", "coverage": ai.get("coverage")}
    _logger.info(f"[FEED] AI briefing refreshed — {ai.get('coverage')} items, model={ai.get('model')}")
    return {"status": "ok", "coverage": ai.get("coverage"), "model": ai.get("model")}


@router.post("/internal/refresh-briefing")
async def refresh_briefing_endpoint(x_internal_token: str = Header(None)):
    """Internal: regenerate the AI narrative now (also lets Mac-side/Minimax trigger a refresh)."""
    if not _INTERNAL_TOKEN or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    return await refresh_ai_briefing()


@router.post("/internal/ai-briefing")
async def push_ai_briefing(payload: dict, x_internal_token: str = Header(None)):
    """Internal: Mac-side (Minimax) pushes an AI-written briefing directly. Body:
    {headline?, items:{item_id: narrative}, model?}. Compliance-gated on read via _overlay_ai
    (we still only overlay onto known ids). Stored to Redis `signal:ai_briefing`."""
    if not _INTERNAL_TOKEN or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    items = payload.get("items")
    if not isinstance(items, dict) or not items:
        raise HTTPException(status_code=400, detail="items:{id:narrative} required")
    # compliance scrub — drop any item whose prose carries advice language
    from src.data.narrative.llm_narrator import _clean
    clean_items = {k: _clean(v) for k, v in items.items()}
    clean_items = {k: v for k, v in clean_items.items() if v}
    if not clean_items:
        raise HTTPException(status_code=422, detail="all items failed compliance scrub")
    doc = {"headline": _clean(payload.get("headline") or ""), "items": clean_items,
           "model": payload.get("model") or "mac-push", "coverage": f"{len(clean_items)}/{len(items)}",
           "_ts": int(time.time())}
    from src.api.store import redis_set_key
    await redis_set_key("signal:ai_briefing", doc, ttl=7200)
    return {"status": "ok", "stored": len(clean_items), "model": doc["model"]}


@router.get("/api/v1/signals/performance")
async def get_signal_performance():
    """
    Institutional-grade performance metrics computed from signal_journal.
    Sharpe, Sortino, CAGR, max drawdown, win rate, profit factor, equity curve.
    Cached 10 minutes in Redis.
    """
    # Try Redis cache first
    try:
        from src.api.store import redis_get_key, redis_set_key
        cached = await redis_get_key(_REDIS_PERF_KEY)
        if cached and cached.get("status") == "live":
            age = int(time.time()) - cached.get("_cached_at", 0)
            if age < _REDIS_PERF_TTL:
                return {**cached, "cache_age_s": age}
    except Exception:
        pass

    # Fetch closed signals (last 180 days, ordered oldest→newest for equity curve)
    closed = await _sb_query(_SB_TABLE, {
        "exit_date": "not.is.null",
        "order":     "signal_date.asc",
        "limit":     "500",
        "select":    "id,symbol,asset_class,grade,signal,cis_score,macro_regime,return_pct,holding_days,signal_date,exit_date,exit_reason,entry_price,exit_price,outcome_30d,return_pct_30d,alpha_30d,benchmark_symbol",
    })

    # Fetch open signals
    open_rows = await _sb_query(_SB_TABLE, {
        "exit_date": "is.null",
        "order":     "signal_date.desc",
        "limit":     "100",
        "select":    "id,symbol,asset_class,grade,signal,cis_score,macro_regime,entry_price,signal_date,outcome_30d",
    })

    # Never 500 the flagship page — degrade to a graceful "building" status if the
    # metric computation raises on some data shape (customer-facing robustness).
    try:
        result = _compute_metrics(closed, open_rows)
    except Exception as e:
        _logger.warning(f"[SIGNALS] performance compute failed: {e}", exc_info=True)
        return {"status": "building",
                "message": "Performance metrics are recomputing.",
                "total_signals": len(closed) + len(open_rows),
                "closed_signals": len(closed), "open_signals": len(open_rows)}
    result["_cached_at"] = int(time.time())

    # Cache result
    try:
        from src.api.store import redis_set_key
        await redis_set_key(_REDIS_PERF_KEY, result, ttl=_REDIS_PERF_TTL)
    except Exception:
        pass

    return result


@router.post("/internal/run-outcome-tracker")
async def run_outcome_tracker_endpoint(
    dry_run: bool = Query(default=False),
    limit: int = Query(default=500, le=2000),
    x_internal_token: str = Header(None),
):
    """
    Resolve 30-day directional outcomes for matured signals (WIN/LOSS/EXPIRED).
    Internal-only — guarded by INTERNAL_TOKEN. Idempotent; safe to call repeatedly.
    Also runs automatically once/day via the startup background task.
    """
    if not _INTERNAL_TOKEN or not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    from src.data.signals.outcome_tracker import run_outcome_tracker
    result = await run_outcome_tracker(dry_run=dry_run, limit=limit)
    # bust the cached performance metrics so the new outcomes surface immediately
    if not dry_run and result.get("rows_written"):
        try:
            from src.api.store import redis_set_key
            await redis_set_key(_REDIS_PERF_KEY, {"status": "stale"}, ttl=1)
        except Exception:
            pass
    return result


@router.get("/api/v1/signals/summary")
async def get_signal_summary():
    """
    Lightweight KPI strip — for embedding in other pages.
    Cached in Redis; fast response.
    """
    perf = await get_signal_performance()
    return {
        "status":          perf.get("status"),
        "sharpe":          perf.get("sharpe"),
        "sortino":         perf.get("sortino"),
        "cagr_pct":        perf.get("cagr_pct"),
        "max_drawdown_pct": perf.get("max_drawdown_pct"),
        "win_rate_pct":    perf.get("win_rate_pct"),
        "profit_factor":   perf.get("profit_factor"),
        "total_signals":   perf.get("total_signals"),
        "open_signals":    perf.get("open_signals"),
        "closed_signals":  perf.get("closed_signals"),
        "current_equity":  perf.get("current_equity"),
        "as_of":           perf.get("as_of"),
    }


@router.get("/api/v1/signals/track-record")
async def get_signal_track_record(response: Response = None):
    """
    The honest, defensible track record: 30-day BENCHMARK-RELATIVE outcomes of our
    DIRECTIONAL signals (STRONG OUTPERFORM / OUTPERFORM / UNDERPERFORM /
    UNDERWEIGHT), computed entirely from our own data (cis_scores × ohlcv_daily),
    refreshed daily by the Supabase RPC refresh_signal_track_record (v2, 2026-07-26;
    MINIMAX_SYNC §BETA-METRIC-AGG).

    Two layers, labelled. Each tier exposes both RAW and β-ADJ aggregates:

      - RAW (`avg_alpha_pct`): what an UNHEDGED holder of the asset experiences,
        computed as `a_ret − b_ret`. This is the pre-R62 metric; it conflates
        alpha with leveraged beta in a high-β universe (our avg β ≈ 1.49 — R62).

      - β-ADJ (`avg_edge_beta_adj_pct`): the HEDGED excess return. Capturing
        it requires shorting the benchmark at the PIT-estimated β. PIT-safe
        expanding-window OLS, ≥20 priors, NEVER default β=1.0 (insufficient
        history → NULL — the row is honestly excluded from n_beta_adj).

    SHIP GATE: when ohlcv_daily is stale (>=36 h since last_trade_date), the
    β-ADJ headline is SUPPRESSED rather than published β-correct-but-STALE.
    The RAW block stays published — it's a pre-R62 number either way, and the
    ship verdict block says so explicitly. The gate auto-opens the moment
    the daily collector writes a fresh trade_date.

    Reading guide (which rows are real edges):
      STRONG OUTPERFORM  — top conviction; β-ADJ expected positive.
      OUTPERFORM         — broad tier; β-ADJ expected positive but smaller.
      UNDERPERFORM       — negative-edge tier; β-ADJ treats negative alpha as a
                            correct call, so positive β-ADJ is the edge.
      UNDERWEIGHT        — the one KNOWN defect (R62 t = −3.56); do not size.

    Consuming agents and investor pages should cite the tier breakdown
    under both raw AND β-ADJ headings, NOT a blended headline, and never
    without the gate verdict block.
    """
    if response:
        response.headers["Cache-Control"] = "public, max-age=1800, stale-while-revalidate=3600"
    from src.api.store import supabase_get_latest_track_record, supabase_ohlcv_daily_freshness
    from src.api.routers._track_record_agg import (
        build_headline, apply_ship_gate, defect_warning as _defect_warning,
    )
    rows = await supabase_get_latest_track_record()
    freshness = await supabase_ohlcv_daily_freshness()

    # Build the four-axis headline dict {RAW, BETA_ADJ, BETA_ADJ_T_STAT, WIN_PCT}.
    # Pure-function aggregator — unit-tested in src/api/routers/tests/.
    raw_headline = build_headline(rows)
    gate_open = bool(freshness.get("gate_open"))
    headline = apply_ship_gate(raw_headline, gate_open=gate_open)
    warning = _defect_warning(headline, gate_open=gate_open)

    return {
        "basis": "30d benchmark-relative alpha (BTC for crypto / SPY for TradFi), "
                 "from own data (cis_scores × ohlcv_daily), daily snapshot.",
        "tiers": rows,
        "headline": headline,
        "tier_definitions": {
            "RAW": "raw_alpha = a_ret − b_ret. What an UNHEDGED holder of the asset "
                   "experiences. NOT the same as alpha in a high-β universe.",
            "BETA_ADJ": ("Point-in-time β-adjusted directional edge. "
                         f"Computed from each row's PIT-estimated β (expanding-window "
                         f"OLS over strictly prior (symbol, d) pairs, ≥20 priors, "
                         f"NEVER default β=1.0; insufficient history → NULL — "
                         f"honestly excluded from n_beta_adj). Captured by shorting "
                         f"the benchmark at the estimated β. Mirrors "
                         f"src/data/market/beta_adjust.py."),
            "BETA_ADJ_T_STAT": "One-sample t-stat of BETA_ADJ vs 0. t>1.96 = "
                               "honestly survives, regardless of point estimate.",
            "WIN_PCT": "Share of resolved signals where the asset return beat the "
                       "benchmark return over the same 30d window. Independent of β.",
        },
        "defect_warning": warning,
        "ship_gate": {
            "ohlcv_daily_freshness": freshness,
            "publish_beta_adj": gate_open,
            "reason": ("ohlcv_daily staleness gate. β-ADJ headline is suppressed "
                       "when last_trade_date > 36 h old — stale + β-correct is "
                       "worse than pre-R62 raw. Gate auto-opens when the daily "
                       "collector writes a fresh row.")
                      if not gate_open else None,
        },
        "note": "Observational signal→30d outcome (validates the signal), not "
                "live-traded P&L. Use the tier breakdown under BOTH RAW and β-ADJ "
                "headings; do not blend. The top-conviction STRONG OUTPERFORM tier "
                "delivers positive β-ADJ (R62); the broad OUTPERFORM tier was "
                "previously mischaracterised by the pre-R62 RAW number — the "
                "β-ADJ row restores it to a positive (smaller) edge.",
        "compliance": "Positioning language only; not investment advice.",
    }


@router.get("/api/v1/signals/edge-map")
async def get_signal_edge_map(response: Response = None):
    """
    The decision surface: expected 30-day benchmark-relative alpha of each signal tier,
    conditioned on the RISK GRADIENT (benchmark trailing 30d return). This is the
    Glassnode-tier granular product — every cell is a real outcome with its sample size,
    from our own data. Read it as two dials: the top tier carries the widest positive edge when the tape is
    risk-ON, the bottom tier the widest negative edge when risk-OFF; both shrink in neutral tape.
    Refreshed daily (signal_edge_map). Risk bands (benchmark trailing 30d):
    1_deep_off <-15% · 2_off -15..-5% · 3_neutral -5..+5% · 4_on +5..+15% · 5_deep_on >+15%.
    """
    if response:
        response.headers["Cache-Control"] = "public, max-age=1800, stale-while-revalidate=3600"
    from src.api.store import supabase_get_latest_edge_map
    rows = await supabase_get_latest_edge_map()
    # Empirical-Bayes shrinkage over the grid: `avg_alpha_pct` is the DENOISED (shrunk) value
    # posture/conviction actually use; `avg_alpha_raw`, `shrink_weight` (0=all-prior, 1=all-own)
    # and the prior are exposed for transparency.
    shrink = {"cells": {}, "params": {}}
    try:
        from src.data.signals.edge_shrinkage import shrink_edge_map
        shrink = shrink_edge_map(rows)
    except Exception as _e:
        _logger.warning(f"[EDGE] shrinkage failed (raw only): {_e}")
    grid: dict = {}
    for r in rows:
        sig, band = r.get("signal"), r.get("risk_band")
        sc = shrink["cells"].get((sig, band), {})
        grid.setdefault(sig, {})[band] = {
            "avg_alpha_pct": sc.get("shrunk", r.get("avg_alpha_pct")),
            "avg_alpha_raw": r.get("avg_alpha_pct"),
            "prior": sc.get("prior"),
            "shrink_weight": sc.get("weight"),
            "alpha_win_pct": r.get("alpha_win_pct"),
            "n": r.get("n"),
        }
    return {
        "basis": "30d benchmark-relative alpha by signal tier × risk gradient (benchmark trailing 30d), from own data",
        "risk_bands": {"1_deep_off": "<-15%", "2_off": "-15..-5%", "3_neutral": "-5..+5%",
                       "4_on": "+5..+15%", "5_deep_on": ">+15%"},
        "grid": grid,
        "shrinkage": {**shrink.get("params", {}),
                      "method": "empirical-Bayes, two-way additive prior (tier+band), robust MoM K",
                      "reading": "avg_alpha_pct is denoised; shrink_weight→1 = well-sampled (own value), →0 = thin (prior)"},
        "how_to_read": "The top tier (STRONG OUTPERFORM) has shown the widest positive edge when the "
                       "tape is risk-ON (bands 4/5); the bottom tier (UNDERPERFORM) has shown the "
                       "widest negative edge when risk-OFF (bands 1/2). Neutral tape → both edges shrink.",
        "note": "Observational signal→30d outcome; thin cells shrunk to structure. Not live-traded P&L.",
        "compliance": "Positioning language only; not investment advice.",
    }


def _band_of(trail_30d: float) -> str:
    """Bucket the benchmark trailing-30d return into the edge-map risk gradient band."""
    if trail_30d < -15: return "1_deep_off"
    if trail_30d < -5:  return "2_off"
    if trail_30d < 5:   return "3_neutral"
    if trail_30d < 15:  return "4_on"
    return "5_deep_on"

_BAND_ACTION = {
    "1_deep_off": "Deep risk-OFF — negative-edge tier at maximum width; positive-edge book screens UNDERWEIGHT.",
    "2_off":      "Risk-OFF — the negative-edge tier is widest; the positive-edge book screens UNDERWEIGHT.",
    "3_neutral":  "Neutral tape — both edges shrink; conviction dispersion compresses.",
    "4_on":       "Risk-ON — top tier (STRONG OUTPERFORM) edge widest; negative-edge tier fades.",
    "5_deep_on":  "Deep risk-ON — top-tier edge strongest; bottom tier disfavored.",
}

# Band → default posture (net bias + gross scale), from the edge-map thesis: top-tier edge is
# widest in risk-ON, bottom-tier edge widest in risk-OFF, shrinking to neutral in the middle. Refined by the
# LIVE edge-map data (does this band's tier alpha actually confirm?) and sample size.
_BAND_POSTURE = {
    "5_deep_on":  ("long",    1.10),
    "4_on":       ("long",    0.95),
    "3_neutral":  ("neutral", 0.55),
    "2_off":      ("short",   0.80),
    "1_deep_off": ("short",   0.95),
}
_POSTURE_MIN_N = 30   # need this many resolved outcomes in the relevant tier to trust the edge


def _posture_from(band: str, tiers_now: dict) -> dict:
    """Actionable posture for the current band, grounded in the live edge-map cell. Advisory /
    positioning language only — NOT a live sizing directive. Falls back to the band default and
    dampens toward neutral when the confirming tier is thin (n<_POSTURE_MIN_N) or contradicts."""
    bias, gross = _BAND_POSTURE.get(band, ("neutral", 0.55))
    top = tiers_now.get("STRONG OUTPERFORM", {}) or {}
    bot = tiers_now.get("UNDERPERFORM", {}) or {}
    conf = "confirmed"
    if bias == "long":
        a, n = top.get("avg_alpha_pct"), top.get("n") or 0
        if n < _POSTURE_MIN_N or (a is not None and a <= 0):   # thin or edge doesn't confirm
            gross = round(gross * 0.6, 2); conf = "unconfirmed (thin/contradicts)"
    elif bias == "short":
        a, n = bot.get("avg_alpha_pct"), bot.get("n") or 0
        if n < _POSTURE_MIN_N or (a is not None and a >= 0):   # bottom tier isn't underperforming
            gross = round(gross * 0.6, 2); conf = "unconfirmed (thin/contradicts)"
    return {"net_bias": bias, "gross_scale": gross, "confirmation": conf,
            "rationale": _BAND_ACTION.get(band, "")}


async def compute_current_band() -> dict:
    """Where the tape sits RIGHT NOW on the edge-map risk gradient + what each signal
    tier is expected to do in that band. Benchmark = BTC 30d (crypto). Shared by the
    live read endpoint AND the daily snapshot logger so both are identical."""
    from src.api.routers.cis import get_cis_universe
    from src.api.store import supabase_get_latest_edge_map
    data = await get_cis_universe()
    universe = (data or {}).get("universe", []) or []
    regime = (data or {}).get("macro_regime")
    btc = next((a for a in universe if (a.get("symbol") or a.get("asset_id") or "").upper() == "BTC"), {})
    trail = 0.0
    try:
        trail = float(btc.get("change_30d") or 0.0)
    except (TypeError, ValueError):
        trail = 0.0
    band = _band_of(trail)
    rows = await supabase_get_latest_edge_map()
    # Empirical-Bayes shrinkage over the WHOLE grid: thin/noisy cells (n=1..3) collapse to the
    # two-way structural prior; well-sampled cells keep their own value. So posture/conviction
    # read a denoised alpha, not raw thin-cell noise (e.g. −64% on n=3). Raw kept for context.
    shrunk = {}
    try:
        from src.data.signals.edge_shrinkage import shrunk_grid_by_signal
        shrunk = shrunk_grid_by_signal(rows)
    except Exception as _e:
        _logger.warning(f"[BAND] edge shrinkage failed (using raw): {_e}")
    tiers = {}
    for r in rows:
        if r.get("risk_band") != band:
            continue
        sig = r.get("signal")
        sh = (shrunk.get(sig) or {}).get(band)
        raw = r.get("avg_alpha_pct")
        tiers[sig] = {"avg_alpha_pct": sh if sh is not None else raw,
                      "avg_alpha_raw": raw, "alpha_win_pct": r.get("alpha_win_pct"),
                      "n": r.get("n"), "shrunk": sh is not None}
    top = tiers.get("STRONG OUTPERFORM", {})
    posture = _posture_from(band, tiers)
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "bench_trail_30d": round(trail, 2),
        "current_band": band,
        "macro_regime": regime,
        "tiers_now": tiers,
        "top_tier_alpha": top.get("avg_alpha_pct"),
        "top_tier_n": top.get("n"),
        "posture": posture,
        "action": _BAND_ACTION.get(band, ""),
    }


@router.get("/api/v1/signals/current-band")
async def get_current_band(response: Response = None):
    """Live read: given today's risk gradient (BTC 30d), which edge-map band are we in and
    what is each signal tier expected to do NOW. Compliance: positioning language only."""
    if response:
        response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=1800"
    cur = await compute_current_band()
    cur["risk_bands"] = {"1_deep_off": "<-15%", "2_off": "-15..-5%", "3_neutral": "-5..+5%",
                         "4_on": "+5..+15%", "5_deep_on": ">+15%"}
    cur["compliance"] = "Positioning language only; not investment advice."
    return cur


@router.get("/api/v1/signals/holder-map")
async def get_holder_map_debug():
    """Diagnostic: current D3 holder map + a raw Moralis probe (shows the real response shape /
    error / whether the owners endpoint is available on this plan). Read-only."""
    from src.data.cis.holder_provider import get_holder_map, _TOKEN_REGISTRY
    from src.data.market.data_layer import get_token_holders, MORALIS_KEY
    m = await get_holder_map()
    sym, (chain, addr) = next(iter(_TOKEN_REGISTRY.items()))
    raw = await get_token_holders(addr, chain=chain, limit=5)
    holders = raw.get("holders") if isinstance(raw, dict) else None
    return {
        "map_size": len(m),
        "map_symbols": sorted(m.keys()),
        "moralis_key_set": bool(MORALIS_KEY),
        "probe_symbol": sym,
        "probe_error": raw.get("error") if isinstance(raw, dict) else None,
        "probe_holder_count": len(holders) if isinstance(holders, list) else None,
        "probe_first_holder_keys": list(holders[0].keys()) if holders else None,
        "probe_sample": holders[:1] if holders else None,
    }


@router.get("/api/v1/cis/conviction")
async def get_conviction(response: Response = None):
    """Fusion #1 — per-asset conviction verdict: fuses regime-neutral quality (grade) +
    cause-proximity (in-circle vs 出圈 fragility + season) + the edge map's expected alpha for
    each tier in TODAY's band + executability, into one {conviction, direction, action} per
    asset, ranked. Anchored on real outcomes; illiquid names discounted. Positioning language only."""
    if response:
        response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=900"
    from src.api.routers.cis import get_cis_universe
    from src.data.cis.conviction import rank_universe
    cur = await compute_current_band()
    data = await get_cis_universe()
    universe = (data or {}).get("universe", []) or []
    rows = rank_universe(universe, cur.get("tiers_now") or {}, cur.get("current_band"))
    return {
        "current_band": cur.get("current_band"),
        "bench_trail_30d": cur.get("bench_trail_30d"),
        "macro_regime": cur.get("macro_regime"),
        "posture": cur.get("posture"),
        "basis": "quality × in-circle × (edge-map tier×band) × executability, ranked by signed edge",
        "count": len(rows),
        "conviction": rows,
        "compliance": "Positioning language only; not investment advice.",
    }


async def log_regime_band() -> bool:
    """Daily snapshot writer — persists one current-band reading to Supabase `regime_band_log`
    so we accumulate the band time series (→ Mac warehouse via the same sync as CIS scores).
    This is the track record of the band signal itself. Best-effort; never raises."""
    from src.api.store import supabase_insert_table
    try:
        cur = await compute_current_band()
        pos = cur.get("posture") or {}
        row = {
            "ts": cur["ts"],
            "bench_trail_30d": cur["bench_trail_30d"],
            "current_band": cur["current_band"],
            "macro_regime": cur["macro_regime"],
            "top_tier_alpha": cur.get("top_tier_alpha"),
            "top_tier_n": cur.get("top_tier_n"),
            "net_bias": pos.get("net_bias"),
            "gross_scale": pos.get("gross_scale"),
        }
        ok = await supabase_insert_table("regime_band_log", [row])
        _logger.info(f"[BAND-LOG] {cur['current_band']} trail={cur['bench_trail_30d']}% "
                     f"regime={cur['macro_regime']} written={ok}")
        return ok
    except Exception as e:
        _logger.warning(f"[BAND-LOG] snapshot failed: {e}")
        return False
