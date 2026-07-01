"""
CometCloud Strategy Research Framework.

Built to enforce STRATEGY_VALIDATION.md gates 1-9 by default. Every strategy
registered with the framework gets:

- Standardised metric suite with statistical inference (gates 2, 5)
- Walk-forward validation with purging + embargo (gates 3, 4)
- Multiple-testing correction (gate 5)
- Per-regime P&L attribution (gate 7)
- OOS holdout discipline (gate 8)
- Decay monitoring (alpha health)
- Standardised markdown report (gates 1-10 checklist)

Out of scope for MVP: live paper trading (gate 9 — needs Mac Mini time),
reviewer sign-off workflow (gate 10 — process tooling).
"""
