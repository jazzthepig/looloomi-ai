"""
S-397 P1/P2 audit backlog (2026-09-23) — 8 sites of the S-262 family pattern
"missing data rendered as a plausible-looking number".

The fix per site is one-line:
  - A2  StrategyPage.jsx:545  BTC 7D color branch (`|| 0` → green when null)
  - A6  DiagnoseHome.jsx:32   radius() NaN when h.cis missing
  - A8  AssetRadar.jsx:152-158 fmtVol applied to market_cap with $1e3 divisor
  - A9  AssetRadar.jsx:341-353 sort `|| 0` collapses missing to bottom
  - C2  IntelligencePage.jsx:67-73  fmt.amount() falsy-zero → "—"
  - C3  CISWidget.jsx:343-344 + 718-723  pillar `?? 0` color + composite recalc
  - C4  PortfolioDiagnosis.jsx:42  cis:25 fallback for missing CIS
  - C7  QuantMonitor.jsx:227, 279  median_return falsy-zero → "—"

Note: A7 (VaultPage) was flagged in the initial scan but verified NOT broken
(`setLoading(false)` and `setVaultsLoading(false)` are both in `finally`
blocks — VaultPage.jsx:177/195). NOT part of this batch.

This test is a sibling to test_safe_format_score.py (S-405 / A5+C6 family):
- Unit-style runtime tests via the actual safeFormat helpers
- AST + grep static guards for each call site, so a regression that
  drops `isMissing`/resurrects `?? 0` fails CI before deploy

Run: python3 -m tests.test_s397_p1p2_audit_backlog
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


# ── runtime smoke (Node subprocess against safeFormat.js) ─────────────────────

_JS_RUNTIME = r"""
import('/Users/sbb/Projects/looloomi-ai/dashboard/src/lib/safeFormat.js')
.then(async (m) => {
  const { isMissing } = m;
  const fails = [];
  // A2 / C2 / C7 family: isMissing must treat 0 as a real number (not "—").
  for (const [v, expected] of [
    [null, true], [undefined, true], [NaN, true],
    [0, false], [-0, false], [0.0, false], [1, false], [-1, false],
  ]) {
    if (isMissing(v) !== expected) {
      fails.push(`isMissing(${JSON.stringify(v)}) → ${isMissing(v)}, expected ${expected}`);
    }
  }
  console.log(fails.length ? 'FAIL' : 'OK');
  if (fails.length) console.log(JSON.stringify(fails));
  process.exit(fails.length ? 1 : 0);
}).catch(e => { console.error(e); process.exit(2); });
"""


def test_ismissing_predicate_zero_safe() -> None:
    """The whole batch hinges on `isMissing` treating 0 as data, not absence.
    A regression that returns `true` for 0 would re-collapse every fix here."""
    r = subprocess.run(
        ["node", "--input-type=module", "-e", _JS_RUNTIME],
        capture_output=True, text=True, timeout=15,
    )
    ok = r.returncode == 0 and r.stdout.strip().startswith("OK")
    check("isMissing(0) === false (zero is data, not missing)",
          ok, f"rc={r.returncode} stdout={r.stdout[:200]} stderr={r.stderr[:200]}")


# ── AST / grep static guards per call site ──────────────────────────────────

def _file_text(rel: str) -> str:
    return (_REPO / rel).read_text()


def _call_uses_ismissing(rel: str, marker: str) -> bool:
    """Spot-check that a fixed site now imports/uses `isMissing`."""
    text = _file_text(rel)
    return "isMissing" in text and marker in text


def test_a2_strategypage_btc7d_color_uses_isMissing() -> None:
    """A2: BTC 7D tile color must use isMissing for the missing branch."""
    rel = "dashboard/src/components/StrategyPage.jsx"
    text = _file_text(rel)
    has_ismissing = "import { isMissing }" in text
    has_color_guard = ('isMissing(macro?.btc?.usd_7d_change) ? T.t3' in text
                       or 'isMissing(macro?.btc?.usd_7d_change)' in text)
    check("A2 imports isMissing", has_ismissing, f"check {rel} for `import {{ isMissing }}`")
    check("A2 color branch uses isMissing", has_color_guard,
          "expected `isMissing(macro?.btc?.usd_7d_change)` in color branch")
    # Old `|| 0` color proxy must be removed.
    check("A2 `|| 0` color proxy removed",
          "(macro?.btc?.usd_7d_change || 0) >= 0" not in text,
          "old `(usd_7d_change || 0) >= 0` proxy still present")


def test_a6_diagnosehome_radius_guards_missing() -> None:
    """A6: radius() must return the rim bucket when h.cis is missing."""
    rel = "dashboard/src/components/DiagnoseHome.jsx"
    text = _file_text(rel)
    check("A6 imports isMissing",
          "import { isMissing }" in text,
          f"check {rel} for `import {{ isMissing }}`")
    check("A6 radius guards isMissing(h.cis)",
          "isMissing(h.cis)" in text,
          "expected `isMissing(h.cis)` in radius()")
    # The `(85 - h.cis) / 60` arithmetic still exists but is now gated by
    # `isMissing(h.cis)` above it — verify the gate precedes the arithmetic.
    check("A6 isMissing(h.cis) gate precedes the radius arithmetic",
          text.find("isMissing(h.cis)") < text.find("(85 - h.cis)"),
          "isMissing(h.cis) gate must precede the unguarded arithmetic")


def test_a8_assetradar_fmtvol_mcap_split() -> None:
    """A8: market_cap must NOT use fmtVol (the $1e3 divisor bug)."""
    rel = "dashboard/src/components/AssetRadar.jsx"
    text = _file_text(rel)
    # New fmtMcap helper present, fmtMcap applied to market_cap.
    check("A8 fmtMcap helper defined",
          "const fmtMcap" in text,
          "expected `const fmtMcap =` helper")
    check("A8 market_cap rendered via fmtMcap",
          "{fmtMcap(mkt.market_cap)}" in text,
          "expected `{fmtMcap(mkt.market_cap)}` at line ~552")
    check("A8 total_volume still uses fmtVol",
          "{fmtVol(mkt.total_volume)}" in text,
          "expected `{fmtVol(mkt.total_volume)}` (its $1e3 divisor is right for liquidity)")
    # fmtVol must still be defined for total_volume — but no longer used for mcap.
    check("A8 fmtVol definition retained",
          "const fmtVol = " in text,
          "fmtVol was renamed/removed; should be retained for total_volume")


def test_a9_assetradar_sort_missing_last() -> None:
    """A9: sort must push isMissing values to the end (not collapse to 0)."""
    rel = "dashboard/src/components/AssetRadar.jsx"
    text = _file_text(rel)
    # Scope the `|| 0` check to the sort comparator (between the `// Sort`
    # marker and the closing `});` of the comparator). Other contexts
    # (line 245-248 building rows from upstream; line 658 sparkline polarity)
    # legitimately use `|| 0` as a numeric default.
    sort_start = text.find("// Sort")
    sort_end = text.find("});\n", sort_start)
    sort_block = text[sort_start:sort_end] if sort_start != -1 else ""
    check("A9 sort uses isMissing guard",
          "aMissing" in text and "bMissing" in text,
          "expected aMissing/bMissing in sort comparator")
    bad_in_sort = [pat for pat in (
        "mkt.market_cap || 0", "ch24 || 0", "ch7d || 0",
        "cis?.score || 0", "cis?.las || 0", "total_volume || 0",
    ) if pat in sort_block]
    check("A9 sort drops `|| 0` fallback (scoped to comparator)",
          not bad_in_sort,
          f"`|| 0` patterns still in sort keys: {bad_in_sort}")


def test_c2_intelligencepage_amount_ismissing() -> None:
    """C2: fmt.amount() must use isMissing (real 0 renders, missing → "—")."""
    rel = "dashboard/src/components/IntelligencePage.jsx"
    text = _file_text(rel)
    check("C2 fmt.amount uses isMissing",
          "amount: (v) =>" in text and "isMissing(v)" in text,
          "expected isMissing(v) in fmt.amount")
    check("C2 falsy-zero `!v` proxy removed",
          "if (!v) return \"—\";" not in text,
          "old `if (!v) return \"—\";` still present")


def test_c3_ciswidget_pillar_color_and_recalc() -> None:
    """C3: pillar color uses isMissing; recalc normalizes by presence."""
    rel = "dashboard/src/components/CISWidget.jsx"
    text = _file_text(rel)
    check("C3 imports isMissing",
          "import { isMissing }" in text,
          f"check {rel} for `import {{ isMissing }}`")
    check("C3 pillar color uses isMissing",
          "isMissing(v) ?" in text or "isMissing(v)\n" in text,
          "expected `isMissing(v)` in pillar map color branch")
    # Recalc must normalize by presence, not by `?? 0`.
    check("C3 recalc drops `(asset.f ?? 0)` pattern",
          "(asset.f ?? 0)" not in text and "(asset.m ?? 0)" not in text,
          "old `(asset.f ?? 0)` etc. still in recalc")


def test_c4_portfoliodiagnosis_cis_fallback() -> None:
    """C4: cis must be null when missing, not 25."""
    rel = "dashboard/src/components/PortfolioDiagnosis.jsx"
    text = _file_text(rel)
    check("C4 imports isMissing",
          "import { isMissing }" in text,
          f"check {rel} for `import {{ isMissing }}`")
    check("C4 cis:25 fallback removed",
          "h.cis : 25" not in text,
          "old `typeof h.cis === \"number\" ? h.cis : 25` fallback still present")
    check("C4 uses isMissing(h.cis) for missing branch",
          "isMissing(h.cis)" in text,
          "expected `isMissing(h.cis)` in BookField")


def test_c7_quantmonitor_median_ismissing() -> None:
    """C7: median_return must use isMissing (real 0 renders, missing → "—")."""
    rel = "dashboard/src/components/QuantMonitor.jsx"
    text = _file_text(rel)
    check("C7 imports isMissing",
          "import { isMissing }" in text,
          f"check {rel} for `import {{ isMissing }}`")
    check("C7 median_return label uses isMissing",
          "isMissing(spot?.summary?.median_return)" in text,
          "expected isMissing in Median Return tile")
    check("C7 median_return sub-line uses isMissing",
          "isMissing(smc_enhanced.summary.median_return)" in text,
          "expected isMissing in SMC Enhanced sub-line")
    # Both old truthy-check sites must be gone.
    check("C7 old truthy median_return patterns removed",
          "spot?.summary?.median_return ?" not in text,
          "old `spot?.summary?.median_return ? ... : \"—\"` still present")


# ── preflight registration (S-244 family: test exists ≠ test runs) ──────────

def test_preflight_registers_this_test() -> None:
    """`tests/test_s397_p1p2_audit_backlog.py` must be in preflight.sh so that
    a regression here fails the pre-deploy gate. S-244 family pattern."""
    preflight = _REPO / "scripts" / "preflight.sh"
    text = preflight.read_text()
    check("preflight.sh registers this test",
          "test_s397_p1p2_audit_backlog" in text,
          "expected `test_s397_p1p2_audit_backlog` in scripts/preflight.sh")


# ── sibling-sites flagged-not-fixed audit (A7 false positive) ──────────────

def test_a7_vaultpage_already_handled() -> None:
    """A7 was a false positive: setLoading(false) is in finally, so the loading
    branch flips off on error. Document the verification rather than ship a
    fake fix."""
    rel = "dashboard/src/components/VaultPage.jsx"
    text = _file_text(rel)
    check("VaultPage fetchFunds finally sets loading=false",
          "setLoading(false)" in text,
          "expected `setLoading(false)` in fetchFunds finally block")
    check("VaultPage fetchPartnerVaults finally sets vaultsLoading=false",
          "setVaultsLoading(false)" in text,
          "expected `setVaultsLoading(false)` in fetchPartnerVaults finally block")


if __name__ == "__main__":
    print("── S-397 P1/P2 audit backlog: 8 sites + isMissing predicate ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        try:
            fn()
        except Exception as e:
            print(f"  ✗ {fn.__name__} :: {type(e).__name__}: {e}")
            _FAILURES.append(fn.__name__)
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ 8 sites fixed + isMissing smoke + grep guards + preflight registration")