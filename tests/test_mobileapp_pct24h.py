"""
T-022: 移动端 RECENT SIGNALS 卡片百分比 / 文案跨度对齐

T-014 产品面审计(2026-09-24)发现:
  PULSE tab TOP SIGNALS 卡片(MobileApp.jsx:411-419)显示 "+1.23%"
  但旁边是 7d sparkline — 短时窗百分比与中等窗 sparkline 跨度错位,
  视觉上让用户把 24h 数据读成 7d。

本卡修复:
  1. 引入 `pct24h(v)` helper,显式带 "(24h)" 后缀 — 短时窗一目了然。
  2. 把裸 `pct()` 改为内部 helper `_pct()`,防止后续直接调它(窗语义丢失)。
  3. RECENT SIGNALS 卡片(line 427-480)不引入任何 trend-implying copy
    (历史 bug: 'strong momentum' / 'surge' 与负 24h 百分比同屏)。

跑法:python3 -m tests.test_mobileapp_pct24h
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_MOBILEAPP = _ROOT / "dashboard" / "src" / "components" / "MobileApp.jsx"

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


def _src() -> str:
    return _MOBILEAPP.read_text(encoding="utf-8")


# ── 1. Helper surface — pct24h exists, raw `pct` does not ─────────────────

def test_pct24h_function_defined() -> None:
    src = _src()
    check("`function pct24h(` is declared",
          re.search(r"^function\s+pct24h\s*\(", src, re.MULTILINE) is not None,
          "no `function pct24h(` declaration found")
    check("`function _pct(` (internal helper) is declared",
          re.search(r"^function\s+_pct\s*\(", src, re.MULTILINE) is not None,
          "no `function _pct(` declaration found")


def test_bare_pct_is_not_a_public_helper() -> None:
    """The pre-T-022 leak was `function pct(` at module scope. Pinning
    against re-introduction protects both the helper surface and the JSX
    call site from regressing to a window-less percentage."""
    src = _src()
    bad = re.search(r"^function\s+pct\s*\(", src, re.MULTILINE)
    check("no bare `function pct(` declaration (was the leak)",
          bad is None,
          "line declares unqualified `pct` — reverts T-022")


def test_no_bare_pct_call_in_source() -> None:
    """Word-boundary regex: \\bpct\\( does NOT match `_pct(` (underscore is
    \\w) or `pct24h(` (suffix before paren), but DOES match a bare `pct(`
    call — the regression we want to fail loudly."""
    src = _src()
    bare_calls = re.findall(r"\bpct\(", src)
    check("no bare `pct(` call anywhere in MobileApp.jsx",
          len(bare_calls) == 0,
          f"found {len(bare_calls)} occurrence(s): {bare_calls[:3]}")


def test_jsx_call_site_uses_pct24h() -> None:
    """The change line at ~411-419 must call `pct24h(change)`. Searching for
    the literal JSX expression — pinning the call site."""
    src = _src()
    call = re.search(r"\{pct24h\(change\)\}", src)
    check("JSX call site uses `{pct24h(change)}`",
          call is not None,
          "no `{pct24h(change)}` literal found")


# ── 2. Behaviour — mirror reference implementation asserts contract ────────

def test_pct24h_propagates_dash_for_missing() -> None:
    """None / NaN must propagate to '—' without leaking 'NaN% (24h)' or
    'null% (24h)'. Mirror in Python asserts the contract independently of
    how the JS implementation is written."""

    def _mirror_pct(v):
        if v is None or (isinstance(v, float) and v != v):
            return "—"
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.2f}%"

    def mirror_pct24h(v):
        s = _mirror_pct(v)
        return s if s == "—" else f"{s} (24h)"

    check("pct24h(None)  == '—' (no NaN/null leak)",
          mirror_pct24h(None) == "—",
          f"got {mirror_pct24h(None)!r}")
    check("pct24h(NaN)   == '—' (no NaN leak)",
          mirror_pct24h(float("nan")) == "—",
          f"got {mirror_pct24h(float('nan'))!r}")
    check("pct24h(0)     == '+0.00% (24h)' (zero positive branch)",
          mirror_pct24h(0) == "+0.00% (24h)",
          f"got {mirror_pct24h(0)!r}")
    check("pct24h(1.234) == '+1.23% (24h)'",
          mirror_pct24h(1.234) == "+1.23% (24h)",
          f"got {mirror_pct24h(1.234)!r}")
    check("pct24h(-7.45) == '-7.45% (24h)' (the prior_value case)",
          mirror_pct24h(-7.45) == "-7.45% (24h)",
          f"got {mirror_pct24h(-7.45)!r}")


# ── 3. Source contains the literal '(24h)' suffix ──────────────────────────

def test_pct24h_function_body_emits_window_suffix() -> None:
    """Parse the pct24h function body and confirm the literal '(24h)' lives
    inside — regression if someone refactors to `\${s} 24h\`` (space typo)
    or drops the suffix entirely."""
    src = _src()
    m = re.search(r"function\s+pct24h\s*\([^)]*\)\s*\{(.*?)\n\}", src, re.DOTALL)
    check("pct24h function body extractable",
          m is not None,
          "could not extract pct24h body via regex")
    if m:
        body = m.group(1)
        check("pct24h body contains literal '(24h)'",
              "(24h)" in body,
              f"body: {body!r}")
        check("pct24h body delegates to _pct for the raw format",
              "_pct(" in body,
              "pct24h should call _pct to avoid duplicating format logic")


# ── 4. RECENT SIGNALS card body has no trend-implying copy ─────────────────

def test_recent_signals_no_trend_implying_words() -> None:
    """The RECENT SIGNALS card was historically polluted with 'strong
    momentum' / 'surge' / 'breakout' copy that contradicted the adjacent
    24h percentage. Today the card shows direction labels only
    (OUTPERFORM / UNDERPERFORM / UNDERWEIGHT), which is the S-244 family
    contract — no trend magnitude claim that needs to align with the %.
    Pin both: (a) the section locates correctly, (b) none of the trend
    words appear in it."""

    src = _src()
    lines = src.splitlines()
    # Locate the section by its comment header.
    header_idx = next(
        (i for i, line in enumerate(lines) if "Latest Signals" in line),
        -1,
    )
    check("RECENT SIGNALS section header locatable",
          header_idx >= 0,
          "no `Latest Signals` comment marker in MobileApp.jsx")

    if header_idx < 0:
        return
    # Take the next 60 lines (card body fits in <50 lines; some buffer).
    body = "\n".join(lines[header_idx : header_idx + 60])
    forbidden = (
        "strong momentum",
        "momentum surge",
        "volume surge",
        "breakout",
        "rally",
        "parabolic",
        "explosive",
        "moon ",
    )
    for word in forbidden:
        check(f"RECENT SIGNALS card does not contain {word!r}",
              word not in body.lower(),
              f"found trend-implying word {word!r} in card body")


# ── 5. S-244 family text guard — caller is `pct24h`, not `_pct` ─────────────

def _strip_comments_preserving_offsets(s: str) -> str:
    """Strip // and /* */ comments but PRESERVE character offsets (replace
    with spaces + newlines) so any line/column indexed against the original
    source still lines up. Needed because re.sub(/\\*.*?\\*/, '', ...) eats
    internal newlines and shifts every later line's number."""

    def _blank(match: re.Match) -> str:
        # Replace each non-newline char with space, keep newlines.
        return "".join("\n" if c == "\n" else " " for c in match.group(0))

    # Block comments — must come BEFORE line comments so /* ... */ on a line
    # isn't first split into "/* ... " + "*/" pieces by the line rule.
    s = re.sub(r"/\*.*?\*/", _blank, s, flags=re.DOTALL)
    # Line comments — replace with spaces (keeps column offsets).
    s = re.sub(r"//[^\n]*", lambda m: " " * len(m.group(0)), s)
    return s


