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
import pathlib
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np  # noqa: E402

from src.data.signals import beta_core_paper as bc  # noqa: E402


_REPO = pathlib.Path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _src() -> str:
    return (_REPO / "src" / "data" / "signals" / "beta_core_paper.py").read_text(encoding="utf-8")


def _code_only_src() -> str:
    """Source with comments and string literals stripped.

    Needed because a guard that greps raw source fires on PROSE ABOUT the defect —
    it happened three separate times on 2026-08-09 (the lenient-canonicaliser scan,
    the truncating-query check, and this one), each time on a comment written to
    explain the very bug being guarded. Punishing the person who documents an
    incident is precisely the wrong incentive."""
    import io
    import tokenize
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(_src()).readline):
            if tok.type not in (tokenize.COMMENT, tokenize.STRING):
                out.append(tok.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return _src()
    return " ".join(out)



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
    assert bc._exposure_cap(None)[0] == 1.0, "no regime ⇒ neutral, not a guess"
    assert bc._exposure_cap("SOME_REGIME_WE_HAVE_NEVER_SEEN")[0] == 1.0


def test_exposure_caps_are_discrete_and_within_the_mandate():
    """Coarse on purpose: a continuous exposure function invites fitting, and the ⓠ
    spec's criterion is not Sharpe but 'did exposure come down in the first third of
    the drawdown'. Every reachable cap must also sit inside [0, 1.3] — no shorts."""
    caps = {bc._exposure_cap(r)[0] for r in
            ("RISK_OFF", "TIGHTENING", "STAGFLATION", "NEUTRAL", "EASING",
             "RISK_ON", "GOLDILOCKS", None, "A_LABEL_WE_HAVE_NEVER_SEEN")}
    assert caps <= set(bc._ALLOWED_CAPS), f"cap outside the allowed set: {caps}"
    assert min(caps) >= 0.0, "layer ① never shorts"
    assert max(caps) <= 1.3, "exposure mandate ceiling"


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


def test_regime_map_covers_the_canonical_vocabulary_exactly():
    """THE bug the book's first live mark exposed. The original mapping used invented
    labels — CRISIS, CAPITULATION, EUPHORIA, EXPANSION, BULL, BEAR — none of which
    exist in the canonical set. Measured against the live table, only RISK_OFF
    (40.2 % of days) and RISK_ON (12.3 %) ever matched, so **47.5 % of days silently
    defaulted to full exposure** and layer ③ was inert without announcing it.

    Those names were half-remembered from EXPOSURE_BANDS_V1, a different vocabulary
    keyed off a different input. Same shape as `asset_class` and `bench` before it:
    a mapping written against an imagined vocabulary instead of the real one. Pinning
    it to the canonical set means the next added regime breaks CI rather than
    silently becoming full exposure."""
    from src.data.cis.cis_provider import _CANONICAL_REGIMES
    assert set(bc._REGIME_CAP) == set(_CANONICAL_REGIMES), (
        f"regime map must cover the canonical set exactly.\n"
        f"  missing:  {set(_CANONICAL_REGIMES) - set(bc._REGIME_CAP)}\n"
        f"  invented: {set(bc._REGIME_CAP) - set(_CANONICAL_REGIMES)}")
    for regime, cap in bc._REGIME_CAP.items():
        assert cap in bc._ALLOWED_CAPS, f"{regime} maps to {cap}, outside ALLOWED_CAPS"


def test_layer_three_not_running_is_distinguishable_from_choosing_neutral():
    """`exposure_cap = 1.0` carries three different meanings: ③ evaluated and chose
    neutral, ③ met a label it does not know, or ③ got no input at all. Folding them
    into one number is the -2-into-0 conflation one layer up — and it is exactly what
    hid the inert mapping on the first mark."""
    assert bc._exposure_cap("NEUTRAL")   == (1.0, "regime_map")
    assert bc._exposure_cap(None)        == (1.0, "no_regime")
    assert bc._exposure_cap("NEW_LABEL") == (1.0, "unmapped_regime")
    assert len({bc._exposure_cap(r)[1] for r in ("NEUTRAL", None, "NEW_LABEL")}) == 3, \
        "all three must be separately reportable"
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "src/data/signals/beta_core_paper.py"), encoding="utf-8").read()
    assert '"cap_source"' in src, "cap_source must be WRITTEN to the row, not just computed"


