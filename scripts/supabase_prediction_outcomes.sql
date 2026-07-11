-- prediction_outcomes — one row per resolved prediction, ANY source (the read-back that
-- turns write-only logs into measured track records). Written by
-- src/data/signals/prediction_resolver.py. See LOOP_ENGINEERING.md.

create table if not exists prediction_outcomes (
    id                  bigserial primary key,
    source              text not null,        -- signal | positioning | forward_supply | conviction | narrative
    ref_id              text,                 -- row id in the source table
    symbol              text not null,
    predicted_at        date not null,
    horizon_days        integer not null default 30,
    direction           integer not null,     -- +1 outperform / -1 underperform
    realized_return_pct double precision,
    alpha_pct           double precision,     -- benchmark-relative (BTC/SPY)
    hit                 boolean,              -- null = flat band (no hit/miss)
    resolved_at         timestamptz not null default now(),
    unique (source, ref_id, horizon_days)
);

create index if not exists idx_pred_out_source on prediction_outcomes (source);
create index if not exists idx_pred_out_symbol on prediction_outcomes (symbol);

-- The value-mining read-back: is each source actually predictive?
--   select source, count(*) filter (where hit) ::float / nullif(count(*) filter (where hit is not null),0) as hit_rate,
--          avg(alpha_pct * direction) as avg_directional_alpha, count(*) as n
--   from prediction_outcomes group by source order by hit_rate desc nulls last;
