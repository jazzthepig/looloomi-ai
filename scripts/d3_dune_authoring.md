# D3-DUNE — holder-concentration query authoring (UI walkthrough)

**Status:** Spec ready. API auto-probe confirmed pipe works, but the source table
`tokens_ethereum.balances_daily` is heavy (every probe hit 2-min hard timeout on the API
even with `WHERE day = … AND token_address = …`). The Dune Web UI gives incremental
feedback (column validation as you type, cancel anytime, watch execution progress),
so it is the right place to author the query. **This doc is the handoff — please
author in the UI and pass the resulting `query_id` back to Seth.**

**Why we need this query.** D3 = `cause_proximity` (出圈 risk) — concentration falling +
holder count exploding = mass retail arriving = late-stage / out-of-circle / danger.
Today, `cause_proximity.stage` is `null` on every asset because the holder-stage
computation has no input. This query is the single missing data feed.

**Where the math lives.** `scripts/holder_concentration.py` — concentration primitives
(HHI / top-N / Gini) + `stage_series()` (per-asset, self-referenced diffusion curve).
Once we have per-day `(day, n_holders, hhi, top10)` per token, the rest is local.

---

## Author this in Dune UI

### Step 1 — open new query
- Go to https://dune.com/queries → New → SQL
- Title: **`D3_holder_concentration_template`**
- Set visibility: **Private** (we'll change later if needed)
- Tag: `cometcloud`, `d3`, `holders`

### Step 2 — paste this SQL (verify column names in UI as you type)

```sql
-- params: {{token}} (varbinary, e.g. 0xdAC17F958D2ee523a2206206994597C13D831ec7 for USDT)
-- returns: per-day metrics for ONE token (lightweight; never SELECT *)
WITH b AS (
  SELECT
    day,
    "address"  AS holder,
    balance
  FROM tokens_ethereum.balances_daily
  WHERE token_address = {{token}}
    AND day >= DATE '2024-01-01'
    AND balance > 0
),
t AS (
  SELECT
    day,
    SUM(balance)              AS total_balance,
    COUNT(*)                  AS n_holders
  FROM b
  GROUP BY day
),
top10 AS (
  SELECT
    b.day,
    SUM(b.balance) AS top10_balance
  FROM (
    SELECT
      day,
      balance,
      ROW_NUMBER() OVER (PARTITION BY day ORDER BY balance DESC) AS rn
    FROM b
  ) b
  WHERE b.rn <= 10
  GROUP BY b.day
),
hhi_per_day AS (
  SELECT
    b.day,
    SUM(POWER(b.balance / t.total_balance, 2)) AS hhi
  FROM b
  JOIN t ON b.day = t.day
  GROUP BY b.day
)
SELECT
  t.day,
  t.n_holders,
  ROUND(h.hhi, 6)                                  AS hhi,
  ROUND(t10.top10_balance / t.total_balance, 4)    AS top10
FROM t
JOIN hhi_per_day h  ON t.day = h.day
JOIN top10     t10  ON t.day = t10.day
ORDER BY t.day
```

### Step 3 — column verification (UI as you type)
The UI flags unknown columns. Confirm the column names match the table — specifically:
- `day` (date)
- `"address"` (varbinary — quoted because it's a reserved word in some Trino contexts)
- `balance` (uint256 or similar)
- `token_address` (varbinary — the filter key)

If `"address"` doesn't work, try `holder` or `wallet`. **Whatever the UI accepts, save
and report back — Seth's adapter normalizes via `pd.to_datetime(df["day"])`.**

### Step 4 — set the param
- Add parameter: `token`, type `Address` (Dune v2 has native Address type — it'll accept
  `0xdAC17F958D2ee523a2206206994597C13D831ec7` style inputs).
- Default: `0xdAC17F958D2ee523a2206206994597C13D831ec7` (USDT) — heaviest, so if it
  finishes for USDT it finishes for everything.

### Step 5 — save & run
- **Save first** (Cmd+S / Ctrl+S) — gets the URL → query_id from the URL bar
  (`dune.com/queries/<query_id>/...`).
- Then **Run**. Watch the execution pane. **Expect ~3–8 minutes** for USDT from
  2024-01-01 to today (~500 daily snapshots × 5M+ holders each). This is heavy but
  within Dune's normal range. Cancel and retune only if you see specific errors.

### Step 6 — credit discipline
- **Do NOT** retry on failure without reducing the date range. Discovery calls have
  already cost us ~3 credits (probe queries that timed out). The saved query is the
  first "real" execution.
- If USDT fails on full range, narrow to `day >= DATE '2025-01-01'` (18 months) and
  re-save as `D3_holder_concentration_template_v2`. Smaller tokens will run faster.

---

## Hand off to Seth

Once the query saves and runs once:

1. **Copy the `query_id`** from the URL (the number after `/queries/`).
2. **Paste it here** — Seth needs it for `dune_holder_metrics(query_id, ...)` in
   `scripts/holder_concentration.py` (already wired, just needs the id).
3. **Run a small validation** before pasting: pick ONE token (USDT or a smaller-cap like
   UNI `0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984`), run the query with that param,
   confirm you get back rows with `day, n_holders, hhi, top10` columns. If column names
   differ, note them — Seth's adapter already calls `pd.to_datetime(df["day"])` so the
   day column must be parseable.

---

## What this unblocks

- `cause_proximity.stage` populates for all assets (currently `None`)
- 出圈 alert (`disp_accel > 1.5 AND stage > 0.3`) becomes live
- Risk Meter gets the third axis (cause + quality + fragility)
- Quant backtests can filter "out-of-circle" tokens explicitly

**Token parameter coverage to add later** (out of scope for v1): add a multi-row input
or run one query per token. The first 10–15 assets are what matter; long tail can wait
until we have a use case.