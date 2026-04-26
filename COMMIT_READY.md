# COMMIT_READY.md

Push-gate only. Seth stages files from Cowork; Minimax clears lock + commits + pushes.

---

## Current status: CLEAR — 2026-04-26

All pending items from previous sessions have been committed:

| Commit | 内容 | 状态 |
|--------|------|------|
| `05e8198` | `/api/v1/health` + deploy docs update | ✅ pushed |
| `9ff46d6` | MINIMAX_SYNC.md §4 P0 verification + §5 HEAD + §6 | ✅ pushed |
| `223c865` | COMMIT_READY.md push-gate + MINIMAX_SYNC.md §4 | ✅ pushed |
| `2ddbaef` | T2 beta fallback + A base +25 + regime S weight | ✅ pushed |

---

## Minimax outstanding tasks (2026-04-26)

These require action from Mac Mini, not Cowork:

| # | Task | Status |
|---|------|--------|
| T16 | Freqtrade regime-aware threshold | ✅ **Already applied** to `/Volumes/CometCloudAI/freqtrade/.../CometCloudStrategy.py` (confirmed live) |
| T17 | Auth E2E test — `python3 ~/projects/looloomi-ai/scripts/test_auth_e2e.py` | 🟡 Mac Mini run |
| T18 | Supabase wallet_profiles confirm | 🟡 Jazz confirm |
| T10 | LAS fields in local engine output | ✅ Already in Mac Mini `cis_v4_engine.py` (line 828: `"las": self.las`) |
| T11 | Apply T1 strategy + run backtest | 🟡 Mac Mini run |
| T12 | Report backtest PF/WR/MaxDD to Jazz | 🟡 Mac Mini |

---

## How to update this file

When Seth stages files:
1. Replace "Current status: CLEAR" with staged file list and commit message
2. After push, revert to "Current status: CLEAR"

Do not add step-by-step instructions. Push-gate only.