"""
① Beta Core book guard — the product book's invariants.

WHY IT EXISTS. On 2026-08-07 an oversight review found all five books accruing a
forward track record were long/short, gross ~1.0, market neutral — the ④
construction CLAUDE.md says "discards beta by construction", refuted again the same
day by S-103 and S-105. Layer ①, the FoF core AND the benchmark every other book is
measured against, had ZERO forward days. The 60-day gate is calendar-bound, so the
cost of that misallocation was 25 days that cannot be recovered.

These tests pin the properties that make the book worth the calendar it will spend:

  · LONG ONLY, exposure in [0, 1.3] — tilt, don't neutralize
  · the vol scalar can DE-lever without limit but can never lever past the ③ ceiling;
    a calm market must not silently produce 6x
  · unmeasured inputs (NaN vol, unknown regime) resolve to NEUTRAL, never to large.
    I1 says unmeasured is not zero; the corollary that matters for a book is that
    unmeasured is also not a licence to size up
  · the benchmark is computed from the same prices on the same day, so excess is
    arithmetic rather than a benchmark chosen later — S-103 showed choosing wrong
    manufactures significance and can flip its sign

Run: python3 -m tests.test_beta_core_book
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np  # noqa: E402

from src.data.signals import beta_core_paper as bc  # noqa: E402


def test_layer_one_is_equal_weight_and_long_only():
    """Layer ① holds the panel and expresses no view. The view belongs in layer ③
    (how much), never in layer ① (which) — putting it in ① is the ② tilt that
    S-103/S-105 refuted."""
    w = bc._equal_weights(["BTC", "ETH", "SOL", "BNB"])
    assert len(w) == 4
    assert all(v > 0 for v in w.values()), "layer ① must be long only"
    assert abs(sum(w.values()) - 1.0) < 1e-12
    assert len(set(round(v, 12) for v in w.values())) == 1, "equal weight, no tilt"
    assert bc._equal_weights([]) == {}, "empty panel must not divide by zero"


def test_vol_scalar_delevers_freely_but_cannot_lever_past_the_ceiling():
    """Asymmetry on purpose. Halving size in a storm is risk control; doubling it in
    a calm patch is leverage wearing risk control's clothes. A 10%-vol reading
    against a 60% target implies 6x, and 6x on a crypto panel is how a book dies in
    the gap it never traded through."""
    assert bc._vol_scalar(0.60) == 1.0
    assert bc._vol_scalar(1.20) == 0.5, "twice the target vol ⇒ half size"
    assert bc._vol_scalar(2.40) == 0.25, "de-levering is unbounded below"
    assert bc._vol_scalar(0.10) == bc._MAX_SCALAR, "calm must NOT imply 6x"
    assert bc._MAX_SCALAR <= 1.3, "the vol scalar may never exceed the ③ ceiling"


def test_unmeasured_inputs_resolve_to_neutral_not_to_large():
    """I1 says unmeasured is not zero. For a book the sharper corollary is that
    unmeasured is not a licence to size up: a missing vol reading and an unknown
    regime must both land on 1.0, which is the only value that asserts nothing."""
    assert bc._vol_scalar(float("nan")) == 1.0
    assert bc._vol_scalar(0.0) == 1.0, "a zero vol reading is broken data, not calm"
    assert bc._vol_scalar(-1.0) == 1.0
    assert bc._exposure_cap(None) == 1.0, "no regime ⇒ neutral, not a guess"
    assert bc._exposure_cap("SOME_REGIME_WE_HAVE_NEVER_SEEN") == 1.0


def test_exposure_caps_are_discrete_and_within_the_mandate():
    """Coarse on purpose: a continuous exposure function invites fitting, and the ⓠ
    spec's criterion is not Sharpe but 'did exposure come down in the first third of
    the drawdown'. Every reachable cap must also sit inside [0, 1.3] — no shorts."""
    caps = {bc._exposure_cap(r) for r in
            ("CRISIS", "CAPITULATION", "DELEVERAGING", "RISK_OFF", "CONTRACTION",
             "BEAR", "EUPHORIA", "EXPANSION", "RISK_ON", "BULL", "NEUTRAL", None)}
    assert caps <= set(bc._ALLOWED_CAPS), f"cap outside the allowed set: {caps}"
    assert min(caps) >= 0.0, "layer ① never shorts"
    assert max(caps) <= 1.3, "exposure mandate ceiling"
    assert bc._exposure_cap("CRISIS_DELEVERAGING") == 0.0, "crisis must reach flat"


