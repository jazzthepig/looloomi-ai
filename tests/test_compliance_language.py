"""
Compliance-language guard — hard rule #1, which had never been enforced by anything.

CometCloud holds no Hong Kong SFC Type 4 or Type 9 licence, so every user-facing
surface must use POSITIONING language and never transactional language. CLAUDE.md
calls a breach a P0 and `.claude/skills/compliance-language/` documents the
substitution tables. Until now neither was checked by CI, and the full code check on
2026-08-09 found NINE live violations across five files — API response narratives
and a dashboard component:

    macro.py       "Avoid high-beta altcoins."
    cis.py         "Avoid over-leveraged protocols."
    signals.py     "avoid shorts"  ·  "not a buy list"  (x2)
    market.py      "Avoid chasing parabolic moves."  ·  "Avoid FOMO entry."
                   "Avoid chasing."  ·  "Avoid catching falling knives"
    CISCompare.jsx "avoid over-leveraged protocols"

Note what they have in common: every one is HEDGING prose, written to sound
prudent. "Avoid chasing" and "not a buy list" both read as restraint, which is
exactly why they survived review — the author's intent was to be careful, and the
words that express caution to a human are the same words a regulator reads as
advice. That is why this has to be mechanical rather than a matter of judgement.

SCOPE. User-facing surfaces only: API routers (JSON reaches clients), dashboard
components, and static HTML. NOT research code, tests, migrations or internal
logs — the skill explicitly permits `BUY`/`SELL` in a Freqtrade log or a
past-tense backtest description, and a guard that flagged those would be turned off.

Run: python3 -m tests.test_compliance_language
"""
import os
import pathlib
import re
import sys

REPO = pathlib.Path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Surfaces a client can actually see.
_SURFACES = [
    ("src/api/routers", ("*.py",)),
    ("dashboard/src", ("*.jsx", "*.js", "*.tsx")),
]
_STATIC_HTML = ("strategy.html", "vision.html", "index.html")

# Transactional verbs from .claude/skills/compliance-language/SKILL.md. `HOLD` is
# excluded: the skill permits it in prose and bans it only as a signal LABEL, and a
# guard that fires on prose gets disabled.
# ⚠️ `go long` 在,而裸的祈使 `Long the …` 不在 —— 这个缺口让下面这句在
# `/api/v1/signals/edge-map` 的【响应体】里活了很久 (S-239):
#
#     "how_to_read": "Long the top tier (STRONG OUTPERFORM) when the tape is
#                     risk-ON …; short the bottom tier (UNDERPERFORM) when risk-OFF"
#
# 禁词表**枚举了这个概念的一种说法**。和 S-209(一个 regime 两种拼法)、
# S-229(只守我刚看见的那个病例)同一族:列举实例,而不是刻画构造。
#
# 构造是【祈使动词 + 定冠词】:`long the` / `short the`。它抓到了全部 6 处真违规,
# 而不会碰 `admin.py` 的 "Short top-ups stay synchronous"(short 是形容词)、
# 也不碰 `long-only` / `long/short`(策略类型名词)/ `longer` / `short window`。
_FORBIDDEN = re.compile(
    r"\b(buy|sell|accumulate|liquidate|avoid|trim|stop out|load up|"
    r"go long|go short|(?:long|short)\s+the\b|"
    r"we recommend|you should|investors should|price target|top pick)\b", re.I)

# Substrings that are the same letters in a non-transactional role.
_EXEMPT = re.compile(
    r"buyer|buy_|_buy|sell_|_sell|sellers|circular dep|avoid circular|"
    r"# |//\s|buySell|avoidance", re.I)

_STRING_LIT = re.compile(r'"([^"\\]{12,300})"|\'([^\'\\]{12,300})\'')


