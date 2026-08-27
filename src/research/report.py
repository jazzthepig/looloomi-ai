"""
Standardised research report — render framework results as markdown.

Writes `reports/{strategy}_{YYYYMMDD}.md` matching the gate 1-10 discipline
from STRATEGY_VALIDATION.md. All sections are conditional: the report
gracefully degrades when optional inputs (walk-forward, multi-testing,
decay, hygiene, regime attribution) are absent.

Inputs:
- strategy_name + label + date (header)
- SingleRunResult → Aggregate metrics, parity check, OOS holdout
- WalkForwardResult → Walk-forward + decay ratio (gate 3)
- CorrectionResult → Multiple-testing (gate 5)
- DecayStatus → Decay monitor (live-paper support)
- HygieneReport → Signal hygiene (turnover, capacity, slippage)
- RegimeAttribution → Per-regime breakdown (gate 7)
- baseline (BaselineMetrics) → Parity comparison column

Output: a single markdown string. `write_report()` also writes to disk.

Design notes:
- Output layer matters most. Numbers formatted to 3 sig figs, tables
  consistent width, status icons (✅/⚠️/❌) on each gate.
- All sections use positioning language only — no BUY/SELL/HOLD/LONG.
  Long/short directional language is acceptable in tables for trade
  attribution (already a structural fact, not a recommendation).
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.research.metrics import StrategyMetrics
from src.research.walk_forward import WalkForwardResult
from src.research.multiple_testing import CorrectionResult, interpret_correction
from src.research.decay_monitor import DecayStatus
from src.research.signal_hygiene import HygieneReport
from src.research.regime_attribution import RegimeAttribution
from src.research.baselines import BaselineMetrics


logger = logging.getLogger(__name__)


# ── Output location ─────────────────────────────────────────────────────────
REPORTS_DIR = Path("reports")


# ── Gate thresholds (from STRATEGY_VALIDATION.md) ───────────────────────────
@dataclass(frozen=True)
class GateThresholds:
    """Numerical gates applied to the framework-validated metrics."""
    min_n_trades: int = 100            # gate 2
    min_sharpe: float = 0.5            # "any edge" floor
    min_win_rate_pct: float = 40.0     # "decent" floor
    min_profit_factor: float = 1.1     # "positive edge"
    max_max_dd_pct: float = 25.0       # gate 6 risk
    min_decay_ratio: float = 0.7       # gate 3 walk-forward
    max_fdr_rejected_pct: float = 0.5  # gate 5: at least half survive


DEFAULT_GATES = GateThresholds()


# ── Formatting helpers ──────────────────────────────────────────────────────

def _fmt(x, fmt: str = ".3f", na: str = "—") -> str:
    if x is None or (isinstance(x, float) and (x != x)):
        return na
    if isinstance(x, float) and x in (float("inf"), float("-inf")):
        return "∞" if x > 0 else "-∞"
    return format(x, fmt)


def _status_icon(passed: bool, marginal: bool = False) -> str:
    if passed:
        return "✅"
    if marginal:
        return "⚠️"
    return "❌"


# ── Report builder ──────────────────────────────────────────────────────────

@dataclass
class ReportInput:
    """Bundles everything the report renderer needs."""
    strategy_name: str
    label: str
    run_date: dt.date
    metrics: StrategyMetrics
    config_lines: list[str]                       # free-form setup lines
    baseline: Optional[BaselineMetrics] = None
    walk_forward: Optional[WalkForwardResult] = None
    multiple_testing: Optional[CorrectionResult] = None
    decay: Optional[DecayStatus] = None
    hygiene: Optional[HygieneReport] = None
    regime: Optional[RegimeAttribution] = None
    oos_window: Optional[tuple[str, str]] = None  # e.g. ("2026-01-01", "2026-06-30")
    oos_metrics: Optional[StrategyMetrics] = None  # if --oos flag was used
    gates: GateThresholds = DEFAULT_GATES


def render_report(inp: ReportInput) -> str:
    """Render the full markdown report as a string."""
    sections: list[str] = []
    sections.append(_render_header(inp))
    sections.append(_render_setup(inp))
    sections.append(_render_aggregate_metrics(inp))
    if inp.baseline is not None:
        sections.append(_render_parity(inp))
    if inp.walk_forward is not None:
        sections.append(_render_walk_forward(inp))
    if inp.multiple_testing is not None:
        sections.append(_render_multiple_testing(inp))
    if inp.regime is not None:
        sections.append(_render_regime(inp))
    if inp.oos_metrics is not None:
        sections.append(_render_oos(inp))
    if inp.hygiene is not None:
        sections.append(_render_hygiene(inp))
    if inp.decay is not None:
        sections.append(_render_decay(inp))
    sections.append(_render_gate_checklist(inp))
    sections.append(_render_verdict(inp))
    return "\n\n---\n\n".join(sections) + "\n"


# ── Sections ────────────────────────────────────────────────────────────────

def _render_header(inp: ReportInput) -> str:
    return (
        f"# Strategy Research Report — {inp.strategy_name}\n"
        f"\n"
        f"- **Label:** `{inp.label or '—'}`\n"
        f"- **Run date:** {inp.run_date.isoformat()}\n"
        f"- **Generated by:** research framework (`src.research.report`)"
    )


def _render_setup(inp: ReportInput) -> str:
    lines = ["## Setup"]
    for line in inp.config_lines:
        # If caller already passed a leading "- ", don't double up.
        prefix = "" if line.lstrip().startswith("- ") else "- "
        lines.append(f"{prefix}{line}")
    return "\n".join(lines)


def _render_aggregate_metrics(inp: ReportInput) -> str:
    m = inp.metrics
    g = inp.gates
    rows = [
        ("Total trades",        _fmt(m.n_trades, "d"),       f"≥{g.min_n_trades}",   _status_icon(m.n_trades >= g.min_n_trades)),
        ("Wins / Losses",       f"{m.n_wins} / {m.n_losses}", "—",                    "—"),
        ("Win rate",            f"{_fmt(m.win_rate_pct, '.1f')}%", f"≥{g.min_win_rate_pct:.0f}%", _status_icon(m.win_rate_pct >= g.min_win_rate_pct)),
        ("Profit factor",       _fmt(m.profit_factor, ".2f"), f"≥{g.min_profit_factor}", _status_icon(m.profit_factor >= g.min_profit_factor)),
        ("Sharpe (annualised)", _fmt(m.sharpe, ".3f"),       f"≥{g.min_sharpe:.2f}", _status_icon(m.sharpe >= g.min_sharpe)),
        ("Sharpe p-value",      _fmt(m.sharpe_p_value, ".4f"), "p<0.05 → significant", _status_icon(m.sharpe_p_value < 0.05)),
        ("Sortino",             _fmt(m.sortino, ".3f"),      "—",                    "—"),
        ("Calmar",              _fmt(m.calmar, ".3f"),       "—",                    "—"),
        ("SQN",                 _fmt(m.sqn, ".2f"),          "—",                    "—"),
        ("CAGR",                f"{_fmt(m.cagr_pct, '.2f')}%", "—",                  "—"),
        ("Total return",        f"{_fmt(m.total_return_pct, '.2f')}%", "—",           "—"),
        ("Max drawdown",        f"{_fmt(m.max_drawdown_pct, '.2f')}%", f"≤{g.max_max_dd_pct:.0f}%", _status_icon(m.max_drawdown_pct <= g.max_max_dd_pct)),
        ("Volatility (annual)", f"{_fmt(m.volatility_annual, '.2f')}", "—",          "—"),
        ("Downside vol (annual)", f"{_fmt(m.downside_vol_annual, '.2f')}", "—",        "—"),
        ("Avg trade PnL",       f"{_fmt(m.avg_trade_pnl, '.4f')} USDT", "—",          "—"),
        ("Initial → Final",     f"${_fmt(m.initial_balance, ',.2f')} → ${_fmt(m.final_balance, ',.2f')}", "—", "—"),
        ("Timeframe / Years",   f"{m.timeframe} / {_fmt(m.years, '.3f')}", "—",      "—"),
    ]
    table = _table(["Metric", "Value", "Gate target", "Pass"], rows)
    return "## Aggregate metrics (in-sample, gate 2)\n\n" + table


def _render_parity(inp: ReportInput) -> str:
    """Compare framework run vs freqtrade baseline."""
    b = inp.baseline
    m = inp.metrics
    if b is None:
        return ""
    rows = [
        ("n_trades",   m.n_trades,    b.n_trades,    f"±{int(b.n_trades * 0.30)} (30%)"),
        ("CAGR (%)",   m.cagr_pct,    b.cagr_pct,    "±5pp"),
        ("MaxDD (%)",  m.max_drawdown_pct, b.max_dd_pct, "±5pp"),
        ("WR (%)",     m.win_rate_pct, b.win_rate_pct, "±8pp"),
        ("Sharpe",     m.sharpe,      b.sharpe,      "±0.40"),
    ]
    table_rows = []
    for label, ours, theirs, tol in rows:
        delta = ours - theirs
        within = (
            abs(m.n_trades - b.n_trades) <= b.n_trades * 0.30
            if label == "n_trades"
            else abs(delta) <= 5.0 if "MaxDD" in label or "CAGR" in label
            else abs(delta) <= 8.0 if "WR" in label
            else abs(delta) <= 0.40
        )
        table_rows.append((label, _fmt(ours, ",.2f" if "pnl" not in label else ".4f"),
                           _fmt(theirs, ",.2f" if "pnl" not in label else ".4f"),
                           f"{_fmt(delta, '+.3f')}",
                           tol, _status_icon(within)))
    return (
        f"## Parity vs freqtrade baseline ({b.source_report})\n\n"
        + _table(["Metric", "Framework", "Baseline", "Delta", "Tolerance", "Pass"], table_rows)
        + f"\n\n**Baseline verdict (C):** {b.c_verdict}"
    )


def _render_walk_forward(inp: ReportInput) -> str:
    wf = inp.walk_forward
    if wf is None:
        return ""
    g = inp.gates
    decay_pass = wf.decay_ratio >= g.min_decay_ratio
    rows = []
    for r in wf.rolls:
        rows.append((
            f"roll-{r.roll_id}",
            f"[{r.train_start}:{r.train_end}]",
            f"[{r.test_start}:{r.test_end}]",
            _fmt(r.is_sharpe, "+.3f"),
            _fmt(r.oos_sharpe, "+.3f"),
            f"{_fmt(r.oos_cagr_pct, '+.2f')}%",
            _fmt(r.oos_max_dd_pct, ".2f"),
            str(r.oos_n_trades),
        ))
    table = _table(
        ["Roll", "Train", "Test", "IS Sharpe", "OOS Sharpe", "OOS CAGR", "OOS MaxDD", "OOS n"],
        rows,
    )
    # S-235:这个量 WalkForwardRoll 不携带。印一个占位数比不印更糟 —— 它会被读、
    # 被引用、被拿去比较,而它的量纲是回撤不是盈亏,单位还写着 USDT。
    _pnl_line = (
        f"- **OOS total PnL:** {_fmt(wf.oos_total_pnl, ',.2f')} USDT\n"
        if wf.oos_total_pnl is not None else
        "- **OOS total PnL:** not measured — WalkForwardRoll carries no PnL field "
        "(S-235; the previous figure summed max-drawdown percentages and labelled "
        "them USDT)\n"
    )
    summary = (
        f"## Walk-forward (gate 3) — {len(wf.rolls)} rolls\n\n"
        f"- **OOS Sharpe mean ± std:** {_fmt(wf.oos_sharpe_mean, '+.3f')} ± {_fmt(wf.oos_sharpe_std, '.3f')}\n"
        f"- **OOS CAGR mean:** {_fmt(wf.oos_cagr_mean, '+.2f')}%\n"
        f"- **OOS MaxDD worst:** {_fmt(wf.oos_max_dd_max, '.2f')}%\n"
        f"- **OOS total trades:** {wf.oos_n_trades_total}\n"
        + _pnl_line +
        f"- **IS Sharpe mean:** {_fmt(wf.is_sharpe_mean, '+.3f')}\n"
        f"- **IS CAGR mean:** {_fmt(wf.is_cagr_mean, '+.2f')}%\n"
        f"- **Decay ratio (OOS/IS):** {_fmt(wf.decay_ratio, '+.3f')}  "
        f"{_status_icon(decay_pass, marginal=0.55 <= wf.decay_ratio < g.min_decay_ratio)}\n"
        f"- **Decay status:** `{wf.decay_status}` "
        f"(gate: ≥{g.min_decay_ratio:.2f} → "
        f"{'PASS' if decay_pass else 'FAIL — overfit'})\n\n"
        + table
    )
    return summary


def _render_multiple_testing(inp: ReportInput) -> str:
    mt = inp.multiple_testing
    if mt is None:
        return ""
    interp = interpret_correction(mt)
    rows = []
    for i, (p_raw, p_corr, rej) in enumerate(
        zip(mt.p_values, mt.p_values_corrected, mt.rejected)
    ):
        rows.append((
            f"variant-{i:02d}",
            _fmt(p_raw, ".4f"),
            _fmt(p_corr, ".4f"),
            _status_icon(not rej, marginal=p_raw < 0.05 and p_corr >= 0.05),
        ))
    table = _table(["Variant", "p (raw)", f"p (corrected, {mt.method})", "Survives"], rows)
    survive_pct = (
        100.0 * (mt.n_tests - mt.n_rejected) / mt.n_tests if mt.n_tests > 0 else 0.0
    )
    return (
        f"## Multiple-testing correction (gate 5) — {mt.method.upper()}\n\n"
        f"- **N tests:** {mt.n_tests}\n"
        f"- **N rejected:** {mt.n_rejected} ({_fmt(100 - survive_pct, '.1f')}%)\n"
        f"- **N survive:** {mt.n_tests - mt.n_rejected} ({_fmt(survive_pct, '.1f')}%)\n"
        f"- **Alpha:** {mt.alpha:.2f}\n"
        f"- **Family-wise error:** {_fmt(mt.family_wise_error, '.4f')}\n"
        f"- **Interpretation:** {interp}\n\n"
        + (f"{mt.notes}\n\n" if mt.notes else "")
        + table
    )


def _render_regime(inp: ReportInput) -> str:
    r = inp.regime
    if r is None:
        return ""
    rows = []
    for name, bucket in r.buckets.items():
        if bucket.n_trades == 0:
            continue
        rows.append((
            name,
            str(bucket.n_trades),
            f"{_fmt(bucket.win_rate_pct, '.1f')}%",
            _fmt(bucket.total_pnl, ",.2f"),
            _fmt(bucket.sharpe, "+.3f"),
            f"{_fmt(bucket.contribution_pct, '.1f')}%",
        ))
    if not rows:
        return (
            "## Regime attribution (gate 7)\n\n"
            "*No regime-tagged trades (regime data unavailable for this run).*"
        )
    table = _table(
        ["Regime", "Trades", "Win %", "Total PnL", "Sharpe", "Contribution %"],
        rows,
    )
    return (
        f"## Regime attribution (gate 7)\n\n"
        f"- **Total trades:** {r.total_trades}\n"
        f"- **Total PnL:** {_fmt(r.total_pnl, ',.2f')} USDT\n"
        f"- **Best regime:** `{r.best_regime}` ({_fmt(r.best_regime_pnl, '+,.2f')} USDT)\n"
        f"- **Worst regime:** `{r.worst_regime}` ({_fmt(r.worst_regime_pnl, '+,.2f')} USDT)\n"
        f"- **Regime dependency:** {_fmt(r.regime_dependency, '.3f')} "
        f"(0=diversified, 1=concentrated)\n\n"
        + table
    )


def _render_oos(inp: ReportInput) -> str:
    m = inp.oos_metrics
    if m is None or inp.oos_window is None:
        return ""
    is_m = inp.metrics
    sharpe_decay = (
        m.sharpe / is_m.sharpe if abs(is_m.sharpe) > 0.05 else 0.0
    )
    return (
        f"## Out-of-sample holdout (gate 8)\n\n"
        f"- **OOS window:** {inp.oos_window[0]} → {inp.oos_window[1]} "
        f"(last 20% of backtest period)\n"
        f"- **OOS n_trades:** {m.n_trades}\n"
        f"- **OOS Sharpe:** {_fmt(m.sharpe, '+.3f')}  "
        f"(in-sample: {_fmt(is_m.sharpe, '+.3f')})\n"
        f"- **OOS CAGR:** {_fmt(m.cagr_pct, '+.2f')}%\n"
        f"- **OOS MaxDD:** {_fmt(m.max_drawdown_pct, '.2f')}%\n"
        f"- **OOS vs IS Sharpe ratio:** {_fmt(sharpe_decay, '.3f')} "
        f"{_status_icon(sharpe_decay >= 0.70)}\n\n"
        f"Gate 8 pass: OOS Sharpe ≥70% of in-sample Sharpe."
    )


def _render_hygiene(inp: ReportInput) -> str:
    h = inp.hygiene
    if h is None:
        return ""
    return (
        f"## Signal hygiene (capacity + slippage)\n\n"
        f"- **Turnover:** {_fmt(h.turnover_per_year, '.1f')} round-trips / year\n"
        f"- **Avg hold:** {_fmt(h.avg_hold_bars, '.1f')} bars\n"
        f"- **Estimated capacity:** ${_fmt(h.estimated_capacity_usd, ',.0f')}\n"
        f"- **Capacity ratio (cap / position):** {_fmt(h.capacity_ratio, '.1f')}×\n"
        f"- **Avg volume per bar:** ${_fmt(h.avg_volume_usd_per_bar, ',.0f')}\n"
        f"- **Est slippage per fill:** {_fmt(h.estimated_slippage_bps_per_fill, '.1f')} bps\n"
        f"- **Hygiene grade:** `{h.hygiene_grade}` {_status_icon(h.hygiene_grade == 'OK', marginal=h.hygiene_grade == 'WATCH')}\n\n"
        f"Notes: {h.notes}"
    )


def _render_decay(inp: ReportInput) -> str:
    d = inp.decay
    if d is None:
        return ""
    hl_text = (
        "NaN (peak at end of sample — no observable decay)"
        if d.half_life_bars != d.half_life_bars  # NaN check
        else f"{_fmt(d.half_life_bars, '.1f')} bars"
    )
    return (
        f"## Decay monitor (rolling Sharpe)\n\n"
        f"- **Status:** `{d.status}` {_status_icon(d.status == 'OK', marginal=d.status == 'WATCH')}\n"
        f"- **Rolling Sharpe peak:** {_fmt(d.rolling_sharpe_peak, '+.3f')}\n"
        f"- **Rolling Sharpe current:** {_fmt(d.rolling_sharpe_current, '+.3f')}\n"
        f"- **Rolling Sharpe mean ± std:** {_fmt(d.rolling_sharpe_mean, '+.3f')} ± {_fmt(d.rolling_sharpe_std, '.3f')}\n"
        f"- **Half-life:** {hl_text}\n"
        f"- **Z-score (current vs mean):** {_fmt(d.z_score, '+.2f')}\n\n"
        f"Notes: {d.notes or '(none)'}"
    )


def _render_gate_checklist(inp: ReportInput) -> str:
    m = inp.metrics
    g = inp.gates
    rows = []

    def add(label, passed, detail):
        rows.append((label, _status_icon(passed), detail))

    add("Gate 1 — Data source",
        True,
        "Binance public klines 1h → resampled 4h, ≥2 years (see Setup)")

    add("Gate 2 — Sample size (n≥100)",
        m.n_trades >= g.min_n_trades,
        f"n={m.n_trades} (threshold {g.min_n_trades})")

    if inp.walk_forward is not None:
        wf = inp.walk_forward
        add("Gate 3 — Walk-forward decay",
            wf.decay_ratio >= g.min_decay_ratio,
            f"OOS/IS={wf.decay_ratio:+.3f}, status={wf.decay_status}")
    else:
        add("Gate 3 — Walk-forward decay",
            False,
            "not run (no `--walk-forward` flag)")

    add("Gate 4 — Purged CV",
        True,
        "embargo_bars enforced at train/test boundary (see WalkForwardConfig)")

    if inp.multiple_testing is not None:
        mt = inp.multiple_testing
        survive_pct = (mt.n_tests - mt.n_rejected) / max(mt.n_tests, 1)
        add("Gate 5 — Multiple-testing",
            survive_pct >= 1.0 - g.max_fdr_rejected_pct,
            f"{mt.method.upper()}: {mt.n_rejected}/{mt.n_tests} rejected")
    else:
        add("Gate 5 — Multiple-testing",
            False,
            "not run (single variant — no `--fdr` flag)")

    add("Gate 6 — Net of cost",
        m.cagr_pct > 0 and m.max_drawdown_pct <= g.max_max_dd_pct,
        f"CAGR={m.cagr_pct:+.2f}%, MaxDD={m.max_drawdown_pct:.2f}%")

    if inp.regime is not None and inp.regime.buckets:
        # Gate 7 (regime-segmented): pass if no single regime loses >2% of
        # initial balance AND no regime contributes >50% of total PnL.
        loss_threshold = -0.02 * inp.metrics.initial_balance
        worst_loss = min(
            (b.total_pnl for b in inp.regime.buckets.values() if b.n_trades > 0),
            default=0.0,
        )
        max_contrib = max(
            (b.contribution_pct for b in inp.regime.buckets.values() if b.n_trades > 0),
            default=0.0,
        )
        regime_pass = worst_loss > loss_threshold and max_contrib < 50.0
        add(
            "Gate 7 — Regime-segmented",
            regime_pass,
            f"worst regime PnL = {_fmt(worst_loss, '+,.2f')} USDT; "
            f"max regime contribution = {_fmt(max_contrib, '.1f')}%",
        )
    else:
        add("Gate 7 — Regime-segmented",
            False,
            "no regime data")

    if inp.oos_metrics is not None:
        sharpe_decay = inp.oos_metrics.sharpe / max(abs(inp.metrics.sharpe), 0.05)
        add("Gate 8 — OOS holdout",
            sharpe_decay >= 0.70,
            f"OOS/IS Sharpe={sharpe_decay:.3f} (threshold 0.70)")
    else:
        add("Gate 8 — OOS holdout",
            False,
            "no `--oos` flag")

    add("Gate 9 — Live paper (30d)",
        False,
        "deferred — requires Mac Mini execution time, opens after first deployment")

    add("Gate 10 — Reviewer sign-off",
        False,
        "Seth signs off + Austin cross-checks (process step, not automated)")

    return "## Gate checklist (STRATEGY_VALIDATION.md)\n\n" + _table(
        ["Gate", "Status", "Detail"], rows
    )


def _render_verdict(inp: ReportInput) -> str:
    """High-level pass/needs-work/fail based on critical gates."""
    m = inp.metrics
    g = inp.gates
    failures: list[str] = []
    if m.n_trades < g.min_n_trades:
        failures.append(f"n={m.n_trades} < {g.min_n_trades}")
    if m.cagr_pct <= 0:
        failures.append(f"CAGR={m.cagr_pct:+.2f}% (≤0)")
    if inp.walk_forward is not None and inp.walk_forward.decay_ratio < g.min_decay_ratio:
        failures.append(f"decay={inp.walk_forward.decay_ratio:+.3f} < {g.min_decay_ratio}")
    if inp.hygiene is not None and inp.hygiene.hygiene_grade == "OVERFIT":
        failures.append("hygiene=OVERFIT (capacity < 2× position)")

    if not failures:
        verdict = "**PASS** — eligible for paper trading (after Gate 9 + 10)"
    elif len(failures) <= 2:
        verdict = f"**NEEDS-WORK** — {len(failures)} failure(s): {', '.join(failures)}"
    else:
        verdict = f"**FAIL** — {len(failures)} failures: {', '.join(failures)}"
    return f"## Verdict\n\n{verdict}"


# ── Markdown table helper ───────────────────────────────────────────────────

def _table(headers: list[str], rows: list[tuple]) -> str:
    """Render a markdown table from a list of header strings + row tuples."""
    out = ["| " + " | ".join(str(h) for h in headers) + " |"]
    out.append("|" + "|".join("---" for _ in headers) + "|")
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


# ── Disk writer ─────────────────────────────────────────────────────────────

def write_report(inp: ReportInput, output_path: Optional[Path] = None) -> Path:
    """Render + write report to disk. Returns the path written."""
    if output_path is None:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        output_path = REPORTS_DIR / f"{inp.strategy_name}_{inp.run_date.isoformat()}.md"
    body = render_report(inp)
    output_path.write_text(body)
    logger.info(f"Report written: {output_path}")
    return output_path


# ── Self-test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Synthetic smoke: minimal report
    import datetime as dt2

    m = StrategyMetrics(
        n_trades=150, n_wins=80, n_losses=70,
        total_return_pct=12.5, cagr_pct=14.2,
        sharpe=1.4, sharpe_p_value=0.001,
        sortino=2.1, sortino_p_value=0.003,
        calmar=0.85, sqn=2.8,
        max_drawdown_pct=16.7,
        volatility_annual=22.4, downside_vol_annual=15.3,
        win_rate_pct=53.3, profit_factor=1.45,
        avg_trade_pnl=8.33,
        timeframe="4h", years=0.857,
        initial_balance=10_000.0, final_balance=11_250.0,
    )
    inp = ReportInput(
        strategy_name="SMOKE_TEST",
        label="smoke",
        run_date=dt2.date(2026, 6, 30),
        metrics=m,
        config_lines=[
            "- Strategy: SMOKE_TEST (synthetic)",
            "- Pairs: BTC, ETH",
            "- Timeframe: 4h",
            "- Period: 2025-05-03 → 2026-03-12",
            "- Fee: 5bps taker",
            "- Starting balance: $10,000",
        ],
    )
    print(render_report(inp))