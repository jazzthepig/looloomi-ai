"""
T-033: 后端 CIS narrative 短语措辞修订 — 避免短期 trend 词与负 24h% 同屏

T-022 前半(移动端 pct24h 后缀)shipped,但 acceptance 还要求:
  'strong momentum' / 'positions to outperform on strong momentum' 这类
  short-window trend-implying 词,在 OUTPERFORM + 负 24h 条件下不再出现。

phrase 来源:`src/data/cis/narrative.py` `_STRONG['M']='strong momentum'`。
LLM path(Gemma)若 push 了 narrative,则 narrative_source='llm' 优先,本卡
deterministic fallback 才生效(LLM down 时常驻路径)。

跑法:python3 -m tests.test_cis_narrative_phrasing
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_NARRATIVE = _ROOT / "src" / "data" / "cis" / "narrative.py"

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


def _src() -> str:
    return _NARRATIVE.read_text(encoding="utf-8")


# ── 1. Source-level guards ─────────────────────────────────────────────────

def test_strong_m_phrase_no_longer_short_window_implying() -> None:
    """The whole point of T-033 is the `_STRONG['M']` entry no longer says
    'strong momentum'. The phrase implies a short-window trend that
    conflicts with a negative 24h % on the same card (T-022 prior_value).
    Pinned both at the dict literal AND the absence from compiled output."""
    src = _src()

    # Read the dict literal — find the M entry in _STRONG specifically.
    m = re.search(
        r"_STRONG\s*=\s*\{(.*?)\n\}",
        src,
        re.DOTALL,
    )
    check("_STRONG dict is extractable from narrative.py",
          m is not None,
          "could not find _STRONG dict")
    if m is None:
        return
    body = m.group(1)

    # The M entry should no longer be 'strong momentum'.
    bad_m = re.search(r'"\s*M\s*"\s*:\s*"strong momentum"', body)
    check("_STRONG['M'] is no longer the literal 'strong momentum'",
          bad_m is None,
          "still pinned to short-window trend-implying phrase")

    # And it should be a structural / non-window-bound phrase.
    new_m = re.search(r'"\s*M\s*"\s*:\s*"([^"]+)"', body)
    check("_STRONG['M'] has a replacement phrase",
          new_m is not None,
          "could not read new _STRONG['M'] value")
    if new_m is not None:
        new_phrase = new_m.group(1)
        check("_STRONG['M'] phrase does NOT contain 'strong momentum'",
              "strong momentum" not in new_phrase,
              f"phrase is {new_phrase!r}")
        check("_STRONG['M'] phrase is non-empty and structural-flavored",
              len(new_phrase) > 5 and "constructive" in new_phrase.lower(),
              f"phrase is {new_phrase!r} — expected 'constructive ...' wording")


def test_signal_phrase_outperform_keeps_compliance() -> None:
    """T-033 does NOT change `_SIGNAL_PHRASE['OUTPERFORM']` because it is
    a compliance positioning-language phrase (CLAUDE.md rule 1: OUTPERFORM
    is allowed). Pinning against accidental rewrites that drift into
    buy/sell territory."""
    src = _src()
    m = re.search(
        r"_SIGNAL_PHRASE\s*=\s*\{(.*?)\n\}",
        src,
        re.DOTALL,
    )
    check("_SIGNAL_PHRASE dict is extractable",
          m is not None,
          "could not find _SIGNAL_PHRASE dict")
    if m is None:
        return
    body = m.group(1)
    outl = re.search(r'"OUTPERFORM"\s*:\s*"([^"]+)"', body)
    check("_SIGNAL_PHRASE['OUTPERFORM'] still defined",
          outl is not None,
          "could not read OUTPERFORM phrase")
    if outl is not None:
        phrase = outl.group(1)
        check("_SIGNAL_PHRASE['OUTPERFORM'] does NOT drift to BUY/SELL/HOLD",
              not any(w in phrase.lower() for w in ("buy", "sell", "hold", "accumulate", "avoid", "reduce")),
              f"phrase is {phrase!r}")
        check("_SIGNAL_PHRASE['OUTPERFORM'] still says 'positions to outperform'",
              phrase == "positions to outperform",
              f"phrase changed: {phrase!r}")


# ── 2. Runtime output guards (deterministic narrative builder) ─────────────

def _make_asset(symbol: str, signal: str, m: float, change_24h: float | None = None) -> dict:
    """Build a minimal asset dict matching the shape narrative.py expects."""
    a = {
        "symbol": symbol,
        "grade": "B+",
        "signal": signal,
        "macro_regime": "RISK_ON",
        # Nested pillar form (preferred)
        "pillars": {"F": 70.0, "M": m, "O": 65.0, "S": 60.0, "A": 75.0},
    }
    if change_24h is not None:
        a["change_24h"] = change_24h
    return a


def test_narrative_does_not_contain_strong_momentum_for_outperform_negative_24h() -> None:
    """The bug T-022 / T-033 close: an asset flagged OUTPERFORM with a
    strong M pillar but a *negative* 24h change should not have the words
    'strong momentum' next to its 24h %. The deterministic fallback is
    what users see when LM Studio is down — it's the always-on floor."""

    sys.path.insert(0, str(_ROOT))
    from src.data.cis.narrative import build_asset_narrative  # noqa: E402

    asset = _make_asset("ETH", signal="OUTPERFORM", m=72.0, change_24h=-7.45)
    text = build_asset_narrative(asset, regime="RISK_ON").lower()

    check("ETH OUTPERFORM + M=72 + 24h=-7.45 narrative does NOT contain 'strong momentum'",
          "strong momentum" not in text,
          f"got: {text!r}")
    check("ETH OUTPERFORM + M=72 narrative DOES contain the new 'constructive momentum profile'",
          "constructive momentum profile" in text,
          f"got: {text!r}")