def test_regime_labels_normalise_the_way_the_live_table_spells_them():
    """The live table carries 'Risk-Off' and 'Tightening' beside 'RISK_OFF'. Matching
    on underscores alone misses the hyphenated variants — 0.9 % of days, small enough
    to survive review and large enough to mis-size a book."""
    for variant in ("Risk-Off", "risk off", "RISK_OFF", " Tightening "):
        assert bc._exposure_cap(variant)[1] == "regime_map", f"{variant!r} not normalised"
    assert bc._exposure_cap("Risk-Off")[0] == bc._exposure_cap("RISK_OFF")[0]


def test_the_dwell_length_is_imported_not_tuned():
    """S-118 wired a 5-day dwell filter onto the regime before it sizes the book.
    The number is NOT chosen against a return — it equals the minimum holding
    period the SHIP gate already requires, so it is a constraint imported from
    elsewhere. A dwell length picked for how clean the chart looks would make the
    smoothing itself the edge, which is the R76–R94 error in new clothes."""
    assert bc._REGIME_DWELL_DAYS == 5, (
        "dwell must equal the gate's minimum holding period; changing it needs a "
        "reason that is not 'the curve looked better'")
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "src/data/signals/beta_core_paper.py"), encoding="utf-8").read()
    assert "NOT tuned" in src, "the provenance of the dwell length must be stated"
    assert "dwell_filter" in src, "the filter must actually be applied, not just cited"


def test_confirmed_and_raw_regime_are_both_carried():
    """The filter's effect has to be visible in the row. Returning only the
    confirmed value would make 'the filter did nothing today' indistinguishable
    from 'the filter is not running' — the S-116 failure exactly, where an inert
    mapping survived a whole first mark behind a correct-looking 1.0."""
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "src/data/signals/beta_core_paper.py"), encoding="utf-8").read()
    assert "-> tuple[str | None, str | None]" in src, \
        "_current_regime must return (confirmed, raw)"
    assert "regime, regime_raw = await _current_regime()" in src
    assert "regime != regime_raw" in src and "dwell" in src, \
        "cap_source must record when the filter CHANGED the decision"
    assert "return raw, raw" in src, \
        "too little history must return them EQUAL — stated, not silent"


def test_the_filter_is_the_one_from_the_validated_module():
    """Not a reimplementation. `state_persistence.dwell_filter` is causal and has
    its own guards; a second copy inside the book would drift from them, and the
    copy that drifts is always the one running live."""
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "src/data/signals/beta_core_paper.py"), encoding="utf-8").read()
    assert "from src.research.validation.state_persistence import dwell_filter" in src, \
        "must import the guarded filter rather than reimplement it"




# ── inception identity (2026-08-09, S-123) ──────────────────────────────────

def test_inception_id_is_a_code_constant_not_an_env_var():
    """THE INTEGRITY PROPERTY OF THE WHOLE PRODUCT.

    The deliverable is a forward track record. A track record whose NAV can be
    quietly reset proves nothing — if a bad month can be erased by flipping a
    dashboard variable or clearing a cache key, sixty green days are worth zero,
    because the reader cannot tell sixty days of survival from the sixtieth attempt.

    So re-inception has to cost a commit: reviewed, dated, attributed, permanently
    visible in `git log` beside its reason. That friction is the feature. Reading the
    id from the environment would move the decision to a place with no history."""
    src = _src()
    assert re.search(r'^_INCEPTION_ID\s*=\s*["\']', src, re.M), \
        "_INCEPTION_ID must be a literal module constant"
    body = re.sub(r'#.*', '', src)
    for pat in (r'_INCEPTION_ID\s*=\s*os\.', r'_INCEPTION_ID\s*=\s*.*getenv',
                r'_INCEPTION_ID\s*=\s*.*environ'):
        assert not re.search(pat, body), \
            "_INCEPTION_ID must never come from the environment — that is a reset with no git trace"
    assert re.search(r'^_INCEPTION_REASON\s*=', src, re.M), \
        "an incarnation must carry the reason the previous one was abandoned"


def test_every_read_path_is_scoped_to_the_live_incarnation():
    """Three queries read this table: state recovery, continuity, and the published
    curve. All three must exclude other incarnations and voided rows.

    Recovery is the subtle one — unscoped, the next Redis eviction would 'recover'
    the NAV of the run the re-inception was meant to replace, resurrecting the voided
    segment while logging a perfectly healthy recovery. The published curve is the
    loud one: splicing a void segment onto a live one reads as a continuous 60-day
    record containing a discontinuity at the seam, and the curve IS the claim."""
    # The queries are built across several f-string lines, so a single-line regex
    # sees only the first fragment and passes on a query it never actually read.
    # Take the statement, not the line.
    lines = _src().splitlines()
    starts = [i for i, l in enumerate(lines) if "beta_core_nav?select=" in l]
    assert len(starts) >= 3, f"expected the three read paths, found {len(starts)}"
    for i in starts:
        stmt = " ".join(lines[i:i + 5])
        assert "inception_id=eq." in stmt, \
            f"read path not scoped to an incarnation (line {i+1}): {stmt[:110]}"
        assert "void_reason=is.null" in stmt, \
            f"read path does not exclude voided rows (line {i+1}): {stmt[:110]}"


