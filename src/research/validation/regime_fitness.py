"""
cis_regime_fitness — per (regime × pillar) Pearson IC of the pillar score against
the 7-day forward return. The Simons feedback loop: which pillar actually predicts
in which macro regime.

T-062 (2026-11-17) — WHY THIS MODULE EXISTS
-------------------------------------------
`cis_regime_fitness` had been at 0 rows since it was created, and the loop that
is supposed to fill it (`_regime_fitness_loop` in src/api/main.py) reported
`ok` on every daily round. Three separate causes, all measured, all real:

  1. **The input table is empty.** The old writer read `cis_scores`
     (234 rows with all pillars NULL per S-203, and 0 rows today — measured
     2026-11-17: `select count(*) from cis_scores` = 0). With no rows there is
     no (pillar, forward-return) pair, so `compute_fitness` returned [] and
     nothing was ever written. The canonical daily series with pillars is
     `cis_official_daily` (2203 rows, 38 distinct days 2026-10-10 → 2026-11-16,
     `pillar_f..pillar_a` + `regime` + `d`) — this module reads THAT.

  2. **The forward return had nowhere to come from.** `trade_results` (the
     Freqtrade fills the old writer preferred) is empty too (0 rows measured
     2026-11-17), so the writer fell through to `score_proxy` — a score-change
     proxy that is not a return at all. The forward return is computed here from
     `ohlcv_daily` (1.5M rows, `symbol`/`trade_date`/`close`), which is the
     price series the rest of the stack already treats as the price of record.

  3. **The sample floor was never reachable.** The gate needs 20 INDEPENDENT
     DAYS; the old window had 18. `cis_official_daily` has 38 distinct days in
     the same 90-day window, so the floor is now met — and the gate is kept,
     because 20 days is the smallest sample that means anything.

WHAT THIS DOES NOT DO
---------------------
It does not change any CIS score. The live IC multiplier reads the Redis key
`cis:factor_performance`; the official daily CIS is computed with
`ic_mult=None`. This table is a RECORD — the Simons feedback signal that
somebody has to be able to read before it can be wired into anything. Writing
rows does not energise it, and this module does not pretend otherwise.

THE SAMPLE FLOOR IS ON DAYS, NOT ROWS
--------------------------------------
`n_samples` counts (symbol, day) pairs and `n_days` counts distinct days
behind them — the same symbol contributes many pairs across the window, so
`n_samples` alone overstates the evidence by the number of assets. Both are
written, and the gate reads `n_days`.

PIT DISCIPLINE: the label uses the price at d+7, which only exists 7 days
after the score. The newest 7 days of the window therefore have no label and
are dropped — that is not a bug, it is the reason a forward return is forward.
"""
from __future__ import annotations

import json
import logging
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

_log = logging.getLogger("regime_fitness")

# ── Constants ────────────────────────────────────────────────────────────────
MIN_INDEPENDENT_DAYS = 20      # the gate the old writer could never pass (it had 18)
MIN_SAMPLES = 30               # (symbol, day) pairs — a regime with 5 days of 1 asset is not evidence
HORIZON_DAYS = 7               # forward return horizon, matching the table's stated purpose
PILLARS = ("F", "M", "O", "S", "A")
_SCORES_TABLE = "cis_official_daily"
_PRICES_TABLE = "ohlcv_daily"
_TARGET_TABLE = "cis_regime_fitness"

# ohlcv_daily carries more than one source per (symbol, trade_date) for some
# symbols. One price per day per symbol, deterministically: the priority order
# below is the same one the rest of the stack treats as preferred.
_SOURCE_PRIORITY = ("binance_hist", "eodhd", "yfinance", "coinbase", "okx")

_PAGE = 1000  # PostgREST silently truncates limit=10000 to 1000 (T-170 / 11-05 lane-b)


# ── Config ───────────────────────────────────────────────────────────────────
def _sb_conf() -> tuple[str, str] | None:
    """Supabase URL + the strongest key present. service_role first, exactly as
    src/api/store.py resolves it — the publishable key can READ the research
    tables but is rejected by the service-only ones."""
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY", "")
    return (base, key) if base and key else None


