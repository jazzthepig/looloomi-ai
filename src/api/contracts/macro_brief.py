"""Canonical macro-brief prompt + regeneration gate (S-186/S-187, 2026-08-20).

WHY THIS FILE EXISTS AT ALL. The prompt that actually produces the live brief
lived in `Shadow/cometcloud-local/macro_brief_push.py` — the Mac lane — and a
SECOND prompt sat in `src/data/market/macro_brief_v2.py` with zero callers and
Chinese output, flagged as dead on 2026-07-08 and never removed. Asked to
"upgrade the prompt" on 2026-08-20, the first file I opened was the dead one.
Two prompts in one repo is not redundancy, it is a coin flip about which one a
future edit lands on. The dead one is deleted; this is the only one.

Generation stays Mac-side because the model is local (LM Studio, 127.0.0.1:1234)
and Railway cannot reach it. So this module is the CONTRACT, not the runtime:
the Mac copies `build_prompt` and reports `PROMPT_VERSION` back with the brief,
and `/internal/macro-brief` records what arrived. That is the same shape as the
cis_push SCHEMA_VERSION echo (CLAUDE.md #2) and for the same reason — two
codebases on two machines drift silently unless the drift has somewhere to show.

WHAT THE OLD PROMPT GOT WRONG. Measured against the live output (1,196 chars,
qwen3.5-9b, 2026-08-20 11:00):

  1. It shipped LEVELS only. The brief said "BTC's $71,848 consolidation" with
     no reference to what moved. At a 6-hour cadence that is merely thin; at a
     5-minute cadence it is the whole problem, because the only interesting fact
     is what changed since the last brief.
  2. Missing inputs arrived as "—" and the model narrated around them as though
     the reading existed. This is I1 (NaN-honesty) in prose form: unmeasured must
     not become a confident sentence. Now absent fields are named as absent and
     the model is forbidden to characterise them.
  3. "Write the CometCloud macro brief for today" — wrong tense at 5 minutes.
  4. Compliance was one line about BUY/SELL. It missed the larger exposure for a
     firm with no 投顾 licence: FORWARD-LOOKING claims. "BTC is likely to test
     $75k" is not solved by avoiding the word "buy".
  5. Nothing constrained length or structure, so the output drifted run to run.
  6. Nothing forbade inventing numbers absent from the snapshot.
  7. Nothing carried CLAUDE.md's own regime doctrine — that defensive regimes
     compress grades BY DESIGN — so a Tightening brief reads as bearish opinion
     rather than as a described mechanism.

CHANGING THIS FILE. Bump PROMPT_VERSION, note it in MINIMAX_SYNC §MACRO-BRIEF,
and let the Mac pick it up. A brief arriving with an older version is not an
error — the receiver records and reports, it does not reject, because a receiver
cannot know which of two deployments is right (S-178).
"""
from __future__ import annotations

import re

# Bump on any change to build_prompt's text or to the gate thresholds.
PROMPT_VERSION = "mb-2"

# ── Regeneration gate (S-187) ────────────────────────────────────────────────
#
# Jazz, 2026-08-20: the brief must never be more than five minutes behind the
# data. That is a statement about FRESHNESS, and freshness does not require
# regenerating prose — the inputs mostly do not move in five minutes (Fear &
# Greed updates roughly daily, DeFi TVL roughly hourly). Regenerating anyway
# produces text that differs run to run from sampling rather than from the
# market, which on a page an allocator reads manufactures the appearance of
# signal. So: poll every five minutes, rewrite only when something happened.
#
# Thresholds are pre-registered here rather than tuned against output, so that
# "the brief changed" always means "an input crossed a stated line".
POLL_INTERVAL_S = 300           # how often the Mac re-reads the data

# Any ONE of these is sufficient cause to regenerate.
BTC_MOVE_PCT = 0.5              # |Δ BTC| since the brief in force
DOMINANCE_MOVE_PP = 0.3         # BTC dominance, percentage POINTS
MCAP_MOVE_PCT = 0.8
TVL_MOVE_PCT = 2.0              # DeFi TVL is hourly; below this it is noise
FNG_BAND_CHANGE = True          # Fear/Greed crossing a named band, not a value
REGIME_CHANGE = True            # always regenerate — this is the headline fact
GRADE_CHANGE_MIN = 2            # ≥2 assets changing letter grade