def _user_facing_files():
    for rel, pats in _SURFACES:
        base = REPO / rel
        if not base.exists():
            continue
        for pat in pats:
            for p in sorted(base.rglob(pat)):
                if "node_modules" in str(p) or ".venv" in str(p):
                    continue
                yield p
    for name in _STATIC_HTML:
        for p in REPO.rglob(name):
            if "node_modules" not in str(p) and "dist" not in str(p):
                yield p


def test_no_transactional_language_on_user_facing_surfaces():
    """Positioning language only. The allowed vocabulary is the five-tier enum;
    anything that tells a reader what to DO with their money is Type 4 territory."""
    offenders = []
    for p in _user_facing_files():
        txt = p.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(txt.splitlines(), 1):
            s = line.strip()
            if s.startswith(("#", "//", "*", "--")):
                continue
            for m in _STRING_LIT.finditer(line):
                lit = m.group(1) or m.group(2) or ""
                if _EXEMPT.search(lit):
                    continue
                hit = _FORBIDDEN.search(lit)
                if hit:
                    offenders.append(
                        f"{p.relative_to(REPO)}:{i}: {hit.group(0)!r} in {lit[:80]!r}")
    assert not offenders, (
        "transactional language on a user-facing surface — no SFC Type 4/9 licence, "
        "so this is a P0 (CLAUDE.md hard rule 1):\n  " + "\n  ".join(offenders[:25]))


_META_DISPLAY = re.compile(r"PROHIBITED LANGUAGE|line-through|✗ PROHIBITED", re.I)


def test_signal_vocabulary_is_the_five_tier_enum():
    """The compliance enum is exactly five values. A sixth invented anywhere near a
    signal field is how BUY re-enters under another name."""
    allowed = {"STRONG OUTPERFORM", "OUTPERFORM", "NEUTRAL", "UNDERPERFORM", "UNDERWEIGHT"}
    bad = {"STRONG BUY", "BUY", "SELL", "STRONG SELL", "ACCUMULATE", "REDUCE", "HOLD"}
    offenders = []
    for p in _user_facing_files():
        txt = p.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(txt.splitlines(), 1):
            if line.strip().startswith(("#", "//", "*")):
                continue
            # The methodology page RENDERS the banned list struck through — that is
            # the rule being explained to a reader, not applied to an asset. A guard
            # that cannot tell use from mention would force us to stop documenting
            # the very policy it enforces.
            ctx = "\n".join(txt.splitlines()[max(0, i - 6):i + 2])
            if _META_DISPLAY.search(ctx):
                continue
            for tok in bad:
                if re.search(rf'["\']{tok}["\']', line):
                    offenders.append(f"{p.relative_to(REPO)}:{i}: signal literal {tok!r}")
    assert not offenders, (
        "non-enum signal literal on a user-facing surface:\n  " + "\n  ".join(offenders[:20]))
    assert len(allowed) == 5


def test_the_guard_fires_on_the_phrasing_that_slipped_through():
    """Negative control, using the real strings this found. Both were written to
    sound CAUTIOUS — which is precisely why they survived human review, and why the
    check has to be mechanical."""
    for lit in ("Commodities, RWA, and BTC as inflation hedges. Avoid high-beta altcoins.",
                "strongest quality reads; regime lens, not a buy list"):
        assert _FORBIDDEN.search(lit), f"guard must flag: {lit!r}"
        assert not _EXEMPT.search(lit), f"exemption wrongly swallows: {lit!r}"
    # and must NOT fire on the legitimate internal usages
    for ok in ("Lazy-import vector store to avoid circular deps at startup.",
               "buyer_concentration", "sell_side_flow"):
        assert _EXEMPT.search(ok), f"exemption must cover: {ok!r}"


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = f = 0
    for t in TESTS:
        try:
            t(); print(f"  ✓ {t.__name__}"); p += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__}\n      {e}"); f += 1
    print(f"\n{'✅' if not f else '🔴'} {p}/{len(TESTS)} compliance-language checks passed")
    sys.exit(1 if f else 0)
