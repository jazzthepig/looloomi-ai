-- S-481 (2026-10-04, migration s481_book_state_column): the three long/short books persist their full state with every
-- NAV row, so a lost Redis key is recovered from the table instead of re-incepting at NAV 1.0 (scalable 7 resets,
-- combined 7, causal 6 since July). Also answers "did the book hold X that day" with full weights (T-027).
alter table causal_paper_nav  add column if not exists state jsonb;
alter table combined_book_nav add column if not exists state jsonb;
alter table scalable_book_nav add column if not exists state jsonb;