# Floors and ceilings on the gate itself.
MIN_REGEN_GAP_S = 300           # never call the model twice inside 5 minutes,
                                # however violently the market moves — the Mac
                                # also runs the T1 CIS engine and must not be
                                # starved by a volatile hour.
MAX_BRIEF_AGE_S = 1800          # …and never let prose sit longer than 30 min,
                                # even on a dead-flat tape. A brief that never
                                # regenerates is indistinguishable from a
                                # generation pipeline that has died — which is
                                # exactly how the depth-divergence record sat
                                # broken for days (S-175).

_FNG_BANDS = ((0, 25, "Extreme Fear"), (25, 45, "Fear"), (45, 55, "Neutral"),
              (55, 75, "Greed"), (75, 101, "Extreme Greed"))


def fng_band(value) -> str | None:
    """Named band for a Fear & Greed reading. None when unmeasured."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    for lo, hi, name in _FNG_BANDS:
        if lo <= v < hi:
            return name
    return None


def _pct_move(now, before) -> float | None:
    try:
        a, b = float(now), float(before)
    except (TypeError, ValueError):
        return None
    if b == 0:
        return None
    return abs(a - b) / abs(b) * 100.0


def should_regenerate(current: dict, previous: dict | None,
                      age_s: float) -> tuple[bool, str]:
    """Decide whether to spend a local-model call. Returns (regenerate, why).

    `why` is not decoration — it is fed into the prompt, because at this cadence
    the reason a brief exists is the most informative thing about it. It is also
    what a human reads when asking why the text on screen just changed.
    """
    if previous is None:
        return True, "no brief in force"
    if age_s >= MAX_BRIEF_AGE_S:
        return True, f"brief is {int(age_s // 60)} min old (ceiling {MAX_BRIEF_AGE_S // 60} min)"
    if age_s < MIN_REGEN_GAP_S:
        return False, f"last brief {int(age_s)}s ago (floor {MIN_REGEN_GAP_S}s)"

    reasons: list[str] = []

    cur_regime = current.get("macro_regime")
    prev_regime = previous.get("macro_regime")
    if REGIME_CHANGE and cur_regime and prev_regime and cur_regime != prev_regime:
        reasons.append(f"regime {prev_regime} → {cur_regime}")

    for key, thresh, label in (
            ("btc_price", BTC_MOVE_PCT, "BTC"),
            ("total_market_cap_usd", MCAP_MOVE_PCT, "total mcap"),
            ("defi_tvl_usd", TVL_MOVE_PCT, "DeFi TVL")):
        mv = _pct_move(current.get(key), previous.get(key))
        if mv is not None and mv >= thresh:
            reasons.append(f"{label} {mv:.1f}% (≥{thresh}%)")

    try:
        dom_now = float(current.get("btc_dominance"))
        dom_before = float(previous.get("btc_dominance"))
        if abs(dom_now - dom_before) >= DOMINANCE_MOVE_PP:
            reasons.append(f"BTC dominance {dom_now - dom_before:+.2f}pp")
    except (TypeError, ValueError):
        pass

    if FNG_BAND_CHANGE:
        b_now = fng_band(current.get("fear_greed_index"))
        b_before = fng_band(previous.get("fear_greed_index"))
        if b_now and b_before and b_now != b_before:
            reasons.append(f"Fear/Greed {b_before} → {b_now}")

    cur_g = {a.get("symbol"): a.get("grade") for a in current.get("top_assets") or []}
    prev_g = {a.get("symbol"): a.get("grade") for a in previous.get("top_assets") or []}
    moved = [s for s, g in cur_g.items()
             if s in prev_g and g and prev_g[s] and g != prev_g[s]]
    if len(moved) >= GRADE_CHANGE_MIN:
        reasons.append(f"{len(moved)} grade changes ({', '.join(sorted(moved)[:4])})")

    if reasons:
        return True, "; ".join(reasons)
    return False, "inputs unchanged within thresholds"


# ── The prompt ───────────────────────────────────────────────────────────────

_ABSENT = ("—", "", None, "N/A", "n/a")


def _fmt(v, prefix="$", suffix="") -> str | None:
    """Formatted value, or None when the reading is absent.

    Returning None rather than a dash is the point: the caller must then decide
    to omit the line entirely, so an unmeasured input can never reach the model
    dressed as a measured one.
    """
    if v in _ABSENT:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if abs(f) >= 1e12:
        return f"{prefix}{f / 1e12:.2f}T{suffix}"
    if abs(f) >= 1e9:
        return f"{prefix}{f / 1e9:.1f}B{suffix}"
    if abs(f) >= 1e6:
        return f"{prefix}{f / 1e6:.1f}M{suffix}"
    return f"{prefix}{f:,.2f}{suffix}".rstrip("0").rstrip(".") if prefix == "$" \
        else f"{prefix}{f:g}{suffix}"


#: Below this a delta is rounding, not movement, and listing it under a heading
#: that says "MOVEMENT" tells the model something moved when nothing did. The
#: first draft emitted "Total market cap: +0.00% since last brief" — three lines
#: of zeroes under a heading asserting change, which is the prompt contradicting
#: itself in the one place the model is told to anchor its first paragraph.
_DELTA_FLOOR = 0.01


def _delta_line(label: str, now, before, unit="%") -> str | None:
    if now in _ABSENT or before in _ABSENT:
        return None
    try:
        a, b = float(now), float(before)
    except (TypeError, ValueError):
        return None
    if unit == "pp":
        d = a - b
        return f"  {label}: {d:+.2f}pp since last brief" if abs(d) >= _DELTA_FLOOR else None
    if b == 0:
        return None
    pct = (a - b) / abs(b) * 100
    return f"  {label}: {pct:+.2f}% since last brief" if abs(pct) >= _DELTA_FLOOR else None


def build_prompt(current: dict, previous: dict | None = None,
                 why: str = "", top_assets: list | None = None) -> str:
    """The macro-brief prompt. Mac-side generation must use exactly this text.

    `previous` and `why` are what make the brief worth regenerating at all: the
    model is told what moved and why it was woken, so the output describes a
    change rather than restating a level.
    """
    top_assets = top_assets or current.get("top_assets") or []

    measured: list[str] = []
    absent: list[str] = []

    def add(label: str, value, formatted=None):
        got = formatted if formatted is not None else _fmt(value)
        (measured.append(f"  {label}: {got}") if got is not None
         else absent.append(label))

    regime = current.get("macro_regime")
    if regime and regime not in _ABSENT:
        measured.append(f"  Macro regime: {regime}")
    else:
        absent.append("Macro regime")

    add("BTC", current.get("btc_price"))
    add("BTC 24h change", current.get("btc_change_24h"),
        None if current.get("btc_change_24h") in _ABSENT
        else f"{float(current['btc_change_24h']):+.2f}%")
    add("BTC dominance", current.get("btc_dominance"),
        None if current.get("btc_dominance") in _ABSENT
        else f"{float(current['btc_dominance']):.2f}%")
    add("Total market cap", current.get("total_market_cap_usd"))
    add("DeFi TVL", current.get("defi_tvl_usd"))

    fng = current.get("fear_greed_index")
    band = fng_band(fng)
    if band:
        measured.append(f"  Fear & Greed: {fng} ({band})")
    else:
        absent.append("Fear & Greed")

    deltas = []
    if previous:
        for label, key, unit in (("BTC", "btc_price", "%"),
                                 ("Total market cap", "total_market_cap_usd", "%"),
                                 ("DeFi TVL", "defi_tvl_usd", "%"),
                                 ("BTC dominance", "btc_dominance", "pp")):
            line = _delta_line(label, current.get(key), previous.get(key), unit)
            if line:
                deltas.append(line)

    asset_lines = []
    for a in top_assets[:8]:
        score = a.get("cis_score") if a.get("cis_score") is not None else a.get("score")
        try:
            score = f"{float(score):.1f}"
        except (TypeError, ValueError):
            score = "unmeasured"
        asset_lines.append(
            f"  {a.get('symbol', '?')}: CIS {score}, grade {a.get('grade', 'unmeasured')}, "
            f"positioning {a.get('signal', 'NEUTRAL')}")

    absent_block = (
        "\nNOT MEASURED right now — you must not characterise, estimate or "
        "mention these:\n" + "\n".join(f"  {a}" for a in absent) + "\n") if absent else ""

    # If nothing cleared the floor, say so explicitly rather than omitting the
    # section. An absent heading reads as "not provided"; this reads as "checked,
    # and the answer is nothing" — which paragraph 1 is instructed to report as a
    # finding in its own right.
    delta_block = ("\nMOVEMENT since the brief currently on screen:\n"
                   + ("\n".join(deltas) if deltas
                      else "  none above the reporting floor — the tape is flat")
                   + "\n") if previous else ""

    why_block = f"\nYou were asked to rewrite because: {why}\n" if why else ""

    return f"""You write the CometCloud macro brief — a short read of the crypto \
