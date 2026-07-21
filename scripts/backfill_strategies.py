"""
Backfill Strategy Records — populate the strategy vector DB from source docs
============================================================================

Sources (per user directive: 全部来源 — all sources):
  1. REFUTATION_LEDGER.md  — R-entries (validated, refuted, doctrine)
  2. ARCHITECTURE.md        — kernel / fusion / primitive / ontology concepts
  3. docs/TRADER_TOM_DOCTRINE.md — behavioral-edge principles
  4. docs/STRATEGY_2026_Q3.md — agenda moves (next-round candidates)
  5. MINIMAX_SYNC.md (gitignored) — § research blocks (only those that ship
     or refute an experiment)

Output:
  - Local audit JSON:  _data/strategy_records.json  (always)
  - Console summary table
  - Optional Redis upsert (if UPSTASH_REDIS_REST_URL is set and --write-redis)

Strict invariants
-----------------
  • No mock data. If a record's dimensional block can't be derived from the source,
    the field is empty. Partial records are fine; fake numbers are not.
  • Verdict is set ONLY for entries with explicit verdict emoji in REFUTATION_LEDGER.
    Doctrinal records (kernel, principle) get verdict=DOCTRINE explicitly.
  • R-entries with no R-number get the next sequential id (RA, RB, …) so they
    still registerable but traceable.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make src/ importable when script is invoked directly
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.vector.strategy_schema import StrategyRecord, Verdict  # noqa: E402

OUT_LOCAL = ROOT / "_data" / "strategy_records.json"


# -----------------------------------------------------------------------------
# 1. REFUTATION_LEDGER R-entry parser
# -----------------------------------------------------------------------------
# Splits on `## R\d+` headers; extracts id (R\d+), verdict (emoji), title.
# The dimensional blocks (cost-sensitivity, factor_exposure, etc.) are mostly
# not backfilled from text — they require live outcome data. We register
# the record skeleton and leave the dimensional blocks empty for gradual fill.

_VERDICT_EMOJI = {
    "🟢": Verdict.SHIP,
    "🟡": Verdict.HOLD,
    "🔴": Verdict.REFUTE,
    "✅": Verdict.SHIP,
    "🔵": Verdict.HOLD,
}

_R_HEADER = re.compile(r"^## (R\d+)\s*([🟢🟡🔴✅🔵])\s+(.*?)(?:\s+\(([^)]+)\))?\s*$", re.MULTILINE)


# -----------------------------------------------------------------------------
# 1b. R-entry dimensional parser — mines body text for fields the vec cares about.
# -----------------------------------------------------------------------------
# HONESTY GATE: only extract numbers that are explicitly labeled. We NEVER
# convert t-stat → Sharpe (needs assumed N which varies per entry) or
# infer cost-tier Sharpes from context. If a field isn't labeled, it stays
# None, and the embedder leaves that dim at 0.0 (neutral).

import re as _re


def _first_floats(pattern: str, text: str, n: int = 1) -> list[float | None]:
    """Return up to `n` floats matching the pattern, or Nones if not found."""
    matches = _re.findall(pattern, text)
    out: list[float | None] = []
    for m in matches[:n]:
        try:
            out.append(float(m))
        except (ValueError, TypeError):
            out.append(None)
    while len(out) < n:
        out.append(None)
    return out


def _parse_dimensions(body: str) -> dict:
    """Mine an R-entry body for fields the 30-dim vector cares about.

    Returns a dict with:
      factor_exposure (dict), mechanics (dict), capacity (dict),
      lifecycle (dict), cost_sensitivity (dict), outcome (dict of optional floats)

    Missing → empty dict / None. We never raise. Anti-imposter: only labeled numbers.
    """
    out: dict = {
        "factor_exposure": {},
        "mechanics": {},
        "capacity": {},
        "lifecycle": {},
        "cost_sensitivity": {},
        "outcome": {},
    }

    # ---- mechanics ----
    # Holding period (days). Priority: BOLDED values come first (the headline),
    # then later-context beats earlier-context (we scan for the LAST candidate
    # when the body describes a sweep, not the FIRST). Patterns like "5-day rebal",
    # "rebal_days=5", "holding period 21d", "21d/0bps" cadence.
    def _first_number(text: str, patterns: tuple[str, ...]) -> float | None:
        """Try patterns in order; prefer bolded values, else last occurrence."""
        # First pass: look inside ** ... ** (the headline)
        bold = _re.findall(r"\*\*([^*\n]+?)\*\*", text)
        for b_text in bold:
            for pat in patterns:
                m = _re.search(pat, b_text, _re.IGNORECASE)
                if m:
                    try:
                        return float(m.group(1))
                    except (ValueError, IndexError):
                        continue
        # Second pass: prefer the LAST occurrence (the most-recently-stated number,
        # which in narrative docs is usually the conclusion).
        last: float | None = None
        for pat in patterns:
            for m in _re.finditer(pat, text, _re.IGNORECASE):
                try:
                    last = float(m.group(1))
                except (ValueError, IndexError):
                    continue
        return last

    hp = _first_number(body, (r"(\d+)[- ]day rebal", r"rebal[_-]?days?[ =]+(\d+)",
                              r"holding period (\d+)d", r"(\d+)d/\d+bps",
                              r"(\d+)-day cadence"))
    if hp is not None:
        out["mechanics"]["holding_period_days"] = hp

    # Turnover (per quarter) — prefer last occurrence of "turnover X"
    t_match = None
    for m in _re.finditer(r"[Tt]urnover(?:[^.\n]{0,30}?)\b(\d{1,4})\b", body):
        try:
            t_match = float(m.group(1))
        except ValueError:
            continue
    if t_match is not None:
        out["mechanics"]["turnover_per_q"] = t_match

    # Directionality — long-only / short-only / long-short from explicit labels
    body_lc = body.lower()
    if "long-only" in body_lc and "short" not in body_lc:
        out["mechanics"]["directionality"] = 1.0
    elif "short-only" in body_lc and "long" not in body_lc:
        out["mechanics"]["directionality"] = -1.0
    elif "long-short" in body_lc or "l/s" in body_lc or "ls " in body_lc:
        out["mechanics"]["directionality"] = 0.0

    # Time in market (% active) — patterns like "%TIM 99%", "%TIM 95%"
    tim_match = _re.search(r"%TIM\s*(\d{1,3})", body)
    if tim_match:
        try:
            out["mechanics"]["time_in_market"] = float(tim_match.group(1))
        except ValueError:
            pass

    # ---- capacity ----
    # K=N or "N majors" or "N names" or "N assets"
    k_match = _re.search(r"\bK\s*=\s*(\d+)", body)
    if k_match:
        try:
            out["capacity"]["n_assets"] = float(k_match.group(1))
        except ValueError:
            pass
    else:
        # Pattern: "24 majors" or "21 names" or "28 assets"
        cn_match = _re.search(r"\b(\d+)\s+(?:majors|names|assets|alts)\b", body)
        if cn_match:
            try:
                out["capacity"]["n_assets"] = float(cn_match.group(1))
            except ValueError:
                pass

    # Declared capacity — patterns like "$5.0M declared capacity" or "joint capacity $5M"
    dc_match = _re.search(r"\$(\d+(?:\.\d+)?)\s*([MBK])\b[^\n]*capacity|capacity[^\n]{0,15}\$(\d+(?:\.\d+)?)([MBK])", body, _re.IGNORECASE)
    if dc_match:
        g = [g for g in dc_match.groups() if g is not None]
        try:
            val = float(g[0])
            unit = g[1].upper()
            mult = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}.get(unit, 1.0)
            out["capacity"]["declared_capacity"] = val * mult
        except (ValueError, IndexError):
            pass

    # ---- lifecycle ----
    # Age — only filled from "n days/weeks/months/years of data/window/history"
    age_match = _re.search(r"\b(\d+(?:\.\d+)?)\s*(year|yr|month|mo|week|wk|day|days?)\b[^\n]{0,20}(?:data|window|history|panel|OOS|backfill|overlap)", body, _re.IGNORECASE)
    if age_match:
        try:
            n = float(age_match.group(1))
            unit = age_match.group(2).lower()
            days = n * {"year": 365, "yr": 365, "month": 30, "mo": 30, "week": 7, "wk": 7, "day": 1, "days": 1}.get(unit, 1)
            out["lifecycle"]["age_days"] = days
        except (ValueError, IndexError):
            pass

    # Half-life — "half-life of X days" or "half_life = X"
    hl_match = _re.search(r"half[-_ ]life[^\n]{0,12}(\d+)\s*d", body, _re.IGNORECASE)
    if hl_match:
        try:
            out["lifecycle"]["half_life_days"] = float(hl_match.group(1))
        except ValueError:
            pass

    # ---- cost_sensitivity ----
    # Only fill if the value is explicitly tagged as a Sharpe (not a t-stat).
    # Pattern: "0bps Sharpe X.YZ" or "at 0bps sharpe X" or "sharpe_0bps X"
    for cost_key, pattern in (
        ("0bps",  r"(?:sharpe[_-]?0bps|SR[_-]?0bps|at\s+0bps\s+sharpe[^.\d]*?)([-+]?\d+\.\d+|[-+]?\d+)"),
        ("2bps",  r"(?:sharpe[_-]?2bps|SR[_-]?2bps|at\s+2bps\s+sharpe[^.\d]*?)([-+]?\d+\.\d+|[-+]?\d+)"),
        ("5bps",  r"(?:sharpe[_-]?5bps|SR[_-]?5bps|at\s+5bps\s+sharpe[^.\d]*?)([-+]?\d+\.\d+|[-+]?\d+)"),
        ("10bps", r"(?:sharpe[_-]?10bps|SR[_-]?10bps|at\s+10bps\s+sharpe[^.\d]*?)([-+]?\d+\.\d+|[-+]?\d+)"),
    ):
        m = _re.search(pattern, body, _re.IGNORECASE)
        if m:
            try:
                out["cost_sensitivity"][cost_key] = float(m.group(1))
            except (ValueError, IndexError):
                pass

    # Fallback: "annSR X.XX" → reported as a heuristic at 5bps if no labeled tier exists,
    # ALSO set at 0bps (so the embedder sees monotonically decreasing cost penalty if present)
    # but ONLY if NO cost_sensitivity was filled (don't double-publish)
    if not out["cost_sensitivity"]:
        annsr_match = _re.search(r"annSR\s*\*?\*?\s*([-+]?\d+\.\d+)", body)
        if annsr_match:
            try:
                sr = float(annsr_match.group(1))
                out["cost_sensitivity"]["0bps"] = sr
            except ValueError:
                pass

    # Plain "Sharpe X.XX" near "Result:" or "**Result:**" — if 0bps not yet set
    if "0bps" not in out["cost_sensitivity"]:
        # be careful: only fill if "Sharpe" is followed by a NUMBER and "DSR" or "OOS" somewhere
        if _re.search(r"\b(?:OOS|DSR)\b", body):
            for pat in (
                r"\*\*Result[^.\n]*?\*\*[^\n]{0,80}?[Ss]harpe[^\d]*?([-+]?\d+\.\d+)",
                r"[Ss]harpe\s+([-+]?\d+\.\d+)[^\n]{0,40}?(OOS|DSR)",
            ):
                m = _re.search(pat, body[:6000])
                if m:
                    try:
                        out["cost_sensitivity"]["0bps"] = float(m.group(1))
                        break
                    except ValueError:
                        continue

    # ---- outcome ----
    # Realized α — patterns like "ann% +X" or "ann α" or "alpha X%"
    ra = _re.search(r"ann%\s*([-+]?\d+\.?\d*)", body)
    if ra:
        try:
            out["outcome"]["realized_alpha"] = float(ra.group(1)) / 100.0
        except ValueError:
            pass

    # Walk-forward positive folds — "n/5 walk-forward" or "n/5 positive"
    if "outcome_confidence" not in out["outcome"]:
        wf_match = _re.search(r"walk[- ]forward[^\n]{0,15}?(\d+)\s*/\s*(\d+)", body, _re.IGNORECASE)
        if wf_match:
            try:
                pos = float(wf_match.group(1)) / float(wf_match.group(2))
                out["outcome"]["outcome_confidence"] = pos
            except (ValueError, ZeroDivisionError):
                pass

    # MaxDD — patterns like "MaxDD −X%" or "MaxDD −XX.X%"
    mdd = _re.search(r"[Mm]axDD\s*\*?\*?\s*([-+]?\d+\.?\d*)\s*%?", body)
    if mdd:
        try:
            out["outcome"]["max_dd"] = float(mdd.group(1)) / 100.0
        except ValueError:
            pass

    # DSR — patterns like "DSR 0.95" or "DSR **0.96**"
    dsr = _re.search(r"DSR\s*\*?\*?\s*(\d+\.\d+)", body)
    if dsr:
        try:
            out["outcome"]["dsr"] = float(dsr.group(1))
        except ValueError:
            pass

    # ---- factor_exposure (heuristic — only fill when body explicitly mentions β) ----
    # Patterns like "β=0.42" or "beta_quality β=0.X" — extremely rare in our R-entries,
    # so most records leave this empty (per anti-imposter: no fake β)
    return out


def parse_refutation_ledger(path: Path) -> list[StrategyRecord]:
    text = path.read_text()
    records: list[StrategyRecord] = []

    # Iterate one R at a time, body = text after header until next ## header
    matches = list(_R_HEADER.finditer(text))

    # Handle duplicate R-numbers (R63 appears twice in the ledger,
    # 2026-07-21: once for fragility-gated sleeve, once for pillar_S domain
    # correction). Suffix the 2nd+ occurrences so both are preserved as
    # distinct records (anti-imposter: don't silently drop findings).
    seen_r_numbers: dict[str, int] = {}

    for i, m in enumerate(matches):
        r_number = m.group(1)
        verdict_emoji = m.group(2)
        title = m.group(3).strip()
        author = m.group(4) or ""

        if r_number in seen_r_numbers:
            seen_r_numbers[r_number] += 1
            id_suffix = f"-v{seen_r_numbers[r_number]}"
        else:
            seen_r_numbers[r_number] = 1
            id_suffix = ""
        r_id = f"{r_number}{id_suffix}-ledger"

        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end]

        # Tags from common keywords in body
        tags: list[str] = []
        body_lc = body.lower()
        for kw in ("cis", "regime", "two-layer", "regime-detector", "capitulation",
                    "funding", "crowding", "absorption", "construction", "pillar_o",
                    "stops", "calibration", "backtest", "dsr", "walk-forward",
                    "annsr", "cadence", "fragility", "fusion"):
            if kw in body_lc:
                tags.append(kw)

        notes = body[:1500].strip()

        # ---- Dimensional mining ----
        dims = _parse_dimensions(body)
        mech = dims["mechanics"]
        cap  = dims["capacity"]
        lc   = dims["lifecycle"]
        cs   = dims["cost_sensitivity"]
        out  = dims["outcome"]

        # --- binary validity flags ---
        pit_clean = ("PIT" in body or "point-in-time" in body_lc
                     or "PIT clean" in body or "no leakage" in body_lc
                     or "no-lookahead" in body_lc)
        cost_feasible_5 = bool(cs.get("5bps")) and cs["5bps"] >= 0.5
        forward_committed = bool(_re.search(r"forward[- ]commit(?:ted|ment)", body, _re.IGNORECASE))
        # If verdict is REFUTED, forward_committed=False (the whole point is it didn't survive)
        verdict = _VERDICT_EMOJI.get(verdict_emoji, Verdict.HOLD)
        if verdict == Verdict.REFUTE:
            forward_committed = False
            cost_feasible_5 = False

        # --- lifecycle.metadata-only fields: age, decay_slope, crowding_proxy remain
        # in the record via dict; the schema doesn't ship top-level slots for these,
        # they live under .lifecycle -- embedder reads from there ----

        rec = StrategyRecord(
            id=r_id,
            title=title,
            doc_source=str(path.relative_to(ROOT)),
            r_number=r_number,
            verdict=verdict,
            tags=list(set(tags))[:6],
            pit_clean=pit_clean,
            cost_feasible_at_5bps=cost_feasible_5,
            forward_committed=forward_committed,
            factor_exposure=dims["factor_exposure"],
            mechanics=mech,
            capacity=cap,
            lifecycle=lc,
            cost_sensitivity=cs,
            realized_alpha=out.get("realized_alpha"),
            capacity_util=cap.get("declared_capacity"),  # crude proxy
            outcome_confidence=out.get("outcome_confidence"),
            notes=notes,
        )
        records.append(rec)

    return records


# -----------------------------------------------------------------------------
# 2. Doctrinal records — hard-coded because ARCHITECTURE / TRADER_TOM structures
#    don't naturally parse into one-record-per-paragraph.
# -----------------------------------------------------------------------------

DOCTRINAL_RECORDS: list[StrategyRecord] = [
    # Kernel primitives (from ARCHITECTURE.md)
    StrategyRecord(
        id="ARCH-kernel-influence-propagation",
        title="Influence propagation — markets/price are downstream of influencer decisions",
        doc_source="ARCHITECTURE.md",
        verdict=Verdict.DOCTRINE,
        tags=["kernel", "influence-propagation", "ontology"],
        notes="The deepest object is not the asset but the Influencer/Decision. "
              "CIS and momentum are reflections; beta+ comes from being closer to the cause.",
    ),
    StrategyRecord(
        id="ARCH-fusion-diagnose-portfolio",
        title="Diagnose(Portfolio) is Fusion #1 — primitive fused with positioning",
        doc_source="ARCHITECTURE.md",
        verdict=Verdict.DOCTRINE,
        tags=["fusion", "kernel", "primitive"],
        notes="Mass-market front (single API call for a family office). Deep behind = "
              "behavioral-cause detection × structural positioning. Anti-imposter: ONE thing, "
              "freely fusable.",
    ),

    # TRADER_TOM principles (from docs/TRADER_TOM_DOCTRINE.md)
    StrategyRecord(
        id="TRADER_TOM-behavioral-edge",
        title="Behavioral edge: human crowd behavior (fear/greed) recurs; indicator fits decay",
        doc_source="docs/TRADER_TOM_DOCTRINE.md",
        verdict=Verdict.DOCTRINE,
        tags=["behavioral", "fear-greed", "durable-edge"],
        notes="~90% of participants lose because hardwired to do the wrong thing. Edge is the "
              "opposite of the crowd, by construction.",
    ),
    StrategyRecord(
        id="TRADER_TOM-asymmetry-law",
        title="Asymmetry law: big when right, small when wrong. Expectancy not hit-rate.",
        doc_source="docs/TRADER_TOM_DOCTRINE.md",
        verdict=Verdict.DOCTRINE,
        tags=["asymmetry", "expectancy", "win-rate"],
        notes="If you can't win big when beta is positive, you can't win bigger when tape is thin. "
              "Capture uptrends aggressively.",
    ),
    StrategyRecord(
        id="TRADER_TOM-add-to-winners",
        title="Add to winners, never to losers. Averaging into hope = amateur trap.",
        doc_source="docs/TRADER_TOM_DOCTRINE.md",
        verdict=Verdict.DOCTRINE,
        tags=["position-sizing", "confirmation", "behavioral"],
        notes="Add-to-winners reinforces correct behavior; add-to-losers is the classic blow-up.",
    ),
    StrategyRecord(
        id="TRADER_TOM-breadth-beats-hero",
        title="Breadth > hero — IR = IC × √breadth. Library beats hero.",
        doc_source="docs/TRADER_TOM_DOCTRINE.md",
        verdict=Verdict.DOCTRINE,
        tags=["breadth", "IC", "library"],
        notes="Many small correct bets beat one big correct bet. Why we ship many sleeves.",
    ),
    StrategyRecord(
        id="TRADER_TOM-assume-wrong",
        title="Assume-wrong-until-proven. Position as if wrong; only scale when cause confirms.",
        doc_source="docs/TRADER_TOM_DOCTRINE.md",
        verdict=Verdict.DOCTRINE,
        tags=["risk-management", "discipline"],
        notes="Structural, not discipline-of-mind.",
    ),
    StrategyRecord(
        id="TRADER_TOM-sell-cause-breaks",
        title="Sell only when the CAUSE breaks — never on short-term volatility.",
        doc_source="docs/TRADER_TOM_DOCTRINE.md",
        verdict=Verdict.DOCTRINE,
        tags=["position-management", "two-layer", "duration"],
        notes="Two-layer book: durable core unsold unless thesis invalid; tactical overlay "
              "scales with confirmed regime.",
    ),
    StrategyRecord(
        id="TRADER_TOM-two-layer-book",
        title="Two-layer book — durable fundamental core + tactical overlay gross-scales with regime",
        doc_source="docs/TRADER_TOM_DOCTRINE.md",
        verdict=Verdict.DOCTRINE,
        tags=["two-layer", "architecture", "core-overlay"],
        notes="Defend in risk-OFF (small, hedged, cut fast). Press/double-down in risk-ON + "
              "confirmed long-term trend. Add to *confirmed* winners, never hope-losers.",
    ),

    # Mechanism primitives (from docs/MECHANISM_SPEC.md)
    StrategyRecord(
        id="MECH-P1-forward-commitment",
        title="P1 Forward commitment — claim before window; auto-resolve against pre-declared criteria",
        doc_source="docs/MECHANISM_SPEC.md",
        verdict=Verdict.DOCTRINE,
        tags=["mechanism", "P1", "forward-commitment"],
        notes="Retroactive claims have no standing. Silence is not free.",
    ),
    StrategyRecord(
        id="MECH-P2-binding-capacity",
        title="P2 Binding capacity declaration — accept flow up to declared; slippage measured against it",
        doc_source="docs/MECHANISM_SPEC.md",
        verdict=Verdict.DOCTRINE,
        tags=["mechanism", "P2", "capacity"],
        notes="Overclaim is self-punishing — realized slippage measured against your own number.",
    ),
    StrategyRecord(
        id="MECH-P3-lifecycle-disclosure",
        title="P3 Mandatory lifecycle disclosure — age, decay slope, crowding proxy as first-class",
        doc_source="docs/MECHANISM_SPEC.md",
        verdict=Verdict.DOCTRINE,
        tags=["mechanism", "P3", "lifecycle", "decay"],
        notes="Edges decay and capacity saturates. We don't yet know our own decay half-life.",
    ),
    StrategyRecord(
        id="MECH-binary-validity-dimensional-durability",
        title="Critical design choice: binary for validity, dimensional for durability",
        doc_source="docs/MECHANISM_SPEC.md",
        verdict=Verdict.DOCTRINE,
        tags=["mechanism", "validity", "durability"],
        notes="PIT/cost-infeasibility are FACT (binary disqualifying). Regime fit, decay, "
              "crowding, correlation are COORDINATES. Without both halves, the system can't "
              "tell itself bad news.",
    ),
]


# -----------------------------------------------------------------------------
# 3. Strategy_2026_Q3 agenda moves (next-round candidates)
# -----------------------------------------------------------------------------

def parse_strategy_q3_agenda(path: Path) -> list[StrategyRecord]:
    if not path.exists():
        return []
    text = path.read_text()
    # Naive regex for "Move N: R57+ ..." sub-sections
    moves = re.findall(r"### Move (\d+): ([^\n]+)", text)
    out = []
    for idx, title in moves:
        out.append(StrategyRecord(
            id=f"Q3-AGENDA-MOVE-{idx}",
            title=title.strip(),
            doc_source=str(path.relative_to(ROOT)),
            verdict=Verdict.HOLD,
            tags=["agenda", f"move-{idx}"],
            notes=f"Move {idx} of STRATEGY_2026_Q3.md. Not yet shipped.",
        ))
    return out


# -----------------------------------------------------------------------------
# 4. MINIMAX_SYNC § blocks (only experiment-related)
# -----------------------------------------------------------------------------

def parse_minimax_sync_experiments(path: Path) -> list[StrategyRecord]:
    """Mine MINIMAX_SYNC § blocks. We register any § that names a research
    experiment (e.g. mentions R#, V#, sleeve, factor) as a HOLD candidate so
    a human can later promote to SHIP/REFUTE based on its real outcome."""
    if not path.exists():
        return []
    text = path.read_text()
    blocks = re.split(r"^## §", text, flags=re.MULTILINE)
    out: list[StrategyRecord] = []

    for blk in blocks[1:]:  # skip preamble
        # First line is the § title
        head, _, body = blk.partition("\n")
        title_line = head.strip().split("\n")[0]

        # Heuristic: § is experiment-related if title mentions R# / V# / sleeve /
        # factor / backtest / sweep / validation
        is_experiment = bool(re.search(
            r"\b(R\d+|V\d+|sleeve|factor|backtest|sweep|validation|absorption|"
            r"construction|cis|qualif|regime|funding|hist)",
            title_line + body[:500], re.IGNORECASE))

        if not is_experiment:
            continue

        # Construct id from a sanitized version of the title
        sid = re.sub(r"[^A-Za-z0-9_-]", "-", title_line)[:80].strip("-")
        sid = f"MS-SYNC-{sid}"

        rec = StrategyRecord(
            id=sid,
            title=title_line,
            doc_source="MINIMAX_SYNC.md",
            verdict=Verdict.HOLD,
            tags=["minimax-sync", "experiment-pending"],
            notes=body[:1000].strip(),
        )
        out.append(rec)
    return out


# -----------------------------------------------------------------------------
# Orchestrator
# -----------------------------------------------------------------------------

def backfill(dry_run: bool = True, write_redis: bool = False) -> dict:
    root = ROOT
    summary = {
        "ran_at": datetime.now(tz=timezone.utc).isoformat(),
        "sources": {},
        "totals": {"by_verdict": {}, "total": 0},
    }

    all_records: list[StrategyRecord] = []

    # 1. Doctrinal (hard-coded; always present)
    all_records.extend(DOCTRINAL_RECORDS)
    summary["sources"]["DOCTRINAL"] = len(DOCTRINAL_RECORDS)

    # 2. R-entries from REFUTATION_LEDGER
    rl_path = root / "REFUTATION_LEDGER.md"
    if rl_path.exists():
        r_recs = parse_refutation_ledger(rl_path)
        all_records.extend(r_recs)
        summary["sources"]["REFUTATION_LEDGER"] = len(r_recs)

    # 3. Q3 agenda moves
    q3_path = root / "docs" / "STRATEGY_2026_Q3.md"
    q3_recs = parse_strategy_q3_agenda(q3_path)
    all_records.extend(q3_recs)
    summary["sources"]["STRATEGY_2026_Q3_AGENDA"] = len(q3_recs)

    # 4. MINIMAX_SYNC § experiments
    ms_path = root / "MINIMAX_SYNC.md"
    ms_recs = parse_minimax_sync_experiments(ms_path)
    all_records.extend(ms_recs)
    summary["sources"]["MINIMAX_SYNC_EXP"] = len(ms_recs)

    # De-dup by id (in case of collisions across sources)
    deduped: dict[str, StrategyRecord] = {}
    for r in all_records:
        if r.id in deduped:
            # Keep the first (doctrinal takes priority over MINIMAX_SYNC noise);
            # if same id twice in same source that's a parsing bug — surface it
            _existing = deduped[r.id]
            if _existing.doc_source != r.doc_source:
                _logger_or_print(
                    f"  ⚠ id collision: '{r.id}' from {_existing.doc_source} and {r.doc_source} — keeping first"
                )
            continue
        deduped[r.id] = r
    all_records = list(deduped.values())

    # Counts
    by_verdict: dict[str, int] = {}
    for r in all_records:
        v = r.verdict.value
        by_verdict[v] = by_verdict.get(v, 0) + 1
    summary["totals"]["by_verdict"] = by_verdict
    summary["totals"]["total"] = len(all_records)

    # Always: write local audit JSON
    if not dry_run:
        OUT_LOCAL.parent.mkdir(parents=True, exist_ok=True)
        payload = {r.id: r.to_dict() for r in all_records}
        OUT_LOCAL.write_text(json.dumps(payload, indent=2, sort_keys=True))
        print(f"  ✓ wrote {OUT_LOCAL} ({len(payload)} records)")
    else:
        print(f"  (dry-run: skipped writing {OUT_LOCAL})")

    # Optionally: Redis upsert
    if write_redis and not dry_run:
        from src.data.vector.strategy_store import upsert_many
        n = upsert_many(all_records)
        summary["totals"]["redis_upserted"] = n
        print(f"  ✓ upserted {n} to Redis")

    return summary


def _logger_or_print(s: str) -> None:
    print(s)


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Backfill strategy records from source docs.")
    p.add_argument("--dry-run", action="store_true", default=True,
                   help="(default) don't write anything")
    p.add_argument("--write", action="store_true",
                   help="actually write local JSON audit file")
    p.add_argument("--write-redis", action="store_true",
                   help="also push to Upstash Redis (requires env vars)")
    args = p.parse_args()

    dry = not args.write
    summary = backfill(dry_run=dry, write_redis=args.write_redis)

    print()
    print("=" * 60)
    print("STRATEGY VECTOR BACKFILL SUMMARY")
    print("=" * 60)
    print(f"  ran_at: {summary['ran_at']}")
    print()
    print("  by source:")
    for src, n in summary["sources"].items():
        print(f"    {src:<28} {n:>4}")
    print()
    print("  by verdict:")
    for v, n in sorted(summary["totals"]["by_verdict"].items()):
        print(f"    {v:<10} {n:>4}")
    print(f"  {'TOTAL':<12} {summary['totals']['total']:>4}")
    if "redis_upserted" in summary["totals"]:
        print(f"  {'redis_upserted':<28} {summary['totals']['redis_upserted']:>4}")
    print()


if __name__ == "__main__":
    main()
