"""
Guard: we do not claim the moat concept we have not measured (S-141).

ARCHITECTURE.md line 164, verbatim:

    "A signal we have not run through our own loop is one we must not claim.
     Claiming it unproven is self-deception, and self-deception cannot teach."

WHAT WAS MEASURED IN PRODUCTION, 2026-08-12. `/api/v1/cis/universe` returned, for
58 of 58 assets:

    out_of_circle_risk: "low"   ·   stage: null   ·   source: "market_proxy"
    drivers: ["consensus still upstream / in-circle —
              no out-of-circle stress detected"]

Three separate problems, in increasing order of seriousness:

1. `stage` — the position on the diffusion curve, which IS the 出圈 concept — was
   null everywhere. Fine on its own; the code deliberately refuses to fabricate it.

2. The BAND was still emitted in the same vocabulary used when real holder or
   attention data is present. A risk indicator that has never fired is
   indistinguishable from one that is switched off. That is S-131's `cap_source`
   (a column that existed, was displayed, and only ever carried one value) —
   sitting on the concept ARCHITECTURE.md calls the moat.

3. The driver text asserted a NEGATIVE FINDING from an absent test. "No
   out-of-circle stress detected" is not "we don't know" — it says we looked and
   it is clear. Nothing looked. 出圈 needs a diffusion input (holder stage D3 or
   attention diffusion D4); cap rank, price extension and the S pillar are
   REFLECTIONS of diffusion, which is precisely what the concept exists to get
   upstream of.

Why this one matters more than the plumbing bugs it resembles: it is on the thing
we sell. ARCHITECTURE.md's own prioritisation filter says the wall is the
"hard-to-compute, hard-to-verify upstream judgment", and then adds that
hard-to-verify cuts both ways — the consumer cannot check us, so the provenance we
hand over IS the product. Provenance that says "measured" when it means "guessed"
is the one defect that destroys the whole proposition rather than one endpoint.

Run: python3 -m tests.test_moat_claims_are_measured
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from src.data.cis.cause_proximity import estimate_inline  # noqa: E402

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


_ASSET = {"symbol": "PROBE", "market_cap_rank": 150,
          "pillars": {"S": 55}, "change_30d": 12}


def test_a_proxy_estimate_is_not_banded_as_a_measurement() -> None:
    """The core fix. With no diffusion input the band must say so rather than
    borrow the vocabulary of a real reading."""
    out = estimate_inline(_ASSET)
    check("source is honest about being a proxy",
          out["source"] == "market_proxy", str(out.get("source")))
    check("band is 'unmeasured', not 'low'",
          out["out_of_circle_risk"] == "unmeasured",
          f"got {out['out_of_circle_risk']!r} — a never-firing indicator and a "
          f"switched-off indicator must not render identically")
    check("the block states measurement status explicitly",
          out.get("diffusion_measured") is False,
          "consumers need a field to branch on, not a string to parse")


def test_no_negative_finding_is_asserted_from_an_absent_test() -> None:
    """"Not detected" and "not measured" differ by exactly the thing a consumer is
    paying us for."""
    drivers = " ".join(estimate_inline(_ASSET)["drivers"]).lower()
    check("does not claim stress was 'not detected'",
          "no out-of-circle stress detected" not in drivers,
          "this asserts a clean result from a test that never ran")
    check("names what is missing instead",
          "not measured" in drivers or "NOT MEASURED".lower() in drivers, drivers[:120])
    check("names the inputs that would have measured it",
          ("d3" in drivers and "d4" in drivers),
          "a reader must be able to tell WHAT would change the answer")


def test_a_real_diffusion_input_restores_the_real_band() -> None:
    """The fix must not disable the feature — it must gate it. If observing
    diffusion no longer produces a band, we have traded a false claim for no
    capability, which is a different way of having nothing."""
    with_att = estimate_inline(_ASSET, attention={"attention_score": 0.2, "sentiment_up": 52})
    check("attention diffusion (D4) yields a real band",
          with_att["out_of_circle_risk"] in ("low", "elevated", "high"),
          str(with_att["out_of_circle_risk"]))
    check("and marks itself measured", with_att.get("diffusion_measured") is True, "")

    with_holder = estimate_inline(_ASSET, holder={"stage": 0.85, "chuquan": True,
                                                  "season": "stale"})
    check("holder stage (D3) yields a real band and a real stage",
          with_holder["out_of_circle_risk"] in ("low", "elevated", "high")
          and with_holder["stage"] is not None,
          str(with_holder))
    check("the elevated case is actually reachable",
          with_holder["out_of_circle_risk"] in ("elevated", "high"),
          "a stale season at stage 0.85 must not read low — otherwise the band is "
          "decorative in the other direction")


def test_stage_is_never_fabricated() -> None:
    """This part was already right and must stay right: the code refuses to invent
    a diffusion position when no holder data exists."""
    check("stage stays null without holder data",
          estimate_inline(_ASSET)["stage"] is None, "")
    src = (_ROOT / "src/data/cis/cause_proximity.py").read_text(encoding="utf-8")
    check("the refusal is documented at the site",
          "don't fabricate it" in src or "do not fabricate" in src.lower(), "")


def test_the_architecture_line_is_quoted_where_the_fix_lives() -> None:
    """The rule that was broken should be readable next to the code that enforces
    it — a doctrine cited only in a 200-line north-star document is one the next
    author will not have read that morning."""
    src = (_ROOT / "src/data/cis/cause_proximity.py").read_text(encoding="utf-8")
    check("cause_proximity.py cites the claim rule",
          "must not claim" in src and "self-deception" in src, "")


if __name__ == "__main__":
    print("── moat claims are measured, not asserted (S-141) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ 出圈 is claimed only where it is observed")
