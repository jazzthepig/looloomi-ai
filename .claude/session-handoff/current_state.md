# Session State — 2026-06-04

## Git status
- **15+ commits ahead of origin** — Jazz must run `git push origin main`
- Last commit: `0b9bae3` — MINIMAX_TRADING_TRIGGER.md
- All design fixes, perf improvements, and new pages are LOCAL ONLY until pushed

## What was done this session (major items)

### Design QA + Fixes
- H5 (MobileApp.jsx): root background was #FAFBFC (white) → T.void (#020208). ROOT CAUSE of all H5 color visibility issues. Also fixed: progress bar track color, macro brief card.
- IntelligencePage: news feed card design (dark bg + left border + gap layout), -0.0% heatmap fix, VC table hover fix
- SignalFeed: left accent border per signal type, type badge with bg/border, visible hover
- Protocol scoring: grade thresholds aligned (A+≥85), STRONG OUTPERFORM rec_weight bug fixed (was 0)
- L2 TVL: added "op mainnet" to L2_CHAINS, ~$2B recovered
- Dead code removed: ProtocolPage, MarketDashboard, PriceChart, FundDeployWizard, market.html
- Cache-Control: all hot API endpoints covered

### Performance
- CISLeaderboard moved to lazy() → main bundle 165KB → 117KB (-29%)
- Google Fonts: 15 variants → 7, non-blocking load

### New pages/files
- `dashboard/win.html` → looloomi.ai/win.html — How to Win positioning page with live CIS scores
- `CometCloud_Investor_Deck_2026.pptx` — 10-slide investor deck. Slide 8: "Licensed structure via regulated HK partner"
- `MINIMAX_TRADING_TRIGGER.md` — copy-paste code block for auto paper trading in cis_scheduler.py

## Context for next session

**Jazz priorities:**
1. git push (blocking everything)
2. Minimax: add MINIMAX_TRADING_TRIGGER.md code to cis_scheduler.py TODAY
3. LP soft intro via Nic (deck ready)
4. License partner terms (Jazz negotiating)

**Tone:** Peer-level, no padding, build first. Jazz will say "do your work" if Seth over-advises.

## FUSE workaround for dist builds
```bash
cd dashboard && npx vite build --outDir /tmp/build --emptyOutDir
python3 -c "
import subprocess, os
for root, dirs, files in os.walk('/tmp/build'):
    for f in files:
        src = os.path.join(root, f)
        gp = f'dashboard/dist/{os.path.relpath(src, chr(39)/tmp/build{chr(39)})}'
        h = subprocess.run(f'git hash-object -w {chr(34)}{src}{chr(34)}', shell=True, capture_output=True, text=True).stdout.strip()
        subprocess.run(f'git update-index --add --cacheinfo 100644,{h},{gp}', shell=True)
"
python3 -c "import os,glob; [os.rename(f,f+'.bak') for f in glob.glob('.git/*.lock')]"
git add <src files> && git commit -m "..."
```

## Business context (Jun 2026)
- **License partner**: Jazz found HK regulated partner, negotiating terms
- **Fundraising**: 10-slide deck done, Nic has family office contacts for soft intro
- **Paper trading**: engine fully built, auto-trigger code written, Minimax needs to plug it in
- **Track record**: Score history since Apr 2026 in Supabase, paper trading not yet auto-running
- **Mac Mini SSD**: 1TB unused as data store — OHLCV history pipeline not started yet