market for institutional allocators and family offices. It is refreshed \
continuously, so write about the market as it stands NOW, never "today" or \
"this week".

MEASURED DATA (this is the complete set; nothing else is known to you):
{chr(10).join(measured)}
{absent_block}{delta_block}

Top assets by CIS score:
{chr(10).join(asset_lines) or "  (unavailable)"}
{why_block}

WRITE:
- 3 short paragraphs, 120-180 words total. No headings, no bullet points, no
  markdown formatting.
- Paragraph 1: what the market is doing, anchored to the movement above if any.
  If nothing moved materially, say so plainly — a quiet tape is a finding, not a
  gap to fill.
- Paragraph 2: what the regime implies for positioning across the book.
- Paragraph 3: the single thing most worth watching, stated as an observable
  condition rather than a prediction.

RULES — each of these has a reason, follow all of them:
- Use ONLY the numbers given above. Do not introduce any figure, level, ratio or
  historical comparison that does not appear in this prompt. If you want to cite
  something you were not given, leave it out.
- For anything listed as NOT MEASURED: say nothing at all. Do not write "data
  unavailable", do not infer it, do not work around it. Silence, not a hedge.
- Positioning language is a fixed vocabulary: STRONG OUTPERFORM, OUTPERFORM,
  NEUTRAL, UNDERPERFORM, UNDERWEIGHT. Never BUY, SELL, ACCUMULATE, AVOID,
  REDUCE, or any paraphrase of them ("attractive entry", "worth adding",
  "time to trim"). Use the exact term from the asset list; do not upgrade or
  soften it.
