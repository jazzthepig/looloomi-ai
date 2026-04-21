# Weekly CIS Audit
*GitHub Agentic Workflow — Phase F, HARNESS_UPGRADE.md*

## Trigger
on: schedule: cron: '0 8 * * 1'  (Every Monday 8:00 UTC)

## Goal

Pull the last 7 days of CIS scores from Supabase and run a quality audit. Detect:
1. Assets that dropped below D grade (score < 25) unexpectedly
2. Assets with unusually high grade volatility (>2 grade steps in 7 days)
3. Assets where T1 (Mac Mini) and T2 (Railway) scores diverge by >15 points
4. Any compliance violations in stored signal labels
5. Scoring coverage: total assets scored, data tier breakdown (T1 vs T2)

## Steps

1. Query Supabase `cis_scores` table:
   ```sql
   SELECT symbol, cis_score, raw_cis_score, grade, signal, data_tier, created_at
   FROM cis_scores
   WHERE created_at > NOW() - INTERVAL '7 days'
   ORDER BY symbol, created_at ASC
   ```

2. For each asset, compute:
   - Grade trajectory (ordered by timestamp): list of grade labels over the week
   - Max grade drop: from highest grade to lowest grade in the period
   - T1/T2 divergence: max(|T1_score - T2_score|) across shared assets

3. Flag anomalies:
   - Any asset scoring below D (< 25) in 3+ consecutive readings
   - Any asset with grade drop > 2 steps (e.g., A → C or B+ → D)
   - Any T1/T2 divergence > 15 points
   - Any signal field containing: BUY, SELL, HOLD, AVOID, ACCUMULATE, REDUCE

4. Compute coverage report:
   - Total unique assets scored this week
   - T1 asset count vs T2 asset count
   - Asset classes represented
   - Scoring frequency (pushes per day, average)

## Reporting

If anomalies found:
1. Open a GitHub issue: "Weekly CIS Audit — [date] — [N anomalies found]"
2. Label: `cis-audit`, `priority: medium`
3. Issue body: full anomaly list with asset names, scores, dates, and recommended actions

If no anomalies:
- Post a commit comment on the latest main commit: "Weekly CIS audit: no anomalies. Coverage: [N] assets, [T1]/[T2] split."

## Context

This audit is the early-warning system for CIS scoring quality. Unexpected grade
drops can indicate data source failures (CoinGecko, DeFiLlama, yfinance), scoring
engine bugs, or genuine market events that warrant Minimax investigation. T1/T2
divergence > 15 points means the Mac Mini and Railway engines are disagreeing
materially — either the local engine has a bug or Railway's fallback is miscalibrated.

The `cis_scores` table only populates once `SUPABASE_URL` and `SUPABASE_KEY` are
set in Railway env vars. Until those are set, this workflow will report zero data
and should be noted as blocked.

See `.claude/agents/cis-validator.md` for the agent that runs manual CIS validation.