def test_realized_vol_is_panel_level_and_nan_honest():
    """The book holds the panel, so the panel's volatility is the risk being
    targeted — averaging first and then taking sd is not the same as averaging the
    single-asset vols, and using the latter would systematically over-state risk and
    under-size the book."""
    rng = np.random.default_rng(0)
    ret = rng.normal(0, 0.03, (60, 10))
    panel_vol = bc._realized_vol(ret)
    mean_asset_vol = float(np.mean(np.nanstd(ret[-30:], axis=0))) * np.sqrt(365.0)
    assert panel_vol < mean_asset_vol, "diversification must show up in the target"
    short = bc._realized_vol(ret[:5])
    assert short != short, "too little history ⇒ NaN, never 0 (I1)"


def test_benchmark_leg_is_structural_not_a_later_choice():
    """S-103: `bench` was BTC on 7,706/7,743 outcome rows, and re-benchmarking to
    hold-the-panel turned t=−12.42 into −0.65 and flipped a sign. The defence is to
    remove the choice — the schema and the writer must both carry the benchmark."""
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "src/data/signals/beta_core_paper.py"), encoding="utf-8").read()
    assert "benchmark_nav" in src and "benchmark_return" in src
    assert "excess_return" in src, "excess must be written, not recomputed downstream"
    # both legs must be priced off the SAME snapshot; two price sources would make the
    # difference an artifact of timing rather than of exposure
    assert src.count("px[s] / mp[s] - 1.0") >= 2, \
        "book and benchmark legs must use the same prices on the same day"


def test_a_lost_cache_must_not_restart_the_clock():
    """The severe failure this book can have. State lives in Redis; if that key is
    evicted, a naive `if not state: inception` restarts the NAV at 1.0 and resets the
    60-day gate — while every log line stays green. That is S-105 (the strategy
    library spent 12 days in a 24h-TTL Redis key) with time as the lost object
    instead of rows, and time cannot be re-fetched.

    Supabase is the system of record and Redis is a cache, so a cache miss must read
    through, never start over."""
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "src/data/signals/beta_core_paper.py"), encoding="utf-8").read()
    assert "_recover_state_from_nav" in src, "no recovery path from the durable table"
    # recovery must be attempted BEFORE the inception branch can be reached
    rec = src.index("_recover_state_from_nav(px)")
    inc = src.index('"status": "inception"')
    assert rec < inc, "recovery must be attempted before inception is allowed"
    assert "beta_core_nav?select=mark_date,nav" in src, \
        "recovery must read the durable NAV table, not another cache"


def test_a_stalled_clock_is_observable_from_outside_the_process():
    """A daily loop that catches its exception and sleeps 24h fails by NOT WRITING.
    Nothing inside that process can report on it, and an in-process counter resets on
    exactly the deploy that broke it — so continuity is measured against the calendar
    from the durable table, and surfaced where an external probe can see it.

    Also asserts it stays OFF /health: that function is contractually I/O-free after
    the 2026-07-29 P0, and a continuity check needs a Supabase read. The fix for a
    health check sitting on a dead data layer must not become a health check that
    loads the data layer."""
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "src/data/signals/beta_core_paper.py"), encoding="utf-8").read()
    assert "def continuity_state" in src
    for field in ("days_since_mark", "missing_days", "gate_days_remaining", "stalled"):
        assert field in src, f"continuity must report {field}"

    main = open(os.path.join(os.path.dirname(__file__), "..", "src/api/main.py"),
                encoding="utf-8").read()
    assert "/internal/beta-core-clock" in main, "no external-probe surface for the clock"
    health = main[main.index("def _health_with_data_layer"):
                  main.index("def _health_with_data_layer") + 3000]
    assert "continuity_state" not in health, \
        "/health must stay I/O-free — the clock check belongs on its own endpoint"

    probe = open(os.path.join(os.path.dirname(__file__), "..",
                              "scripts/external_probe.sh"), encoding="utf-8").read()
    assert "beta-core-clock" in probe, \
        "the external probe is the only observer that survives the deploy that breaks marking"


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = f = 0
    for t in TESTS:
        try:
            t(); print(f"  ✓ {t.__name__}"); p += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__}\n      {e}"); f += 1
    print(f"\n{'✅' if not f else '🔴'} {p}/{len(TESTS)} beta-core book checks passed")
    sys.exit(1 if f else 0)