- NO FORWARD-LOOKING CLAIMS. Do not predict, forecast, project, or say what is
  "likely", "expected", "poised", "set to", or "should". Describe conditions
  that currently hold and what would have to happen for them to change. This
  matters more than the vocabulary rule above: we hold no advisory licence.
- A defensive regime (Tightening, Risk-Off, Stagflation) compresses grades by
  design — the scoring narrows deliberately in those regimes. If the regime is
  defensive, present low grades as that mechanism operating, not as a bearish
  view. Relative ranking still differentiates.
- No promises about returns, no reference to our own performance, no mention of
  infrastructure, models, or how any of this is computed.
- Plain declarative prose. No hype, no "amid", no "signals a potential", no
  rhetorical questions.

Output the three paragraphs and nothing else."""


# ── Validation (S-186) ───────────────────────────────────────────────────────
#
# Every rule in the prompt above is a REQUEST. A 9B local model honours most of
# them most of the time, and "most of the time" is not a compliance posture for
# a firm with no 投顾 licence publishing to allocators. The prompt states the
# rules so the model can follow them; this validates so that when it does not,
# the text does not reach a reader.
#
# The asymmetry with S-178's "receivers echo, never reject" is deliberate and
# narrow: that principle covers SCHEMA disagreements, where a receiver genuinely
# cannot know which of two deployments is right. A brief saying "BUY BTC" is not
# a disagreement about versions — CLAUDE.md #1 makes it a P0, and the correct
# action is to refuse it and keep serving the previous brief. A missing brief is
# recoverable; a compliance breach on an investor page is not.

_BANNED_TERMS = [
    # CLAUDE.md #1 — the enum is the ONLY permitted positioning vocabulary.
    r"\bbuy\b", r"\bsell\b", r"\bselling\b", r"\baccumulate\b", r"\baccumulating\b",
    r"\bavoid\b", r"\breduce\b", r"\breducing\b", r"\btrim\b", r"\btrimming\b",
    r"\bshort\s+(?:it|this|the\s+\w+)\b", r"\bgo\s+long\b", r"\btake\s+profit",
    r"\bentry\s+point", r"\battractive\s+entry", r"\bworth\s+(?:adding|owning|buying)",
    r"\bdip\s+buy", r"\bexit\s+(?:now|here)",
]

_FORWARD_TERMS = [
    # The larger exposure. Avoiding "buy" while writing "BTC should reach $80k"
    # solves nothing.
    r"\bwill\s+(?:likely|probably|continue|reach|test|break|rise|fall)\b",
    r"\bis\s+likely\s+to\b", r"\bexpected\s+to\b", r"\bwe\s+expect\b",
    r"\bpoised\s+to\b", r"\bset\s+to\b", r"\bon\s+track\s+to\b",
    r"\bshould\s+(?:reach|test|hold|break|continue|see)\b",
    r"\bforecast", r"\bproject(?:ed|ion)\b", r"\banticipate", r"\bpredict",
    r"\bin\s+the\s+coming\s+(?:days|weeks|months)\b",
    r"\bnear[- ]term\s+(?:target|upside|downside)\b",
]

# CLAUDE.md #8 — nothing investor-facing names our infrastructure.
_INTERNALS = [
    r"\bFastAPI\b", r"\bRailway\b", r"\bOllama\b", r"\bLM\s*Studio\b",
    r"\bSupabase\b", r"\bRedis\b", r"\bqwen\b", r"\bgemma\b", r"\bMac\s*Mini\b",
    r"\bprompt\b", r"\bLLM\b", r"\bmodel\s+(?:output|says|generated)\b",
]

MIN_WORDS, MAX_WORDS = 90, 230


def validate_brief(text: str, snapshot: dict | None = None) -> dict:
    """Check a generated brief against the rules the prompt asked for.

    Returns {ok, violations[], warnings[], words}. `ok` False means DO NOT SERVE.
    Warnings are things worth seeing that do not justify withholding the brief.
    """
    violations: list[str] = []
    warnings: list[str] = []
    body = text or ""

    for pat in _BANNED_TERMS:
        m = re.search(pat, body, re.I)
        if m:
            violations.append(f"banned positioning term: {m.group(0)!r} "
                              f"(CLAUDE.md #1 — enum only)")
    for pat in _FORWARD_TERMS:
        m = re.search(pat, body, re.I)
        if m:
            violations.append(f"forward-looking claim: {m.group(0)!r} "
                              f"(no advisory licence)")
    for pat in _INTERNALS:
        m = re.search(pat, body, re.I)
        if m:
            violations.append(f"names internals: {m.group(0)!r} (CLAUDE.md #8)")

    words = len(body.split())
    if words < MIN_WORDS:
        violations.append(f"too short: {words} words (min {MIN_WORDS}) — "
                          f"a truncated generation, not a brief")
    elif words > MAX_WORDS:
        warnings.append(f"long: {words} words (target ≤{MAX_WORDS})")

    if re.search(r"^\s*(#{1,6}\s|\*\s|-\s|\d\.\s)", body, re.M):
        warnings.append("contains markdown headings or bullets; prompt asked for prose")
    if re.search(r"</?\w+>|^\s*\{|\"action\"\s*:", body, re.M):
        violations.append("contains markup or JSON — a leaked template or "
                          "reasoning artefact, not prose")

    # Anti-hallucination: dollar figures in the prose that are nowhere in the
    # snapshot. Deliberately a WARNING — formatting differs ($2.45T vs
    # 2450000000000) and a false positive that blocks the brief would be worse
    # than the thing it catches.
    if snapshot:
        known = set()
        for v in snapshot.values():
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            known |= {f"{f:,.0f}", f"{f/1e12:.2f}", f"{f/1e9:.1f}", f"{f:.2f}"}
        for cited in re.findall(r"\$\s?([\d,]+(?:\.\d+)?)", body):
            if cited.replace(",", "") and cited not in known and \
                    cited.rstrip("0").rstrip(".") not in {k.rstrip("0").rstrip(".") for k in known}:
                warnings.append(f"cites ${cited}, not obviously in the snapshot")

    return {"ok": not violations, "violations": violations,
            "warnings": warnings, "words": words,
            "prompt_version": PROMPT_VERSION}
