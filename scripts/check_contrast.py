#!/usr/bin/env python3
"""
check_contrast.py — WCAG contrast guard for tokens.js (2026-08-13, design audit).

Reads dashboard/src/tokens.js, extracts every rgba / hex color used in text-token
positions (t1, t2, t3, t4, primary, secondary, muted, dim), and computes the
contrast ratio against the deep-navy base (#030f2a). Fails CI if any text-color
token falls below WCAG AA 4.5:1 — body text legibility is non-negotiable for
institutional LPs (50+ decision-makers, screen-reader audit, regulatory WCAG check).

T.dim (0.20 opacity) is exempted by design — it is decorative-only, never body
text. Run before any token change:

    python3 scripts/check_contrast.py

Exits non-zero if any text token fails. Prints the ratio for every token it
inspects so the operator can decide whether to bump opacity or rename usage.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Deep-navy base from index.css line ~112 / tokens.js (deepest visible surface).
BASE_RGB = (3, 15, 42)         # #030f2a
WCAG_AA_BODY = 4.5             # body text minimum
WCAG_AA_LARGE = 3.0            # large text / UI components minimum

TOKENS_FILE = Path(__file__).resolve().parent.parent / "dashboard" / "src" / "tokens.js"
TEXT_TOKEN_KEYS = {"t1", "t2", "t3", "t4", "primary", "secondary", "muted", "dim"}


def _parse_hex(s: str) -> tuple[int, int, int] | None:
    s = s.strip().strip('"').strip("'")
    if s.startswith("#") and len(s) == 7:
        return int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16)
    return None


def _parse_rgba(s: str) -> tuple[int, int, int] | None:
    s = s.strip().strip('"').strip("'")
    m = re.search(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)", s)
    if not m:
        return None
    r, g, b, a = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
    a = float(a) if a is not None else 1.0
    # alpha-composite against BASE_RGB (text sits on top of the deep field)
    cr = round(r * a + BASE_RGB[0] * (1 - a))
    cg = round(g * a + BASE_RGB[1] * (1 - a))
    cb = round(b * a + BASE_RGB[2] * (1 - a))
    return cr, cg, cb


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def lin(c: float) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    l1, l2 = _relative_luminance(fg), _relative_luminance(bg)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _extract_tokens(text: str) -> dict[str, str]:
    """Find lines like `key: 'value',` in the tokens object literal."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+?)(?://|$)", line)
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip().rstrip(",").strip()
        if key in TEXT_TOKEN_KEYS:
            out[key] = value
    return out


def main() -> int:
    if not TOKENS_FILE.exists():
        print(f"FAIL: tokens.js not found at {TOKENS_FILE}")
        return 1

    text = TOKENS_FILE.read_text(encoding="utf-8")
    tokens = _extract_tokens(text)
    if not tokens:
        print("FAIL: no text tokens extracted (tokens.js format changed?)")
        return 1

    base_lum = _relative_luminance(BASE_RGB)
    print(f"WCAG contrast check — base {BASE_RGB} luminance {base_lum:.4f}")
    print(f"{'token':<12}{'ratio':>8}  {'AA body':<10}{'AA large':<10}{'value':<32}")
    print("-" * 72)

    failures: list[str] = []
    for key in TEXT_TOKEN_KEYS:
        if key not in tokens:
            continue
        raw = tokens[key]
        # 1. parse hex
        hex_rgb = _parse_hex(raw)
        rgba_rgb = _parse_rgba(raw)
        if rgba_rgb is not None:
            rgb = rgba_rgb
        elif hex_rgb is not None:
            rgb = hex_rgb
        else:
            continue
        ratio = _contrast_ratio(rgb, BASE_RGB)
        aa_body = "PASS" if ratio >= WCAG_AA_BODY else "FAIL"
        aa_large = "PASS" if ratio >= WCAG_AA_LARGE else "FAIL"
        # t4 / dim is exempt: decorative only
        is_decorative_only = key in {"t4", "dim"}
        if not is_decorative_only and ratio < WCAG_AA_BODY:
            failures.append(key)
        marker = "  (decorative-only)" if is_decorative_only else ""
        print(f"{key:<12}{ratio:>7.2f}:1  {aa_body:<10}{aa_large:<10}{raw:<32}{marker}")

    print()
    if failures:
        print(f"FAIL: {len(failures)} text token(s) below WCAG AA 4.5:1 body: {failures}")
        print("Either raise the opacity (preferred) or move the usage to T.dim / a new")
        print("decorative-only token. t4/dim is the right token for non-body use.")
        return 1
    print("PASS — every text token meets WCAG AA 4.5:1 for body text")
    print("(t4/dim is exempt: decorative-only, never body text)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