def test_written_rows_carry_their_incarnation():
    """A row without an id cannot be attributed to a run, so a later query cannot
    exclude it — the stamp has to happen at write time or not at all."""
    src = _src()
    assert '"inception_id": _INCEPTION_ID' in src, \
        "every written row must be stamped with the incarnation that produced it"


def test_superseded_runs_are_voided_not_deleted():
    """CLAUDE.md: the graveyard is the asset. The migration marks v1 with a reason and
    leaves the rows queryable. A record that shows only survivors is precisely the
    bias S-111 measured at 25.1 pp/yr — we do not get to apply it to ourselves."""
    p = _REPO / "scripts" / "supabase_beta_core_reinception.sql"
    assert p.exists(), "scripts/supabase_beta_core_reinception.sql missing"
    sql = p.read_text(encoding="utf-8")
    assert "void_reason" in sql and "update beta_core_nav" in sql.lower()
    assert not re.search(r'\bdelete\s+from\s+beta_core_nav', sql, re.I), \
        "superseded marks must be voided in place, never deleted"
    assert "DO NOT REORDER" in sql, \
        "the deploy-before-void ordering must be stated: voiding first hides the fault"





def test_durable_write_precedes_the_cache_and_its_failure_is_honoured():
    """2026-08-09, found live. After the v2 re-inception the Redis state key
    reappeared while beta_core_nav still held ZERO v2 rows — the signature of a cache
    write that succeeded beside a durable write that failed and was swallowed.

    `_write` logged its exception and returned None, and both call sites set the cache
    BEFORE calling it. The consequence is not a missing row. `last_mark` advances, so
    the next cycle reports already_marked and the day after computes its return from
    mark_prices two days old and books it as a one-day move — the gap stops being
    visible as a gap and becomes visible as a return.

    S-105 in a new place, and Lesson #107: the operation ran and the state changed are
    separate facts. Refusing to cache an unrecorded mark costs one cycle; caching it
    costs the clock, silently, which is the only thing this book produces."""
    src = _src()
    # NOT a string match on `return True` — that assertion failed against the CORRECT
    # implementation (`return bool(ok)`), which is a brittle-guard smell in itself.
    # The behavioural check lives in test_write_reports_failure_when_the_insert_RETURNS_false;
    # this one only pins the ordering, which behaviour cannot easily observe.
    assert "NAV WRITE FAILED" in src, "a raised durable write must log at error level"
    assert "NAV WRITE REJECTED" in src, \
        "a RETURNED failure must log too — it is the path a PostgREST 400 takes"
    for branch in ("inception_failed", "mark_failed"):
        assert branch in src, f"a failed durable write must surface as {branch}"
    # ordering: in both branches the _write call must appear before the _redis_set
    for anchor in ("INCEPTION NOT PERSISTED", "MARK NOT PERSISTED"):
        i = src.index(anchor)
        seg = src[max(0, i - 900):i]
        assert "await _write(" in seg, f"{anchor}: durable write must precede the guard"
        w = seg.rindex("await _write(")
        assert "_redis_set(_STATE_KEY" not in seg[w:], \
            f"{anchor}: the cache is still being written before the durable row"





def test_a_missing_return_stays_missing_and_cannot_read_as_calm():
    """2026-08-09. `_load_panel` used `np.nan_to_num` on the return matrix, so a
    missing bar became a 0.0 return — a flat day. Flat days depress realised vol, the
    vol scalar rises, and the book SIZES UP: unmeasured read as calm, and calm read
    as licence to lever, which is the one direction I1 exists to forbid.

    Lesson #108, and the instructive part is where the guard already was. This file
    asserted `_vol_scalar(nan) == 1.0`, and `_realized_vol` already used
    nanmean/nanstd — every level handled NaN correctly except the one that destroyed
    it first. **An invariant enforced at a point the data cannot reach is not
    enforced.** The question is never "is this asserted somewhere", it is "can a
    value that violates it actually arrive at the assertion"."""
    # Match CODE, not prose. Three guards today first fired on comments describing the
    # very defect they check — a scanner that cannot tell use from mention punishes
    # whoever documents the incident, which is the opposite of the incentive we want.
    assert "nan_to_num" not in _code_only_src(), \
        "nan_to_num on the return matrix converts unmeasured into flat, which levers up"

    # behavioural: a gap must lower nothing. Build a panel where one asset has a hole
    # and confirm the measured vol is not pulled DOWN relative to the same panel with
    # that asset absent entirely.
    rng = np.random.default_rng(7)
    ret = rng.normal(0, 0.04, (60, 6))
    holed = ret.copy()
    holed[20:40, 3] = np.nan                     # a 20-day outage on one name
    zeroed = ret.copy()
    zeroed[20:40, 3] = 0.0                       # what nan_to_num used to produce
    v_holed, v_zeroed = bc._realized_vol(holed), bc._realized_vol(zeroed)
    assert v_holed == v_holed, "a hole must still yield a measurable panel vol"
    assert v_holed >= v_zeroed, (
        f"zero-filling a gap understates panel vol ({v_zeroed:.4f} vs {v_holed:.4f}) "
        "and therefore oversizes the book")


