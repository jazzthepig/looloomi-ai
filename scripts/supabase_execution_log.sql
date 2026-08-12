-- execution_intents / execution_outcomes — what we actually pay to trade (S-155)
--
-- WHY. Every backtest in this repo has guessed the number that decides the
-- sleeve. R66-C assumed 10bps round-trip and its cost ladder showed break-even
-- at 150bps, which reads as 15x headroom -- but that ladder priced FEES, and
-- fees are not the cost:
--
--     the entire Binance VIP ladder, VIP0 -> VIP9    ~3.3 bps
--     maker vs taker fee at VIP0                     ~3   bps
--     crossing a $1-2M ADV alt perp spread           25-50 bps
--
-- At ~28 rebalances/yr the model is (bps/1e4)*2*2 per rebalance, so 50bps of
-- spread is 56%/yr against a realised ~96%/yr. The $10k account starting
-- 2026-08-17 is not there to make money; it is there to measure this.
--
-- TWO TABLES, NOT ONE, AND THAT IS THE POINT. Posted orders fill through
-- ADVERSE SELECTION: you get filled when the market comes to you, i.e. when it
-- is moving against you. A single `fills` table therefore measures execution as
-- excellent and deletes the tracking error -- the survivorship problem moved to
-- the execution layer, and easier to commit here than anywhere else, because an
-- unfilled order leaves no trace in the account, the P&L, or the exchange
-- statement. Nothing but this log will ever notice it is missing.
--
-- So an INTENT is written when the signal fires, before an order exists, and is
-- resolved exactly once -- to a fill OR to an expiry. `execution_unresolved`
-- below makes the gap between them visible instead of inferable.

create table if not exists execution_intents (
    intent_id            text primary key,
    ts_decision          timestamptz not null,
    symbol               text        not null,
    side                 text        not null check (side in ('buy','sell')),
    target_notional_usd  double precision not null,
    -- The anchor for every downstream number. Captured at DECISION time, not at
    -- placement: the decision->placement delay is a real cost a systematic book
    -- controls, and anchoring on arrival price hides exactly that part.
    decision_mid         double precision not null,
    decision_bid         double precision,
    decision_ask         double precision,
    sleeve               text,
    signal_ref           text,
    order_type           text,        -- what we INTENDED (maker/taker)
    limit_price          double precision,
    recorded_at          timestamptz not null default now()
);

create index if not exists idx_exec_intents_sleeve_ts
    on execution_intents (sleeve, ts_decision desc);

create table if not exists execution_outcomes (
    intent_id            text primary key references execution_intents(intent_id),
    ts_resolved          timestamptz not null,
    -- EXPIRED with filled_notional 0 is a first-class result and MUST be
    -- written. It is the expensive outcome and the one with no other witness.
    status               text not null check (status in ('filled','partial','expired','cancelled')),
    filled_notional_usd  double precision not null default 0,
    avg_fill_price       double precision,
    fee_usd              double precision not null default 0,
    liquidity            text,        -- maker|taker as REPORTED by the venue,
                                      -- never as intended: the difference is the
                                      -- measurement
    seconds_to_resolve   double precision,
    mid_at_resolve       double precision,   -- prices the cost of NOT filling
    note                 text,
    recorded_at          timestamptz not null default now()
);

-- The gap made visible. An intent with no outcome is an unresolved order, and
-- unresolved orders are how a fills-only bias creeps back in by omission rather
-- than by design.
create or replace view execution_unresolved as
select i.*, now() - i.ts_decision as age
from execution_intents i
left join execution_outcomes o using (intent_id)
where o.intent_id is null;

alter table execution_intents  enable row level security;
alter table execution_outcomes enable row level security;

drop policy if exists exec_intents_service_only on execution_intents;
create policy exec_intents_service_only on execution_intents
    for all to service_role using (true) with check (true);
drop policy if exists exec_outcomes_service_only on execution_outcomes;
create policy exec_outcomes_service_only on execution_outcomes
    for all to service_role using (true) with check (true);

comment on table execution_intents is
 'One row per signal-driven trading decision, written BEFORE the order exists. '
 'Resolved exactly once in execution_outcomes. The pair prices implementation '
 'shortfall against the decision mid, decomposed into spread, fees and the '
 'opportunity cost of not filling -- three costs with three different fixes.';

comment on column execution_outcomes.status is
 'A 100% fill rate on passive orders is not excellent execution; it is the '
 'signature of unlogged expiries. Nothing can verify from inside that the '
 'misses were written, so the aggregate reports fill_rate prominently instead.';
