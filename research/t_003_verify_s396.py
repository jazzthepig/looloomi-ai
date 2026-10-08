"""T-003: replay n_rows vs SQL count(*) reconciliation (binance_hist, 2023-10-19 → 2026-07-18).

S-396 reader pagination fix (commit 5709e79) bypassed PostgREST max-rows=1000
via Range-Unit + Range headers. Card asks to verify that replay n_rows now equals
SQL count(*) for the same window — i.e. the cap is gone.

Round 2 (2026-10-08, C cross-review #1): the previous version of this script
mirrored the pagination loop by hand instead of calling
`paper_trading.replay_three_arms.fetch_panel_rows`. That only proved "these
headers work" — it did not exercise the function the replay actually uses.
This version calls fetch_panel_rows directly so a bug inside that function
(regression, wrong universe, wrong default page_size, etc.) shows up in the
verdict.

Outputs:
- console: counts + verdict (PASS / FAIL)
- /Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/t_003_s396_verify_2026-10-07.md  (Mac data root, per Rule 3a; same path as round 1 — overwrite)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Make `paper_trading` importable when running from research/
_WORKTREE = Path(__file__).resolve().parent.parent
if str(_WORKTREE) not in sys.path:
    sys.path.insert(0, str(_WORKTREE))

from paper_trading.replay_three_arms import fetch_panel_rows  # noqa: E402

# Load .env from lane-a worktree (project rule: no hard-coded secrets)
for _p in (
    Path(__file__).resolve().parent.parent / ".env",
    Path("/Users/sbb/Projects/looloomi-ai/.env"),
    Path("/Users/sbb/Projects/looloomi-ai-lane-a/.env"),
):
    if _p.exists():
        for _line in _p.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())
        break

import httpx

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
SOURCE = "binance_hist"
START = "2023-10-19"
END = "2026-07-18"


def sql_count() -> tuple[int, str]:
    """Exact count via Prefer: count=exact on a 1-row projection, universe-filtered."""
    spec_path = _WORKTREE / "paper_trading" / "specs" / "a17_panel_long_only.json"
    universe = json.loads(spec_path.read_text(encoding="utf-8"))["universe"]
    syms = ",".join(f'"{s}"' for s in universe)
    endpoint = (
        f"{URL}/rest/v1/ohlcv_daily"
        f"?select=symbol&source=eq.{SOURCE}"
        f"&symbol=in.({syms})"
        f"&trade_date=gte.{START}&trade_date=lte.{END}"
        f"&limit=1"
    )
    r = httpx.get(
        endpoint,
        headers={
            "apikey": KEY,
            "Authorization": f"Bearer {KEY}",
            "Prefer": "count=exact",
        },
        timeout=30,
    )
    if r.status_code not in (200, 206):
        return -1, f"HTTP {r.status_code}: {r.text[:200]}"
    cr = r.headers.get("content-range", "")
    if "/" in cr:
        total = cr.split("/")[-1].strip()
        try:
            return int(total), cr
        except ValueError:
            return -1, f"unparseable Content-Range: {cr!r}"
    return -1, f"no Content-Range header: {r.headers!r}"


def replay_n_rows() -> tuple[int, str, int]:
    """Call the function the replay actually uses: fetch_panel_rows.
    No mirrored loop — a regression inside fetch_panel_rows (wrong default
    page_size, broken Range-Unit header, etc.) would otherwise pass this test
    silently. Card acceptance calls for the replay-side count, which is exactly
    what fetch_panel_rows returns.
    """
    spec_path = _WORKTREE / "paper_trading" / "specs" / "a17_panel_long_only.json"
    universe = json.loads(spec_path.read_text(encoding="utf-8"))["universe"]

    rows, err = asyncio.run(
        fetch_panel_rows(universe, SOURCE, START, END)
    )
    if err:
        return -1, err, 0
    return len(rows), "ok", 0


def main() -> int:
    t0 = time.time()
    print(f"[t_003] source={SOURCE} window=[{START},{END}]")
    print("[t_003] step 1: SQL count(*) via Prefer: count=exact …")
    sql_n, sql_meta = sql_count()
    print(f"[t_003]   sql_count = {sql_n}  ({sql_meta})")
    if sql_n < 0:
        print("[t_003] ABORT sql_count failed")
        return 2

    print("[t_003] step 2: replay fetch via paper_trading.replay_three_arms.fetch_panel_rows …")
    replay_n, replay_meta, pages = replay_n_rows()
    print(f"[t_003]   replay_n_rows = {replay_n}  ({replay_meta})")
    if replay_n < 0:
        print("[t_003] ABORT replay failed")
        return 2

    verdict = "PASS" if replay_n == sql_n else "FAIL"
    elapsed = time.time() - t0
    print(f"[t_003] verdict: {verdict}  (elapsed {elapsed:.1f}s)")

    # Write report to Mac data root (overwrite round-1 file with round-2 result)
    out_path = Path("/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/t_003_s396_verify_2026-10-07.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        f"""# T-003 / S-396 — replay n_rows vs SQL count(*)

**Date (UTC):** 2026-10-08 (round 2 — round 1 was 2026-10-07)
**Source:** ohlcv_daily where source = `{SOURCE}`
**Window:** {START} → {END}
**Universe:** A-17 spec (BTC / ETH / SOL / BNB / XRP) — universe-filtered on both sides.
**Replay caller:** `paper_trading.replay_three_arms.fetch_panel_rows`
(round 1 mirrored the loop by hand; round 2 calls the function the replay
actually uses — see Notes).

## Result

| Method | n_rows |
| --- | --- |
| SQL count(*) via Prefer: count=exact (universe=A-17) | {sql_n} |
| Replay fetch_panel_rows (universe=A-17, paginated) | {replay_n} |
| Replay meta | status={replay_meta} |
| SQL Content-Range | {sql_meta} |

**Verdict:** **{verdict}** — {'equal' if verdict == 'PASS' else 'NOT equal'} ({elapsed:.1f}s).

## Interpretation

- Pre-fix (S-396): replay read 1,000 rows (PostgREST max-rows=1000 cap) while
  SQL count(*) returned the full universe total. Truncation silent.
- Post-fix (5709e79, Range-Unit + Range): fetch_panel_rows walks all pages
  until `len(rows) < page_size`. {'Replay n_rows == SQL count → S-396 fix is live, cap is gone.' if verdict == 'PASS' else 'Replay n_rows ≠ SQL count → either the fix is incomplete, the window drifted, or another cap fired.'}

## Notes for Seth (verifier)

- Round 2 fix: `replay_n_rows()` previously re-implemented the pagination loop
  (different code path than the replay). Round 2 imports `fetch_panel_rows`
  from `paper_trading.replay_three_arms` and calls it with the same universe /
  source / window as the replay. Now `replay_n_rows` IS the replay count.
- Card `prior_value`: "replay 读到 1,000 行(截断)". Now confirmed
  {'restored' if verdict == 'PASS' else 'NOT restored'}.
- Card `expect`: "相等" — {'met' if verdict == 'PASS' else 'NOT met'}.
""",
        encoding="utf-8",
    )
    print(f"[t_003] wrote → {out_path}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())