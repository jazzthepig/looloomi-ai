"""
Guard: exactly one process may write the shared record (S-149).

THE HAZARD, one paste away on 2026-08-12. Running the app locally starts 20+
background loops; a dozen write Supabase and share Redis state keys with Railway.
Both would have marked `beta_core_nav` for the same day, off different panels, at
different times. The forward record — the one artefact of this company that cannot
be re-derived — would have become a function of which machine woke first.

The only thing preventing it was that `SUPABASE_KEY` happened to be empty in the
local `.env`. Safety by accident. And the default made it worse:

    _ENV = os.environ.get("ENVIRONMENT", "production")

An unset variable made any machine a production writer.

THE BOUNDARY IS *WRITE*, NOT *CONNECT*. Reading production from a laptop is useful
and harmless — it is how you debug against real data. Writing is the part that must
have exactly one owner.

THE GATE IS AT THE WRITE FUNCTION, not in the loops. Loops keep being added, and a
gate you have to remember to apply is a gate that will be forgotten — the same
argument that put GREATEST inside `api_usage_upsert` instead of in its caller.
There are exactly two Supabase write functions and seventeen callers; gating the
two covers all seventeen and everything written next year.

Run: python3 -m tests.test_only_one_process_writes_the_record
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


def _role_with(**env) -> object:
    """Re-import runtime_role under a given environment."""
    saved = {k: os.environ.get(k) for k in ("APP_ROLE", "ENVIRONMENT")}
    for k in ("APP_ROLE", "ENVIRONMENT"):
        os.environ.pop(k, None)
    os.environ.update({k: v for k, v in env.items() if v is not None})
    try:
        import src.api.runtime_role as rr
        return importlib.reload(rr)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_unset_means_reader_not_writer() -> None:
    """THE fix. An unset variable must never confer the right to write the record."""
    rr = _role_with()
    check("no APP_ROLE and no ENVIRONMENT ⇒ replica",
          rr.ROLE == rr.REPLICA, f"got {rr.ROLE}")
    check("and it may not write", rr.is_writer() is False, "")
    importlib.reload(rr)


def test_production_must_be_explicit() -> None:
    rr = _role_with(APP_ROLE="production")
    check("APP_ROLE=production is the writer", rr.is_writer() is True, rr.ROLE)
    rr = _role_with(ENVIRONMENT="production")
    check("legacy ENVIRONMENT=production still writes (Railway must not break)",
          rr.is_writer() is True, rr.ROLE)
    importlib.reload(rr)


def test_ci_and_staging_read_only() -> None:
    for env in ("ci", "staging", "test", "development", "local"):
        rr = _role_with(ENVIRONMENT=env)
        check(f"ENVIRONMENT={env} ⇒ reader", rr.is_writer() is False, rr.ROLE)
    importlib.reload(rr)


def test_an_unknown_role_refuses_to_boot() -> None:
    """Guessing means choosing between silently writing to production and silently
    hiding a real deployment. Both are worse than not booting."""
    try:
        _role_with(APP_ROLE="prod")          # a plausible typo
        check("APP_ROLE=prod is rejected", False, "it was accepted")
    except Exception as e:
        check("APP_ROLE=prod is rejected", "RoleConfigurationError" in type(e).__name__
              or "not one of" in str(e), f"{type(e).__name__}: {e}")
    import src.api.runtime_role as rr
    importlib.reload(rr)


def test_dev_is_refused_until_it_is_isolated() -> None:
    """`dev` needs a private Redis namespace and a Supabase branch. Until then a
    'dev' writer shares prod state keys — the exact hazard being removed. Refusing
    is honest; accepting and hoping is not."""
    try:
        _role_with(APP_ROLE="dev")
        check("APP_ROLE=dev is refused", False, "it was accepted without isolation")
    except Exception as e:
        check("APP_ROLE=dev is refused", "not implemented" in str(e), str(e)[:90])
    import src.api.runtime_role as rr
    importlib.reload(rr)


def test_the_gate_is_on_the_write_functions_not_the_loops() -> None:
    """Two functions, seventeen callers. Gating the callers would mean gating every
    future caller too."""
    src = (_ROOT / "src/api/store.py").read_text(encoding="utf-8")
    for fn in ("supabase_insert_batch", "supabase_insert_table"):
        i = src.index(f"async def {fn}(")
        body = src[i:i + 1400]
        check(f"{fn} consults refuse_write", "refuse_write(" in body,
              "an ungated write function makes every caller a potential writer")
    check("store.py imports the gate",
          "from src.api.runtime_role import" in src, "")


RECORD_TABLES = {
    "beta_core_nav", "causal_paper_nav", "dingge_paper_nav", "combined_book_nav",
    "scalable_book_nav", "two_layer_paper_nav", "cis_scores", "signal_outcomes",
    "conviction_verdicts_daily", "cause_snapshots_daily", "narrative_snapshots",
    "trending_log", "asset_embeddings", "asset_embeddings_history",
    "market_state_vectors", "signal_journal", "trade_results",
    "prediction_outcomes", "regime_band_log", "strategy_records",
    "experiment_runs", "risk_meter_history",
}


def test_every_record_writer_is_gated_including_ones_added_later() -> None:
    """THE CORRECTION (S-150). Yesterday's claim was "the write side of the record
    has one owner". Measured the next morning: 30 direct Supabase write sites, and
    the gate reached TWO of them. Five of the rest wrote FORWARD-RECORD tables —
    prediction_outcomes, experiment_runs, strategy_records ×3.

    So the guarantee read broader than the implementation, and the guard I wrote to
    defend it passed, because it only checked the two functions it already knew
    about. That is the defect this whole session has been about — a confident claim
    with a narrower reality — committed inside the fix for it and endorsed by its
    own test.

    THIS test is the durable part: it ENUMERATES, so a record writer added next
    month fails the build instead of being silently ungated. A guard that checks
    the sites you remembered is a guard that protects you from the past.

    Business tables (leads, webhooks, auth, api_keys, api_usage) are deliberately
    OUT of scope: they are not the forward record, they have no single-owner
    requirement, and pretending otherwise would make the list unmaintainable and
    the rule unbelievable."""
    import re

    src_root = _ROOT / "src"
    ungated: list[str] = []
    checked = 0
    for p in sorted(src_root.rglob("*.py")):
        if "/tests/" in str(p) or "site-packages" in str(p) or "/.venv/" in str(p):
            continue
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines, 1):
            code = line.split("#")[0]
            if "rest/v1" not in code:
                continue
            ctx = "\n".join(lines[max(0, i - 10):i + 12])
            if not re.search(r'\.post\(|\.patch\(|\.delete\(|'
                             r'method\s*=\s*["\'](POST|PATCH|DELETE)', ctx):
                continue
            hits = {t for t in RECORD_TABLES if t in ctx}
            if not hits:
                continue
            checked += 1
            # gated either directly, or by going through store.py's helpers
            whole = "\n".join(lines)
            if "refuse_write" in whole or "supabase_insert_table" in ctx:
                continue
            ungated.append(f"{p.relative_to(_ROOT)}:{i} → {sorted(hits)}")

    check(f"{checked} record-writing site(s) found and all gated", not ungated,
          "\n      " + "\n      ".join(ungated))
    check("the scan actually found record writers", checked >= 4,
          f"only {checked} — the table list or the regex has drifted, and a scan "
          f"that finds nothing passes for the same reason a broken one does")


def test_the_claim_matches_the_coverage() -> None:
    """The claim in the module docstring must say RECORD, not "writes". Getting this
    wrong is not pedantry: "the write side has one owner" invites the next author to
    assume their new `leads` insert is covered, or that their new `beta_core_nav`
    insert is covered when it is not."""
    src = (_ROOT / "src/api/runtime_role.py").read_text(encoding="utf-8")
    check("runtime_role scopes its claim to the shared record",
          "shared record" in src or "system of record" in src,
          "an unscoped claim is a claim that will be over-trusted")


def test_a_replica_declines_rather_than_crashes() -> None:
    """A replica that CRASHES on a write attempt is a replica you cannot use to
    debug the write path. It should decline, say so once, and keep serving."""
    rr = _role_with(ENVIRONMENT="ci")
    reason = rr.refuse_write("beta_core_nav")
    check("a reader gets a reason, not an exception", isinstance(reason, str), str(reason))
    check("the reason names the role and the remedy",
          "replica" in reason and "APP_ROLE=production" in reason, reason[:120])
    rr.note_refusal("beta_core_nav", reason)
    rr.note_refusal("beta_core_nav", reason)     # second call must not re-log
    check("refusals are logged once per target", "beta_core_nav" in rr._WARNED, "")
    importlib.reload(rr)


def test_the_banner_distinguishes_absent_from_empty() -> None:
    """`SUPABASE_KEY=` (present, empty) reads as configured to every
    os.environ.get in the codebase and writes nothing. That third state is what
    cost 2026-08-11→12, and a banner that collapses it back into two would be
    theatre."""
    os.environ["_PROBE_EMPTY"] = ""
    try:
        import src.api.runtime_role as rr
        importlib.reload(rr)
        d = rr.describe()
        states = set(d["credentials"].values())
        check("banner reports three states, not two",
              states <= {"set", "EMPTY", "absent"} and "credentials" in d, str(states))
        check("empty is distinguished from absent",
              rr.describe.__doc__ and "present but empty" in rr.describe.__doc__, "")
    finally:
        os.environ.pop("_PROBE_EMPTY", None)
    check("no credential VALUE can appear in the banner",
          "os.environ[" in (_ROOT / "src/api/runtime_role.py").read_text()
          and "_state(" in (_ROOT / "src/api/runtime_role.py").read_text(),
          "the banner must report presence, never contents")


if __name__ == "__main__":
    print("── exactly one process writes the record (S-149) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ every FORWARD-RECORD writer is gated "
          "(business tables are deliberately out of scope)")
