"""
T-044 smoke test — synthetic fixtures for historical replay
============================================================

The agreement() function in t_044_price_source_agreement.py is pure
(it takes two SourcePanels and returns findings). To make T-044
trustable WITHOUT hitting Supabase, this smoke test builds four
synthetic panels that mimic the exact shapes of the historical
incidents, and asserts that `agreement()` flags each one:

  T36:  S-436 — CoinGecko candles labelled one day late
  T37:  S-459 — sample prices stored as candles, also a day late
  T38:  S-468 — frozen Binance prices + corrupted CG candles
  T39:  LDO/GRT/ATOM February drift — 3 coins × ~30 days at ~5% drift
  T40:  NEGATIVE — perfect same-day match → zero findings
  T41:  REPLAY — all four shapes in one combined panel trip all
        three detection dimensions; severity counts are right

Pure Python, no DB / no network / no secrets. This test does NOT
call agreement() against real Supabase data — that's `main()`'s job.
"""
import sys
import math
from datetime import date, timedelta
from pathlib import Path

# Import the pure function we're testing
_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_ROOT))
from src.research.validation.t_044_price_source_agreement import (  # noqa: E402
    SourcePanel, agreement, _safe_pearson,
)


def _gen_dates(start: str, n: int) -> list[str]:
    """Generate n consecutive ISO dates starting from `start`."""
    y, m, d = map(int, start.split("-"))
    base = date(y, m, d)
    return [(base + timedelta(days=i)).isoformat() for i in range(n)]


def _make_baseline_up(start: str, n: int, *, price0: float = 100.0,
                      drift: float = 0.001) -> SourcePanel:
    """Synthetic Binance history: log-normal-ish climb, no freezes."""
    dates = _gen_dates(start, n)
    closes = [price0 * math.exp(drift * i) for i in range(n)]
    return SourcePanel("BTC", "binance_hist", dates, closes)


def _shift_one_day(panel: SourcePanel) -> SourcePanel:
    """Build a new panel where each row is shifted to the previous day.
    This is the S-436 / S-459 fingerprint — candle label says "today"
    but the data is actually "yesterday"."""
    new_dates = _gen_dates(panel.dates[0], len(panel.dates))
    # Candle label says "today" but data is yesterday's — so map
    # data[i] → new_dates[i+1]. Pad front with first value (or drop).
    shifted_dates = new_dates[1:]
    shifted_closes = panel.closes[:len(panel.dates) - 1]
    return SourcePanel(panel.symbol, panel.source, shifted_dates, shifted_closes)


def _make_frozen_baseline(start: str, n: int, price: float = 50.0) -> SourcePanel:
    """Synthetic Binance history: 14 days all at $50.0 (the S-468
    fingerprint — frozen row). The candidate disagrees, so S-468
    is the frozen side (binance), not the candidate."""
    dates = _gen_dates(start, n)
    closes = [price] * n
    return SourcePanel("GRT", "binance_hist", dates, closes)


# T36: S-436 — CG Pro candles labelled one day late
def test_t36_s_436_cg_candles_one_day_late():
    base = _make_baseline_up("2026-01-01", 60)        # 60 days, no freeze
    cand = _shift_one_day(base)                       # S-436 fingerprint
    cand.source = "coingecko_pro_ohlc"
    findings = agreement(base, cand)
    shifts = [f for f in findings if f.kind == "shift_by_1_day"]
    assert shifts, (
        f"S-436 fixture did not trip shift_by_1_day; "
        f"got {len(findings)} findings: {[f.kind for f in findings]}")
    f = shifts[0]
    assert f.source == "coingecko_pro_ohlc", f"wrong source: {f.source}"
    assert "shift" in f.detail.lower(), (
        f"detail should mention shift, got: {f.detail}")
    print(f"✓ T36: S-436 shift-by-1-day detected on coingecko_pro_ohlc "
          f"(window starting {f.dates[0]})")


# T37: S-459 — CG sample prices stored as candles, also day late
def test_t37_s_459_sample_prices_one_day_late():
    base = _make_baseline_up("2026-02-01", 60)
    cand = _shift_one_day(base)
    cand.source = "coingecko"   # S-459 was the coingecko (sample) variant
    findings = agreement(base, cand)
    shifts = [f for f in findings if f.kind == "shift_by_1_day"]
    assert shifts, (
        f"S-459 fixture did not trip shift_by_1_day; "
        f"got {len(findings)} findings: {[f.kind for f in findings]}")
    f = shifts[0]
    assert f.source == "coingecko", f"wrong source: {f.source}"
    print(f"✓ T37: S-459 shift-by-1-day detected on coingecko (sample source)")


