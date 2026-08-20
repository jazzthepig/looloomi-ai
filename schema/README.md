# schema/ — a checked-in snapshot of the live Postgres column list

**Why this exists (S-185, 2026-08-20).** `supabase_fresh_t1_symbols` filtered
`cis_scores` on `created_at`. That column does not exist — the timestamp is
`recorded_at`. PostgREST answers 400, the helper mapped that to `None`
("could not ask"), and the fail-closed writer treated `None` as "do not write".
Every layer behaved exactly as designed and the hourly T2 snapshot silently
stopped writing. A fail-closed guard converts a typo into an outage that
produces no error anywhere.

**Why not validate against `scripts/*.sql`.** Tried first; it produced three
false positives and zero true ones. The `.sql` files have drifted from the
database — `asset_embeddings.superseded_reason` and `beta_core_nav.exposure_cap`
both exist live and appear in no CREATE TABLE. Validating against a stale
definition is worse than not validating: it flags correct code, and a guard
that flags correct code gets switched off by whoever hits it next.

**Refreshing.** This snapshot is the authority for `tests/test_postgrest_columns_exist.py`.
When a migration adds a column, regenerate:

```sql
SELECT json_object_agg(table_name, cols) FROM (
  SELECT table_name, json_agg(column_name ORDER BY ordinal_position) AS cols
  FROM information_schema.columns WHERE table_schema='public'
  GROUP BY table_name) t;
```

Staleness here fails safe in the one direction that matters: a NEW column not
yet in the snapshot makes the test complain about correct code, which is loud.
The dangerous direction — a column that never existed — cannot be introduced by
staleness.