def test_a_name_without_a_usable_price_is_excluded_not_carried_as_nan():
    """A NaN price would propagate into the weights and into the benchmark leg, where
    it can drop an asset from one and not the other — turning a data gap into an
    apparent excess return. Absent price means absent from the panel."""
    src = _src()
    assert "close[-1, i] == close[-1, i]" in src and "> 0" in src, \
        "prices must be filtered for NaN and non-positive before entering the book"
    assert "have no usable price" in src, \
        "an excluded name must be logged — a silently smaller panel is a silent change of book"





def test_write_reports_failure_when_the_insert_RETURNS_false():
    """The fourth instance of Lesson #108 today, and the one I caused.

    `supabase_insert_table` reports failure by RETURNING False — a PostgREST 400
    (unknown column, RLS refusal, constraint violation) never raises. The first
    version of the durable-write fix wrapped the call in try/except and returned True
    unconditionally, so the brand-new `if not ok` guard sat at a point the real
    failure could not reach. The guard written to enforce "check the target, not the
    action" was itself checking the action.

    This test is behavioural on purpose. Reading the code did not catch it; only
    making the dependency fail did. Any guard for this class has to actually induce
    the failure, because the whole failure mode is that it looks fine."""
    import asyncio
    import datetime as _dt
    import src.api.store as store

    calls = {}
    original = store.supabase_insert_table

    async def _reject(table, rows):
        calls["table"] = table
        return False                      # exactly how a 400 surfaces — no exception

    async def _accept(table, rows):
        return True

    try:
        store.supabase_insert_table = _reject
        got = asyncio.run(bc._write(_dt.date(2026, 8, 9), 1.0, 1.0, 0.0, 0.0, 0.5,
                                    "TIGHTENING", 1.0, 0.5, 3, 0.5, 0.0, True,
                                    {"BTC": 0.5}, "probe"))
        assert got is False, (
            "_write returned %r when the insert returned False — the caller will "
            "cache a mark that was never persisted" % (got,))
        assert calls.get("table") == "beta_core_nav"

        store.supabase_insert_table = _accept
        assert asyncio.run(bc._write(_dt.date(2026, 8, 9), 1.0, 1.0, 0.0, 0.0, 0.5,
                                     "TIGHTENING", 1.0, 0.5, 3, 0.5, 0.0, True,
                                     {"BTC": 0.5}, "probe")) is True, \
            "a successful insert must report True, or every mark is treated as failed"
    finally:
        store.supabase_insert_table = original





def test_the_row_key_carries_the_incarnation_not_just_the_date():
    """2026-08-09. The v2 inception failed with a 409: `PRIMARY KEY (mark_date)` meant
    v1's VOIDED row for the same day forbade v2's row.

    The re-inception design gave a row a second dimension of identity — which
    incarnation produced it — and deliberately kept superseded rows in place. But the
    key still asserted that a row IS a date, so the old definition of identity vetoed
    the new one. Same family as the L0 defect where asset_class lived on observation
    rows: an identity recorded at the wrong grain. Here the column had the right
    grain and the key did not.

    **When an entity gains a dimension of identity, its uniqueness constraint must
    gain it in the same change.**"""
    p = _REPO / "scripts" / "supabase_beta_core_pk_by_incarnation.sql"
    assert p.exists(), "scripts/supabase_beta_core_pk_by_incarnation.sql missing"
    sql = p.read_text(encoding="utf-8").lower()
    assert "primary key (inception_id, mark_date)" in sql, \
        "the key must be composite — incarnation first, then date"
    assert "set not null" in sql, \
        "inception_id must be NOT NULL, or a null silently drops out of the key"
    assert "23505" in sql, "record the actual error that exposed it"


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
