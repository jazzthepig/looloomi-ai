# COMMIT_READY.md

Push-gate only. Seth stages files from Cowork; Minimax clears lock + commits + pushes.

---

## Pending commit (staged, ready to push)

Files staged by Seth — waiting on lock clear:
- `src/data/cis/cis_provider.py` — two fixes:
  1. `calculate_asset_betas` min_len bug: partial yfinance failures (TNX) no longer kill the
     entire beta calc. DXY+VIX now compute independently. T2 assets get real rolling betas
     instead of falling back to the crude CG proxy.
  2. `BINANCE_SYMBOLS` cleanup: removed 12 §4A excluded assets
     (FTM, ICP, BCH, SNX, CRV, SUSHI, PEPE, WIF, BONK, SAND, MANA, AXS)
- `CLAUDE.md` — "BUG" note corrected: S/A low scores are correct Tightening market signal,
  not a bug. Beta fix documented.

```bash
# 1. Clear FUSE lock
rm -f ~/projects/looloomi-ai/.git/index.lock

# 2. Stage COMMIT_READY.md (lock prevented this from Cowork)
cd ~/projects/looloomi-ai
git add COMMIT_READY.md

# 3. Commit
git commit -m "fix(cis): beta calc partial-failure bug + BINANCE_SYMBOLS §4A cleanup

- calculate_asset_betas: TNX/VIX partial yfinance failure no longer kills entire
  beta computation. Each factor now aligns independently (prev: min([0])=1 < 15
  threshold → always returned insufficient_data, forcing CG proxy fallback for all T2)
- BINANCE_SYMBOLS: removed 12 §4A excluded assets (FTM, ICP, BCH, SNX, CRV,
  SUSHI, PEPE, WIF, BONK, SAND, MANA, AXS)
- CLAUDE.md: S/A low scores reclassified — correct Tightening signal, not a bug

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"

# 4. Push
git push origin main
```

---

## Next session open items

**Seth:**
- Phase 2.3: A2A Task endpoint `/api/v1/agent/tasks` (ROADMAP_A2A)
- Verify beta fix improved T2 S scores after next scheduler cycle

**Minimax (MINIMAX_SYNC.md §4 P1):**
- T17: `python scripts/test_auth_e2e.py` — 11 auth tests
- T18: Confirm Supabase `wallet_profiles` table
- T11/T12: Run backtest → report PF/WR/MaxDD
