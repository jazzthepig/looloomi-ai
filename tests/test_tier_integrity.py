"""S-180 / S-181 — the T1↔T2 boundary, guarded at the three places it broke.

WHAT HAPPENED (2026-08-19). `redis_get_key`'s docstring said "Returns None on
miss/error", and `_build_cis_universe` read that None as "the Mac engine has not
pushed". So a Redis transport failure — one dropped request — demoted the ENTIRE
58-asset universe from T1 to T2 in a single step. That is not a precision
change: measured on BTC the same instant, T1 said F=50 O=27 S=59 and T2 said
F=80 O=59 S=20, a ~13-point systematic score gap that crosses both the grade
boundary and the positioning boundary.

The hourly snapshot loop then wrote those rows into `cis_scores`, because its
guard is `tier_label == "T2"` and every asset now truthfully claimed to be T2.
Base rate measured over 266 hours: 8 hours affected (3.0%), 473 rows. Rare, and
wholesale when it fires — including 2026-08-19 11:00, inside the rally window
that prompted the investigation.

WHY TESTS AND NOT CARE. This is the THIRD instance of one class in a week
(`supabase_table_exists` missing-vs-unreachable S-166; loop-health "flowing" off
a single fresh row S-179). Each was fixed at the instance. Fixing the instance
is not fixing the class, so the class gets a test.
"""
import ast
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ── 1. The read must carry WHY it is empty ───────────────────────────────────

def test_redis_read_distinguishes_miss_from_error():
    """`redis_get_key_status` must return a status, and must never call an HTTP
    failure a miss. Two-valued returns are what manufactured S-180."""
    from src.api.store import redis_get_key_status
    src = pathlib.Path(ROOT / "src/api/store.py").read_text()
    fn = src.split("async def redis_get_key_status")[1].split("\nasync def ")[0]

    for status in ("hit", "miss", "error", "unconfigured"):
        assert f'"{status}"' in fn, f"redis_get_key_status must be able to report {status!r}"

    # The non-200 branch must NOT fall through to "miss".
    assert "status_code != 200" in fn, "must branch on non-200 explicitly"
    non200 = fn.split("status_code != 200")[1].split("raw =")[0]
    assert '"error"' in non200 and '"miss"' not in non200, (
        "an HTTP error is not a miss — Upstash answers 200/result=null for an "
        "absent key. Calling a failed request a miss is exactly the S-180 bug.")


def test_tier_decision_does_not_use_the_two_valued_read():
    """`_build_cis_universe` must decide T1-vs-T2 on the status-carrying read."""
    src = pathlib.Path(ROOT / "src/api/routers/cis.py").read_text()
    body = src.split("async def _build_cis_universe")[1].split("\nasync def ")[0]

    assert "redis_get_status()" in body, (
        "the tier decision must use redis_get_status(); plain redis_get() cannot "
        "tell an absent Mac push from an unreachable Redis")
    assert re.search(r"^\s*cached\s*=\s*await\s+redis_get\(\)", body, re.M) is None, (
        "bare `cached = await redis_get()` reintroduces S-180")
    assert '== "error"' in body, (
        "the builder must branch on the error status and hold last-good T1 "
        "rather than demoting the whole universe")


# ── 2. The writer must refuse to shadow a live T1 ────────────────────────────

def test_hourly_t2_writer_checks_t1_occupancy():
    """Belt and braces: even with a wrong tier label upstream, the T2 writer must
    not overwrite a symbol that already has a fresh T1 row."""
    src = pathlib.Path(ROOT / "src/api/main.py").read_text()
    # Split on the DEFINITION, not the first mention — the name appears in a
    # create_task() call earlier in the file, and slicing there yields a window
    # that does not contain the loop at all. (First version of this test did
    # exactly that and "failed" against correct code.)
    loop = src.split("async def _hourly_t2_snapshot_loop")[1].split("\nasync def ")[0]

    assert "supabase_fresh_t1_symbols" in loop, (
        "the hourly T2 loop must consult the TABLE, not just the payload's own "
        "tier label — the label was wrong for all 58 assets on 2026-08-19")

    # Match the CALL SITE, not the name — the loop imports both symbols at its
    # top, so `.find("supabase_insert_batch")` lands on the import and reports
    # the insert as happening first. A guard that matches a name where it meant
    # a call is the same mistake this whole file exists to catch.
    insert_at = loop.find("await supabase_insert_batch(")
    check_at = loop.find("await supabase_fresh_t1_symbols(")
    assert insert_at > 0, "expected an `await supabase_insert_batch(` call in the loop"
    assert 0 <= check_at < insert_at, (
        "the occupancy check must run BEFORE the insert, not after it "
        f"(check at {check_at}, insert at {insert_at})")


def test_unknown_t1_occupancy_blocks_the_write():
    """None means 'could not ask'. Not-knowing is not permission."""
    src = pathlib.Path(ROOT / "src/api/main.py").read_text()
    loop = src.split("async def _hourly_t2_snapshot_loop")[1].split("\nasync def ")[0]
    assert "fresh_t1 is None" in loop, (
        "must branch explicitly on the unknown case")
    none_branch = loop.split("fresh_t1 is None")[1].split("elif")[0]
    assert "t2_rows = []" in none_branch, (
        "when T1 occupancy is unknown the write must be HELD. A missing hour is "
        "recoverable; an hour of rows shadowing a live T1 is not.")


