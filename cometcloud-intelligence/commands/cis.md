# /cis — CIS Score Lookup

**Usage:** `/cis [SYMBOL]`

**Examples:**
- `/cis SOL` — get full CIS score for Solana
- `/cis BTC ETH ONDO` — compare multiple assets
- `/cis top10` — get top 10 assets by CIS score
- `/cis` — get the full leaderboard summary

**What it returns:**
For a single asset: full 5-pillar breakdown, grade, signal, LAS, data tier, and positioning narrative.
For multiple assets: side-by-side comparison table.
For `/cis top10`: ranked leaderboard of top 10.
For `/cis` alone: summary of the universe (count, grade distribution, regime).

**API:** `GET https://looloomi.ai/api/v1/cis/universe` (filter by symbol)
Or: `GET https://looloomi.ai/api/v1/cis/top?limit=10`

**Compliance:** All signals use positioning language (OUTPERFORM/NEUTRAL/UNDERPERFORM). Never BUY/SELL.
