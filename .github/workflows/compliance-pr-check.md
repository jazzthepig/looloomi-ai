# Compliance PR Check
*GitHub Agentic Workflow — Phase F, HARNESS_UPGRADE.md*

## Trigger
on: pull_request (all branches)

## Goal

Scan the PR diff for any of the following prohibited transactional signal language
that violates CometCloud's Hong Kong SFC positioning-only compliance rules:

**Forbidden patterns to find:**
- The word `BUY` used as a signal label (not inside comments, documentation strings,
  or test fixtures)
- The phrase `STRONG BUY`
- The words `SELL` or `STRONG SELL` as signal labels
- The word `ACCUMULATE` as a signal label
- The word `AVOID` used as a signal label (exceptions: "avoid using", "avoid the")
- The word `REDUCE` followed by a position/exposure/holding noun
- Chinese forbidden terms: 买入, 卖出, 建仓, 清仓, 减仓, 加仓, 做多, 做空

**Exempt paths (do not flag):**
- `.claude/skills/compliance-language/` — documents the rules
- `CIS_METHODOLOGY.md` — references old terms in "DO NOT USE" context
- `CLAUDE.md`, `HARNESS_UPGRADE.md` — policy documentation
- `.claude/hooks/compliance_check.py` — the hook itself
- `Shadow/` — read-only reference files
- `tests/` or `*.test.*` — test fixtures

## Action

If violations found in non-exempt files:
1. Post a PR review comment listing every violation: file, line number, matched term, context
2. Request changes on the PR
3. Include approved substitution for each violation
4. Reference `.claude/skills/compliance-language/SKILL.md` for full rules

If no violations: post passing status: "Compliance check: no prohibited signal language found."

## Context

CometCloud AI operates under Hong Kong SFC licensing constraints (no Type 4 or Type 9
license active). All user-facing output must use positioning language. Violations in
API responses, frontend, or investor materials expose the company to enforcement action.
The compliance hook at `.claude/hooks/compliance_check.py` enforces this during
development; this workflow enforces it at PR merge time.
