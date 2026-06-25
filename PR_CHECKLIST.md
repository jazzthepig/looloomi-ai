# PR CHECKLIST — 2026-06-25 (repo cleanup after multi-agent / harness / M2.5→M3 churn)

main is branch-protected (PR + `smoke` CI green required). Commit in small, clean PRs.
**Do NOT `git add .`** — the working tree is full of agent/harness noise. Use the explicit
lists below. `.gitignore` was updated 2026-06-25 to stop most noise going forward.

## Step 0 — delete junk (safe, accidental files)
```bash
rm -f "=0.1.49" "=0.2.0"               # pip mis-install artifacts (>=x.y.z typo)
rm -f src/data/cis/cis_history.db-journal
# (health-check-*.md, *.bak, monitor-logs/, meditations/ etc. are now gitignored — leave or delete)
```

## PR-1 · CoinGecko deep-history backfill (backend)
```
src/data/market/data_layer.py     # get_cg_market_chart_range +interval arg
src/api/routers/ohlcv.py          # _fetch_cg_daily forces interval="daily"
src/api/routers/admin.py          # /internal/ohlcv-collect background for days>800
```
After deploy: `curl -X POST ".../internal/ohlcv-collect?days=4000" -H "X-Internal-Token: $TOK"`.

## PR-2 · Methodology + standards (new docs)
```
METHODOLOGY_CORE.md
DATA_CAPTURE_SPEC.md
STRATEGY_VALIDATION.md            # S3 deliverable (verify contents before commit)
_prompts/                         # reusable consolidate-memory prompt
```
NOT committed (intentional): `MINIMAX_SYNC.md` + `MINIMAX_SYNC_ARCHIVE_*.md` — gitignored
internal coordination docs, stay local.

## PR-3 · Research scripts + REAL harness automation (verified 2026-06-25)
```
scripts/backtest_cis.py
scripts/backtest_strategies.py
scripts/smoke_test.py                       # if not already on main
scripts/compliance_scan.py                  # CI compliance scanner (reuses hook patterns)
scripts/post_deploy_check.py                # external uptime/deploy watchdog (stdlib)
.github/workflows/ci-smoke.yml              # import+boot gate (hard) — if not already on main
.github/workflows/compliance-check.yml      # forbidden-language gate (ADVISORY for now)
.github/workflows/post-deploy-verify.yml    # external watchdog: push + every 30min
.github/workflows/weekly-cis-audit.yml      # weekly health + landing summary
```
**Verified locally:** compliance_scan flags STRONG BUY/BUY (exit 1), passes STRONG OUTPERFORM
(exit 0). post_deploy_check reaches live build-state (after UA fix), exit 0 healthy / exit 1
on unreachable or sha-mismatch. (GitHub Actions runs are the final verification.)

**Harness follow-ups (do with this PR):**
- **Delete the 3 fake workflows** (docs that never ran, now superseded):
  `rm .github/workflows/{compliance-pr-check,post-deploy-verify,weekly-cis-audit}.md`
- **Optional Telegram alerts:** add repo secrets `TELEGRAM_BOT_TOKEN` + `TELEGRAM_ALERT_CHAT_ID`
  (without them, GitHub emails the owner on watchdog failure — still works).
- **Compliance: flip to blocking after triage** — ~83 pre-existing hits (mostly comments /
  MCP tool descriptions). Triage, then remove `|| true` + set `COMPLIANCE_BLOCK=1`.
- **Glance:** live build-state shows `route_count=39` (was 147 earlier) — confirm no routers
  silently dropped.

## PR-4 · Frontend Diagnose (if still outstanding)
```
dashboard/src/components/DiagnoseHome.jsx
dashboard/src/App.jsx
dashboard/dist/                   # rebuild before committing: cd dashboard && npm run build
```

## ⚠️ CONFIRM before committing (unknown provenance — multi-agent residue)
- `elizaos-plugin/` — who added it? An ElizaOS agent plugin. Keep / move / drop?
- `config_ls_futures.json` — long-short futures config? whose?
- `dashboard/src/components/{PortfolioDiagnosis,MarketDashboard,PriceChart,ProtocolPage,FundDeployWizard,EstAlphaSection}.jsx`,
  `dashboard/market.html`, `dashboard/src/market.jsx` — these show as **untracked**, i.e.
  never committed or de-tracked. Some are known dead code (ProtocolPage/MarketDashboard/
  PriceChart/FundDeployWizard were removed earlier). **Verify nothing live imports them**,
  then delete the dead ones rather than commit.

## .gitignore additions applied (2026-06-25)
health-check-*.md · HEALTH_CHECK*.md · health-reports/ · health-checks/ · monitor-logs/ ·
meditations/ · macro_brief_latest.json · PRD*.md · *.bak(.*) · MINIMAX_SYNC_ARCHIVE_*.md ·
*.db-journal · .claude/settings.local.json · `=*` (pip artifacts)

## Landing health snapshot (2026-06-25, for reference)
cis_scores ✅ fresh (06-25) · railway_snapshot ✅ (754) · macro_briefs ✅ fresh ·
ohlcv_daily 🟡 stale 06-21 (deep backfill PR-1 fixes) · signal_journal 🟡 06-19 ·
cis_backtest_results 🔴 0 (Minimax S1) · trade_results 🔴 0 (Minimax paper trading).

## §PURGE — dead code (audit 2026-06-25; run by Jazz, deletions are irreversible)

**Delete (confirmed dead, no live import/dependency):**
```bash
cd ~/Projects/looloomi-ai
rm -rf elizaos-plugin                          # 357MB, April crunch, untracked, no deps
# 7 true orphan components (imported NOWHERE in dashboard/src):
rm -f dashboard/src/components/AssetTable.jsx \
      dashboard/src/components/FundDeployWizard.jsx \
      dashboard/src/components/MMIGauge.jsx \
      dashboard/src/components/MarketDashboard.jsx \
      dashboard/src/components/PriceChart.jsx \
      dashboard/src/components/ProtocolPage.jsx \
      dashboard/src/components/PortfolioDiagnosis.jsx   # replaced by DiagnoseHome this session
rm -f dashboard/market.html dashboard/src/market.jsx   # verify no vite multi-entry ref first
```
Before deleting the dashboard files: `grep -rn "market.jsx\|market.html" dashboard/vite.config* dashboard/*.html` to confirm no build entry points at them.

**KEEP:** all 33 freqtrade strategies (Jazz). Backend routers — keep all; `social` serves
crawlers/ShareCard (legit). `onchain` / `discovery` / `factors` have no frontend consumer but
are **dormant scaffolding to REVIVE for the methodology data work** (on-chain holder/flow,
factor registry) — do NOT delete.

**Fake automation (CLAUDE.md corrected 2026-06-25):** `.github/workflows/compliance-pr-check.md`,
`post-deploy-verify.md`, `weekly-cis-audit.md` are docs, never ran. Either convert to real
`.yml` or delete; only `ci-smoke.yml` is live.
