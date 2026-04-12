# Compliance Audit Checklist

Grep patterns and file globs to scan CometCloud code for forbidden
transactional language. Use before shipping, during code review, and as the
basis for the future PreToolUse hook (Phase B).

## File globs to scan

User-facing surfaces (always scan):
```
src/api/routers/**/*.py
dashboard/src/**/*.{jsx,js,ts,tsx}
dashboard/public/strategy.html
dashboard/public/vision.html
dashboard/public/index.html
*.md  (excluding CLAUDE.md itself which documents the rules)
```

Internal (relaxed, but still check for leakage into responses):
```
Shadow/cometcloud-local/**/*.py   (read-only reference)
scripts/**/*.py
src/data/**/*.py
```

Do NOT scan:
```
node_modules/
dashboard/dist/
.git/
Shadow/freqtrade/user_data/logs/
```

## Regex patterns — hard blockers

Case-insensitive, word-boundary matching. Any match in a user-facing file is
a blocker.

```
\b(strong\s+)?buy\b
\b(strong\s+)?sell\b
\baccumulate\b
\bavoid\b(?!\s+(using|the\s+word))
\breduce\s+(position|exposure|holding)
\btrim\b
\bcut\b(?!\s+off)
\bdump\b
\bliquidate\b
\bexit\s+(position|trade)
\bgo\s+long\b
\bgo\s+short\b
\bshort\s+this\b
\bload\s+up\b
\bstop\s+out\b
\btarget\s+price
\bprice\s+target
```

Chinese:
```
买入|賣出|卖出|建仓|建倉|清仓|清倉|减仓|減倉|加仓|加倉|做多|做空
```

## Regex patterns — soft warnings

Require human judgment. Flag for review; do not auto-block.

```
\bhold\b              # OK in prose, NOT as a signal label
\brecommend(ed|s)?\b  # OK if object is docs/reading, NOT if object is trading
\bshould\s+(buy|sell|hold|accumulate)
\btop\s+pick
\bgeneration(al)?\s+(buy|opportunity)
\bcan('?t| not)\s+miss
\balpha\s+opportunity
```

## Quick grep command

```bash
# Run from repo root — fast scan of user-facing surfaces
rg -i --type py --type js --type jsx --type ts --type tsx --type md \
  -g '!node_modules' -g '!dashboard/dist' -g '!Shadow/' -g '!CLAUDE.md' \
  -e '\b(strong\s+)?(buy|sell)\b' \
  -e '\b(accumulate|liquidate|dump|trim|avoid)\b' \
  -e '\b(target\s+price|price\s+target)\b' \
  -e '买入|卖出|建仓|清仓|做多|做空'
```

## Review workflow

1. Run the grep above on every PR touching `src/api/`, `dashboard/src/`, or
   any `.md` file.
2. Each match → determine if user-facing.
3. User-facing match → block PR, rewrite using `substitution_table.md`.
4. Internal-only match → note in PR description, let it through.
5. After Phase B hooks land, this becomes automated at tool-call time.

## Known-safe exceptions (whitelist)

- `CLAUDE.md` — documents the rules, must reference forbidden terms
- `.claude/skills/compliance-language/**` — this skill itself
- `CIS_METHODOLOGY.md` — may mention forbidden terms in "DO NOT USE" context
- Test fixtures in `tests/fixtures/compliance_cases.json` — exists to test detection
- `Shadow/freqtrade/**` — Freqtrade internals; never rendered in UI