def test_narrative_grid_signal_x_m_strength_x_24h() -> None:
    """5-row grid covering: every (signal × M-strength × 24h sign) combo
    the bug appeared in. None should leak 'strong momentum' into user-
    facing narrative."""
    sys.path.insert(0, str(_ROOT))
    from src.data.cis.narrative import build_asset_narrative  # noqa: E402

    grid = [
        # (symbol, signal, M, 24h)  — 24h deliberately negative to mirror T-022 prior_value
        ("ETH",  "OUTPERFORM",      72.0,  -7.45),  # the prior_value case
        ("SOL",  "OUTPERFORM",      68.0,  -3.20),  # milder negative
        ("BTC",  "OUTPERFORM",      80.0,  -1.50),  # small negative
        ("AVAX", "STRONG OUTPERFORM", 88.0, -8.98), # strong + negative — biggest risk
        ("LINK", "OUTPERFORM",      65.0,  -0.10),  # just-over-threshold + tiny negative
    ]
    for sym, sig, m, chg in grid:
        asset = _make_asset(sym, signal=sig, m=m, change_24h=chg)
        text = build_asset_narrative(asset, regime="RISK_OFF")
        check(
            f"{sym} signal={sig!r} M={m} 24h={chg}% narrative has no 'strong momentum'",
            "strong momentum" not in text.lower(),
            f"got: {text!r}",
        )


def test_narrative_still_renders_for_neutral_signal() -> None:
    """Pin that the rewrite didn't break the NEUTRAL path — NEUTRAL has no
    strong-phrase splice, but if the dict refactor broke the lookup, this
    would silently fall back to 'screens neutral' (the default)."""
    sys.path.insert(0, str(_ROOT))
    from src.data.cis.narrative import build_asset_narrative  # noqa: E402

    asset = _make_asset("BTC", signal="NEUTRAL", m=55.0, change_24h=0.5)
    text = build_asset_narrative(asset, regime="EASING")
    check("NEUTRAL narrative still builds (no exception, non-empty)",
          isinstance(text, str) and len(text) > 20,
          f"got: {text!r}")


def test_narrative_underperform_unaffected() -> None:
    """_WEAK['M'] = 'fading momentum' is OUT of scope for T-033 (acceptance
    only covers STRONG-side phrases and the OUTPERFORM signal). Pin it
    unchanged so a future refactor doesn't accidentally drop the symmetric
    WEAK rewrite that was discussed and deferred."""
    src = _src()
    m = re.search(
        r"_WEAK\s*=\s*\{(.*?)\n\}",
        src,
        re.DOTALL,
    )
    check("_WEAK dict extractable",
          m is not None,
          "could not find _WEAK dict")
    if m is None:
        return
    body = m.group(1)
    weak_m = re.search(r'"\s*M\s*"\s*:\s*"([^"]+)"', body)
    check("_WEAK['M'] is still 'fading momentum' (out of T-033 scope, pinned)",
          weak_m is not None and weak_m.group(1) == "fading momentum",
          f"got: {weak_m.group(1) if weak_m else 'None'!r}")


# ── 3. S-244 family text guard — source-level regression ───────────────────

def test_narrative_module_no_strong_momentum_outside_weak_dict() -> None:
    """After the rewrite, 'strong momentum' should appear in narrative.py
    ONLY in the docstring / acceptance history comments, never as a
    phrase tied to user-facing output. This is the regression guard — if
    someone reverts the change, this fails loud at preflight."""
    src = _src()
    # Strip block + line comments
    cleaned = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    cleaned = re.sub(r"#[^\n]*", "", cleaned)
    # Now look for "strong momentum" as a phrase — i.e. not just inside
    # a longer identifier or word.
    hits = re.findall(r"\bstrong momentum\b", cleaned)
    check("narrative.py contains no 'strong momentum' phrase after rewrite",
          len(hits) == 0,
          f"found {len(hits)} occurrence(s) in non-comment text")


def test_narrative_module_mentions_t033_marker() -> None:
    """The rewrite should be annotated so the next reader understands the
    reason. T-033 marker + acceptance excerpt (without buy/sell language)
    in the inline comment above the dict."""
    src = _src()
    check("narrative.py cites T-033 in the M-phrase comment",
          "T-033" in src,
          "no T-033 marker — the rewrite is anonymous")


if __name__ == "__main__":
    print("── T-033: 后端 CIS narrative 短语措辞修订 ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print(
        "\n✅ _STRONG['M']='constructive momentum profile';"
        "OUTPERFORM signal phrase 不动;deterministic narrative 不再含 'strong momentum'"
    )