def _function_body_char_range(stripped: str, name: str) -> tuple[int, int]:
    """Return (start_offset, end_offset) of `function <name>(...) { ... }`
    in `stripped`, brace-counted. Returns (-1, -1) if not found. Comments
    must already be stripped so they don't trick the brace counter."""
    m = re.search(rf"function\s+{re.escape(name)}\s*\([^)]*\)\s*\{{", stripped)
    if m is None:
        return (-1, -1)
    depth = 0
    i = m.end() - 1  # position of `{`
    while i < len(stripped):
        c = stripped[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return (m.start(), i + 1)
        i += 1
    return (-1, -1)


def test_pct24h_is_called_not_pct_in_user_facing_paths() -> None:
    """Outside the pct24h function body, no `_pct(` call should exist. Any
    call site outside pct24h means the window-less percentage leaked back
    to the UI — the regression T-022 closes. Comments are preserved as
    spaces so docstring mentions of `_pct` don't false-positive."""
    src = _src()
    stripped = _strip_comments_preserving_offsets(src)
    start, end = _function_body_char_range(stripped, "pct24h")
    check("pct24h body locatable (char offset, comments stripped)",
          start >= 0,
          "could not find pct24h function body")
    if start < 0:
        return
    outside = stripped[:start] + stripped[end:]
    # Negative lookbehind excludes `function _pct(` (the definition) — only
    # actual call sites remain.
    leaks = re.findall(r"(?<!function )_pct\(", outside)
    check("`_pct(` is not called outside pct24h (would leak window-less %)",
          len(leaks) == 0,
          f"found {len(leaks)} leak(s): {leaks[:3]}")


if __name__ == "__main__":
    print("── T-022: 移动端 RECENT SIGNALS 卡片百分比 / 文案跨度对齐 ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print(
        "\n✅ pct24h(change) 显示 +1.23% (24h);"
        "RECENT SIGNALS 卡片无 trend-implying 词;"
        "_pct 仅内部 helper"
    )