def _get(table: str, params) -> list[dict]:
    """One paged GET. Every page carries `order=` — without it the pagination
    boundary drifts and the same query silently loses keys (T-170 / T-173).

    `params` is a list of (key, value) pairs because PostgREST needs the SAME
    key twice for a range (`trade_date=gte.X` AND `trade_date=lte.Y`) — a dict
    would silently keep only the second one."""
    conf = _sb_conf()
    if not conf:
        return []
    base, key = conf
    out: list[dict] = []
    offset = 0
    while True:
        q = list(params.items()) if isinstance(params, dict) else list(params)
        q += [("limit", str(_PAGE)), ("offset", str(offset))]
        url = f"{base}/rest/v1/{table}?{urllib.parse.urlencode(q)}"
        req = urllib.request.Request(
            url, headers={"apikey": key, "Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                page = json.loads(r.read() or b"[]")
        except (urllib.error.URLError, json.JSONDecodeError) as e:
            _log.warning("[regime_fitness] GET %s failed: %s", table, e)
            return out
        if not isinstance(page, list) or not page:
            break
        out.extend(page)
        if len(page) < _PAGE:
            break
        offset += _PAGE
    return out


# ── Inputs ───────────────────────────────────────────────────────────────────
def fetch_official_scores(window_days: int) -> list[dict]:
    """Daily close scores with pillars + regime, from cis_official_daily."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).date().isoformat()
    rows = _get(_SCORES_TABLE, [
        ("select", "symbol,d,regime,pillar_f,pillar_m,pillar_o,pillar_s,pillar_a"),
        ("d", f"gte.{cutoff}"),
        ("order", "d.asc,symbol.asc"),
    ])
    out = []
    for r in rows:
        if not r.get("symbol") or not r.get("d") or not r.get("regime"):
            continue
        vals = {p: r.get(f"pillar_{p.lower()}") for p in PILLARS}
        if all(v is None for v in vals.values()):
            continue
        out.append({"symbol": r["symbol"], "d": str(r["d"])[:10],
                    "regime": str(r["regime"]).upper(), "pillars": vals})
    return out


def fetch_closes(symbols: list[str], start: str, end: str) -> dict[str, dict[str, float]]:
    """{symbol: {trade_date: close}} for the given window, one price per day.

    `symbol=in.(...)` is chunked (a long list in a query string is a 414 waiting
    to happen) and every chunk is paged with `order=symbol.asc,trade_date.asc`.
    """
    closes: dict[str, dict[str, float]] = {}
    chunk = 40
    for i in range(0, len(symbols), chunk):
        part = symbols[i:i + chunk]
        rows = _get(_PRICES_TABLE, [
            ("select", "symbol,trade_date,close,source"),
            ("symbol", f"in.({','.join(part)})"),
            ("trade_date", f"gte.{start}"),
            ("trade_date", f"lte.{end}"),
            ("order", "symbol.asc,trade_date.asc"),
        ])
        for r in rows:
            sym = r.get("symbol")
            day = str(r.get("trade_date"))[:10]
            close = r.get("close")
            if not sym or not day or close is None:
                continue
            slot = closes.setdefault(sym, {})
            prev = slot.get(day)
            if prev is None or _source_rank(r.get("source")) < _source_rank(_source_of(prev)):
                slot[day] = {"close": float(close), "source": r.get("source")}
    return {s: {d: v["close"] for d, v in days.items()} for s, days in closes.items()}


def _source_rank(source) -> int:
    try:
        return _SOURCE_PRIORITY.index(str(source))
    except ValueError:
        return len(_SOURCE_PRIORITY)


def _source_of(price) -> str:
    return price.get("source") if isinstance(price, dict) else ""


# ── Computation ──────────────────────────────────────────────────────────────
def _pearson(pairs: list[tuple[float, float]]) -> float | None:
    """Pearson r over (x, y) pairs. None if degenerate (zero variance on either side)."""
    n = len(pairs)
    if n < 3:
        return None
    mx = sum(x for x, _ in pairs) / n
    my = sum(y for _, y in pairs) / n
    sxy = sxx = syy = 0.0
    for x, y in pairs:
        dx, dy = x - mx, y - my
        sxy += dx * dy
        sxx += dx * dx
        syy += dy * dy
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def compute_fitness(scores: list[dict], closes: dict[str, dict[str, float]],
                    horizon: int = HORIZON_DAYS,
                    min_days: int = MIN_INDEPENDENT_DAYS,
                    min_samples: int = MIN_SAMPLES) -> list[dict]:
    """One row per (regime, pillar) that clears the sample floor.

    `return_source` is 'ohlcv_daily' — the price series the forward return came
    from. It is written so that a future reader can tell a real return from the
    score-change proxy the old writer fell back to.
    """
    # forward return per (symbol, day): close[d+h]/close[d] - 1
    buckets: dict[str, dict[str, list[tuple[str, float, float]]]] = {}
    for row in scores:
        sym, day, regime = row["symbol"], row["d"], row["regime"]
        series = closes.get(sym)
        if not series:
            continue
        base = series.get(day)
        target = series.get((datetime.fromisoformat(day) + timedelta(days=horizon)).date().isoformat())
        if base is None or target is None or base <= 0:
            continue
        fwd = target / base - 1.0
        for pillar, value in row["pillars"].items():
            if value is None:
                continue
            buckets.setdefault(regime, {}).setdefault(pillar, []).append((day, float(value), fwd))

    rows: list[dict] = []
    for regime, per_pillar in buckets.items():
        for pillar, triples in per_pillar.items():
            pairs = [(v, f) for _, v, f in triples]
            days = {d for d, _, _ in triples}
            if len(days) < min_days or len(pairs) < min_samples:
                continue
            corr = _pearson(pairs)
            if corr is None:
                continue
            rows.append({
                "regime": regime,
                "pillar": pillar,
                "correlation": round(corr, 6),
                "n_samples": len(pairs),
                "n_days": len(days),
                "window_days": 0,          # filled by the caller
                "return_source": "ohlcv_daily",
                "computed_at": datetime.now(timezone.utc).isoformat(),
            })
    rows.sort(key=lambda r: (r["regime"], r["pillar"]))
    return rows


def compute_fitness_pooled(scores: list[dict], closes: dict[str, dict[str, float]],
                            horizon: int = HORIZON_DAYS,
                            min_days: int = MIN_INDEPENDENT_DAYS,
                            min_samples: int = MIN_SAMPLES) -> list[dict]:
    """The SAME statistic pooled across regimes, written as regime='ALL'.

    WHY THIS EXISTS (measured 2026-11-17). The daily series has 38 distinct
    days, and the tape crossed regimes every few days: RISK_ON 5 days, EASING 4,
    NEUTRAL 19, TIGHTENING 3, RISK_OFF 7. A 20-independent-day floor is
    therefore unreachable PER REGIME for most of the table's life — the writer
    would produce nothing for months, which is the failure this whole card is
    about.

    The pooled row is not a way around the gate: it has to clear the SAME gate
    on the SAME kind of evidence (independent days, sample count). It answers a
    different question — "does this pillar predict the next 7 days, regardless
    of regime" — and it answers it with the pooled sample. The per-regime rows
    appear on their own as soon as a regime accumulates 20 independent days;
    until then the record says so instead of implying a per-regime answer.

    'ALL' is a literal, not a wildcard: it is not a regime the engine can
    assign, so nothing downstream can mistake it for one.
    """
    buckets: dict[str, list[tuple[str, float, float]]] = {}
    for row in scores:
        sym, day = row["symbol"], row["d"]
        series = closes.get(sym)
        if not series:
            continue
        base = series.get(day)
        target = series.get((datetime.fromisoformat(day) + timedelta(days=horizon)).date().isoformat())
        if base is None or target is None or base <= 0:
            continue
        fwd = target / base - 1.0
        for pillar, value in row["pillars"].items():
            if value is None:
                continue
            buckets.setdefault(pillar, []).append((day, float(value), fwd))

    rows: list[dict] = []
    for pillar, triples in buckets.items():
        pairs = [(v, f) for _, v, f in triples]
        days = {d for d, _, _ in triples}
        if len(days) < min_days or len(pairs) < min_samples:
            continue
        corr = _pearson(pairs)
        if corr is None:
            continue
        rows.append({
            "regime": "ALL",
            "pillar": pillar,
            "correlation": round(corr, 6),
            "n_samples": len(pairs),
            "n_days": len(days),
            "window_days": 0,          # filled by the caller
            "return_source": "ohlcv_daily",
            "computed_at": datetime.now(timezone.utc).isoformat(),
        })
    rows.sort(key=lambda r: (r["regime"], r["pillar"]))
    return rows


# ── Entry point ──────────────────────────────────────────────────────────────
def run(window_days: int = 90, dry_run: bool = False) -> dict:
    """Compute (and unless dry_run, write) today's fitness rows.

    Returns the shape the internal endpoint and the loop both read:
      ok / rows / degraded / reason / window_days / sample
    `degraded` + a reason means "inputs present, nothing cleared the floor" —
    the same honest shape S-202 introduced, so the loop records a refusal
    instead of an ok with zero rows.
    """
    conf = _sb_conf()
    if not conf:
        return {"ok": False, "degraded": True, "rows": 0,
                "reason": "SUPABASE_URL / SUPABASE_KEY not configured"}

    scores = fetch_official_scores(window_days)
    if not scores:
        return {"ok": False, "degraded": True, "rows": 0,
                "reason": f"{_SCORES_TABLE} has no pillar rows in the last {window_days}d",
                "consequence": "cis_regime_fitness stays empty ⇒ the IC record has nothing in it",
                "window_days": window_days}

    symbols = sorted({s["symbol"] for s in scores})
    dates = sorted(s["d"] for s in scores)
    closes = fetch_closes(symbols, dates[0], dates[-1])
    rows = compute_fitness(scores, closes) + compute_fitness_pooled(scores, closes)
    for r in rows:
        r["window_days"] = window_days

    if not rows:
        return {"ok": False, "degraded": True, "rows": 0,
                "reason": f"no (regime, pillar) pair cleared the floor "
                          f"({MIN_INDEPENDENT_DAYS} independent days, {MIN_SAMPLES} samples)",
                "consequence": "cis_regime_fitness stays empty ⇒ the IC record has nothing in it",
                "window_days": window_days,
                "n_scores": len(scores), "n_symbols": len(symbols),
                "n_priced": len(closes)}

    if dry_run:
        return {"ok": True, "dry_run": True, "rows": len(rows), "sample": rows[:5],
                "window_days": window_days, "n_scores": len(scores),
                "n_symbols": len(symbols), "n_priced": len(closes)}

    written = _post_rows(rows)
    return {"ok": bool(written), "rows": len(rows), "written": written,
            "window_days": window_days, "sample": rows[:5],
            "n_scores": len(scores), "n_symbols": len(symbols), "n_priced": len(closes)}


def _post_rows(rows: list[dict]) -> int:
    """Append today's batch. Plain POST: the table has an identity PK and no
    unique key on (regime, pillar) — a new batch per day is the intent
    (migration 2026-11-14: 'a new batch each day')."""
    conf = _sb_conf()
    if not conf:
        return 0
    base, key = conf
    payload = [{k: v for k, v in r.items() if v is not None} for r in rows]
    req = urllib.request.Request(
        f"{base}/rest/v1/{_TARGET_TABLE}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "Prefer": "return=representation"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
            return len(json.loads(body)) if body else len(payload)
    except urllib.error.HTTPError as e:
        _log.error("[regime_fitness] write REJECTED %s %s", e.code, e.read()[:300])
        return 0
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        _log.error("[regime_fitness] write failed: %s", e)
        return 0


if __name__ == "__main__":  # pragma: no cover - manual verification
    print(json.dumps(run(window_days=90, dry_run=True), indent=2, default=str))