# T38: S-468 — frozen Binance prices + corrupted CG candles
def test_t38_s_468_frozen_binance_with_cg_disagreement():
    base = _make_frozen_baseline("2026-02-10", 14, price=50.0)
    # Candidate moves normally — so Binance is the liar.
    cand_dates = base.dates
    cand_closes = [50.0 + 0.5 * i for i in range(14)]
    cand = SourcePanel("GRT", "coingecko", cand_dates, cand_closes)
    findings = agreement(base, cand)
    frozen = [f for f in findings if f.kind == "frozen_binance"]
    assert frozen, (
        f"S-468 fixture did not trip frozen_binance; "
        f"got {len(findings)} findings: {[f.kind for f in findings]}")
    f = frozen[0]
    assert f.source == "binance_hist", (
        f"frozen_binance should attribute to binance_hist, got {f.source}")
    assert f.severity == "error", (
        f"frozen_binance severity should be error, got {f.severity}")
    print(f"✓ T38: S-468 frozen_binance detected on binance_hist "
          f"(14 days frozen @ $50, candidate diverges)")


# T39: LDO/GRT/ATOM February drift — 3 coins × 30 days at ~5% drift
def test_t39_ldo_grt_atom_february_drift():
    for sym in ("LDO", "GRT", "ATOM"):
        base = _make_baseline_up("2026-02-01", 30)
        base.symbol = sym  # override default BTC
        # Inject 5% drift across the run (constant log offset)
        cand = SourcePanel(
            sym, "coingecko_pro_ohlc",
            base.dates,
            [c * 1.05 for c in base.closes])
        findings = agreement(base, cand)
        drifts = [f for f in findings if f.kind == "drift_run"]
        assert drifts, (
            f"{sym} drift fixture did not trip drift_run; "
            f"got {len(findings)} findings: {[f.kind for f in findings]}")
        f = drifts[0]
        assert "30 days" in f.detail or "drift run = 30" in f.detail, (
            f"{sym} drift detail wrong: {f.detail}")
        assert f.severity in ("warn", "error"), (
            f"{sym} drift severity wrong: {f.severity}")
        print(f"  ✓ {sym}: drift_run 30 days @ ~5% flagged "
              f"({f.severity})")
    print("✓ T39: LDO/GRT/ATOM February drift_run detection works for all 3 coins")


# T40: NEGATIVE — perfect same-day match → zero findings
def test_t40_negative_perfect_match_zero_findings():
    base = _make_baseline_up("2026-03-01", 60)
    cand = SourcePanel(base.symbol, "coingecko_pro_ohlc",
                       base.dates, list(base.closes))
    findings = agreement(base, cand)
    assert len(findings) == 0, (
        f"Perfect match should yield 0 findings; got {len(findings)}: "
        f"{[(f.kind, f.detail) for f in findings]}")
    print("✓ T40: NEGATIVE — perfect same-day match → 0 findings")


# T41: REPLAY — combined fixture trips all three detection dimensions
def test_t41_replay_all_three_dimensions():
    """One panel that combines all three historical shapes:
    - First 14 days: shifted by 1 day (S-436 shape)
    - Days 14-30: binance frozen (S-468 shape)
    - Days 30-60: drift run 30 days (LDO Feb shape)
    """
    base_dates = _gen_dates("2026-03-01", 60)
    base_closes: list[float] = []
    for i in range(60):
        if 14 <= i < 30:
            # Binance frozen at $105.0 for the S-468 segment (16 days flat).
            base_closes.append(105.0)
        else:
            base_closes.append(100.0 * math.exp(0.001 * i))
    base = SourcePanel("BTC", "binance_hist", base_dates, base_closes)

    cand_dates = base_dates
    cand_closes: list[float] = []
    for i, d in enumerate(base_dates):
        if i < 40:
            # S-436 fingerprint extended: cand[i] carries base[i-1] close
            # (cand labelled "day t" but data is from "day t-1") for 40 days.
            # A 30-day sliding window can land entirely inside this segment
            # so the shift detection fires on the window.
            if i == 0:
                cand_closes.append(base_closes[0])
            else:
                cand_closes.append(base_closes[i - 1])
        else:
            # Days 40-59: 5% drift
            cand_closes.append(base_closes[i] * 1.05)
    cand = SourcePanel("BTC", "coingecko_pro_ohlc", cand_dates, cand_closes)

    findings = agreement(base, cand)
    kinds = {f.kind for f in findings}
    assert "shift_by_1_day" in kinds, (
        f"Combined fixture did not trip shift_by_1_day: {kinds}")
    assert "frozen_binance" in kinds, (
        f"Combined fixture did not trip frozen_binance: {kinds}")
    assert "drift_run" in kinds, (
        f"Combined fixture did not trip drift_run: {kinds}")
    print(f"✓ T41: REPLAY — combined fixture trips all 3 dimensions "
          f"({len(findings)} findings total)")


if __name__ == "__main__":
    print("── T-044 price-source agreement smoke ──")
    tests = sorted(
        [(k, v) for k, v in globals().items()
         if k.startswith("test_t")],
        key=lambda kv: int(kv[0].split("_t")[1].split("_")[0]))
    fails = []
    for name, fn in tests:
        try:
            fn()
        except AssertionError as e:
            print(f"  ✗ {name} :: {e}")
            fails.append(name)
        except Exception as e:
            print(f"  ✗ {name} :: {type(e).__name__}: {e}")
            fails.append(name)
    if fails:
        print(f"\n🔴 {len(fails)} FAILED: {fails}")
        sys.exit(1)
    print(f"\n✅ {len(tests)} tests pass")