def test_t1_occupancy_read_is_three_valued():
    from src.api.store import supabase_fresh_t1_symbols  # noqa: F401
    src = pathlib.Path(ROOT / "src/api/store.py").read_text()
    fn = src.split("async def supabase_fresh_t1_symbols")[1].split("\nasync def ")[0]
    assert "return None" in fn and "set[str] | None" in fn, (
        "must be able to say 'I could not ask' distinctly from 'there are none'")


# ── 3. The UI must not assert facts it has not checked ───────────────────────

_RADAR = ROOT / "dashboard/src/components/AssetRadar.jsx"
_LEADER = ROOT / "dashboard/src/components/CISLeaderboard.jsx"
_WIDGET = ROOT / "dashboard/src/components/CISWidget.jsx"


def test_radar_footer_does_not_hardcode_a_tier():
    """The footer said 'T2 Market Est.' unconditionally while 43 of 58 rows were
    T1 — which is what made two pages showing the SAME number look different."""
    txt = _RADAR.read_text()
    footer = txt.split("── Footer")[1]
    assert "dataTier" in footer, "the tier claim must be derived from the rows"
    assert not re.search(r'\{"\s*·\s*"\}<span[^>]*>T2</span>\s*Market Est\.',
                         footer.replace("\n", " ")) or "t1 === 0" in footer, (
        "an unconditional T2 claim is a hardcoded assertion about live data")


def test_two_views_of_the_same_number_sample_on_the_same_clock():
    """AssetRadar and CISLeaderboard read the identical field from the identical
    endpoint. If one refreshes and the other does not, they drift apart and the
    drift is misread as a scoring difference."""
    radar = _RADAR.read_text()
    leader = _LEADER.read_text()
    for name, txt in (("AssetRadar", radar), ("CISLeaderboard", leader)):
        assert "/api/v1/cis/universe" in txt, f"{name} should read the shared endpoint"
        assert "setInterval" in txt, (
            f"{name} never refreshes. BTC moved 44→58 over 2026-08-19; a page "
            f"frozen at mount showed a grade a full letter from its sibling.")

    def interval(txt):
        m = re.findall(r"setInterval\(\s*\w+\s*,\s*([\d_]+)\s*\)", txt)
        return {int(x.replace("_", "")) for x in m}

    assert interval(radar) & interval(leader), (
        f"the two views must share a cadence — radar={interval(radar)} "
        f"leaderboard={interval(leader)}")


def test_no_ui_box_promises_an_indicator_no_endpoint_produces():
    """Five boxes — Fed, 10Y, VIX, DXY, CPI — rendered an em-dash every day since
    launch because nothing in the backend has ever emitted those fields. An
    em-dash reads as a feed hiccup, so an absence disguised itself as an outage
    and survived indefinitely."""
    widget = _WIDGET.read_text()
    backend = "\n".join(
        p.read_text() for p in (ROOT / "src").rglob("*.py")
        if "__pycache__" not in str(p))

    banner = widget.split("export function CISMacroBanner")[1].split("\nexport ")[0]
    # Collapse runs of whitespace before substring-matching the guard. The source
    # aligns `!= null` into a column, so `macro?.fed_funds     != null` does not
    # contain the literal `macro?.fed_funds != null` — the first version of this
    # test reported five dead boxes against code that had already guarded them.
    flat = re.sub(r"\s+", " ", banner)
    for field in ("fed_funds", "treasury_10y", "vix", "dxy", "cpi_yoy",
                  "regime_confidence"):
        if f"macro?.{field}" not in banner:
            continue
        produced = f'"{field}"' in backend or f"'{field}'" in backend
        guarded = f"macro?.{field} != null" in flat
        assert produced or guarded, (
            f"CISMacroBanner renders {field!r}, no backend endpoint produces it, "
            f"and it is not null-guarded out of the DOM — so it will display a "
            f"permanent em-dash claiming we track a series we do not.")


def test_macro_banner_is_passed_what_it_reads():
    """The caller passed `{ regime }`; the component read six fields."""
    widget = _WIDGET.read_text()
    call = widget.split("<CISMacroBanner")[1].split("/>")[0]
    banner = widget.split("export function CISMacroBanner")[1].split("\nexport ")[0]
    flat = re.sub(r"\s+", " ", banner)   # see note in the test above
    read = set(re.findall(r"macro\?\.(\w+)", banner))
    passed = set(re.findall(r"(\w+)\s*:", call)) | {"regime"}
    unpassed = {f for f in read - passed if f"macro?.{f} != null" not in flat}
    assert not unpassed, (
        f"CISMacroBanner reads {sorted(unpassed)} which the caller never passes "
        f"and which are not null-guarded — dead boxes by construction")


# ── 4. Cache windows must not outlive what they cache ────────────────────────

@pytest.mark.parametrize("path", ["src/api/routers/macro.py"])
def test_swr_window_does_not_exceed_the_refresh_cadence(path):
    """`stale-while-revalidate=3600` let a cold CDN edge serve a brief up to 70
    minutes old — longer than the 30-minute cadence that produces it, so the
    window could span an entire missed update. That is the cross-device lag."""
    txt = (ROOT / path).read_text()
    for m in re.finditer(r"max-age=(\d+),\s*stale-while-revalidate=(\d+)", txt):
        max_age, swr = int(m.group(1)), int(m.group(2))
        assert swr <= max_age, (
            f"{path}: max-age={max_age} but stale-while-revalidate={swr}. A SWR "
            f"window longer than the freshness window means the stale copy "
            f"outlives the fresh one — readers on cold edges see the past.")
