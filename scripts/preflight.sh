#!/usr/bin/env bash
# Preflight — the MANDATORY pre-push gate. The app must IMPORT and BOOT, not just
# compile. `py_compile` only checks syntax; it MISSES import-time NameErrors (e.g. a
# name used in a function annotation that isn't imported) — exactly the class that
# 502'd production on 2026-07-13 (`Response` unimported in main.py, py_compile passed).
#
# Run this before EVERY push. It is the same check CI runs, but locally, before the
# broken commit ever reaches Railway (which auto-deploys on push regardless of CI).
#
#   bash scripts/preflight.sh   &&   git push origin main
set -euo pipefail

# ── S-280:每次运行先报解释器。**「通过」必须带上它在哪通过的。** ──────────
# 2026-09-02:test_deep_walk 用 asyncio.get_event_loop(),在沙箱的 3.10 上通过、
# 在 Mac 的 3.14.3 上 RuntimeError。我报了「PREFLIGHT PASSED」而那句话没有声明
# 适用环境 —— 与「一个不带窗口的分位数」是同一种东西(S-274)。
echo "  · preflight 运行于 $(python3 -V 2>&1) @ $(uname -s)-$(uname -m)"
cd "$(dirname "$0")/.."

# The boot probe must not run the app's daily work (S-161). Booting the app fires
# 30 background loops into Moralis, CoinGecko Pro, Binance and the paper books —
# instant with no network egress, a full daily cycle on a laptop with internet,
# which is why preflight stalled with [HEARTBEAT] as its last line. Suppression
# lives in scripts/smoke_test.py and filters by coroutine name: the 30 *_loop
# tasks are skipped, the MCP session manager (_run) is not, because the startup
# path awaits it and skipping it deadlocks the boot. src/api/main.py is untouched.
# ── THE GATE RUNS WITHOUT PRODUCTION CREDENTIALS (S-163, 2026-08-13) ─────────
#
# Jazz asked: "他们一定需要在吗? Railway 有了不就可以了吗?" — and the question
# inverted the diagnosis. The night's story had been "Seth's sandbox lacks
# credentials, so his green is unrepresentative". Measured, the causality runs
# the other way:
#
#   .env has SUPABASE_KEY empty  → every loop fails on its first DB call → 48s
#   a machine that HAS the key   → loops connect, proceed to Moralis /
#                                  CoinGecko / Binance → full daily cycle → hang
#
# **Having the credentials is what made the gate slow and machine-dependent.**
# Lacking them was not a deficiency, it was the correct state for a gate.
#
# Measured with every production credential stripped: exit 0, 49s, ZERO outbound
# HTTP requests, and no test file reads SUPABASE_KEY from the environment. The
# suites check code — imports, invariants, AST, pure functions. Nothing here
# needs a live database, and anything that did would be testing the deployment,
# not the change.
#
# So the gate now strips them itself. Same result on every machine, whatever is
# in .env or exported in the shell. Deployment verification belongs AFTER the
# push, against the deployed URL — that is a different question with a different
# instrument.
#
# ⚠ THE HAZARD THIS INTRODUCES, stated so it is not discovered later: a suite
# that silently no-ops without credentials would now pass vacuously. That is the
# same shape as a column displayed and never written. If a check ever genuinely
# needs a live backend, it does not belong in preflight — it belongs in the
# post-deploy verifier, where its absence is visible.
_PF_STRIP_CREDS=(SUPABASE_KEY SUPABASE_SERVICE_KEY UPSTASH_REDIS_REST_URL
                 UPSTASH_REDIS_REST_TOKEN TELEGRAM_BOT_TOKEN TELEGRAM_ALERT_CHAT_ID
                 GITHUB_TOKEN MORALIS_API_KEY COINGECKO_API_KEY ETHERSCAN_API_KEY
                 HELIUS_API_KEY)
for _v in "${_PF_STRIP_CREDS[@]}"; do unset "$_v"; done
echo "  ⓘ gate runs credential-free (${#_PF_STRIP_CREDS[@]} production vars stripped)"

export DISABLE_BACKGROUND_LOOPS=1

echo "→ [0/3] test-runner dependencies ..."
# `set -e` means the FIRST failure aborts, so a missing dependency midway through
# silently skips every check after it. On 2026-08-09 test_venue_consolidation (one of
# 3 files using pytest while the other 20 are stdlib self-runners) aborted the run and
# 5 suites plus the contract echo never executed — with no indication that they had
# not run. Fail here, loudly, with the remedy, instead of there, ambiguously.
python3 -c "import pytest" 2>/dev/null || {
  echo "  ✗ pytest missing — tests/{conftest,test_cis,test_factory,test_venue_consolidation}.py need it"
  echo "    fix: pip3 install pytest --break-system-packages"
  exit 1
}
echo "  ✓ pytest present"

echo "→ [1/2] byte-compile all src ..."
python3 -m py_compile $(git ls-files 'src/**/*.py') && echo "  ✓ syntax OK"

echo "→ [2/3] import + boot smoke (the real gate py_compile can't do) ..."
INTERNAL_TOKEN=preflight ENVIRONMENT=ci python3 scripts/smoke_test.py

echo "→ [3/3] discipline + schema-drift guard (philosophy compiled to CI, 2026-07-27) ..."
# 3a. strategy discipline — cause/OOS/paper/regime evidence floor on every SHIP record
python3 -m tests.test_the_boot_probe_does_not_run_the_app
python3 -m tests.test_strategy_discipline
# 3a.1 — lag-discipline regression guard (M-114, 2026-08-31). M-95c book Sharpe +8.2
#         was a same-bar look-ahead (`m95c_book_assembly.py:134-147` selected on p[d]
#         then earned day d). M-112 found that 13 rounds (M-95c..M-111) shipped with
#         the leak because every diagnostic (DSR / walk-forward / stress / cost models)
#         accepts a leaked book. M-114 codifies the right test: a sleeve whose Sharpe
#         decays >50% when shifted from lag-0 to lag-1 fails automatically. Synthetic
#         data, sandbox-safe, no DB / network / secrets. Gold-standard test asserts the
#         guard catches the M-95c retention 0.072 (well below 0.5 floor).
python3 -m src.research.validation.tests.test_m114_lag_discipline_smoke || {
  echo "  ✗ M-114 lag-discipline guard FAILED — do not push"; exit 1; }
echo "  ✓ M-114 lag-discipline regression guard"
# 3a-bis. resilience — the 2026-07-29 P0 (Supabase saturation → 33s hangs → retry storm,
#         while /health lied "healthy"). Guards: no retry on timeout, breaker opens, fails
#         fast, RECOVERS after cooldown, 4xx doesn't trip it, health reflects reality.
python3 -m tests.test_supabase_breaker
python3 -m tests.test_cis_universe_lock
# 3a-bis-2. T2 fan-out bounds (2026-08-07, S-104). The lock test above bounds the
#           CALLER; this bounds the CALLEE. `/cis/universe` returned 200 for 56 min
#           while serving a payload frozen at 01:03 — the build never completed
#           because one 24h-cadence decoration branch (cg_dev: 25 coins, sem 4,
#           15s each) overran the budget and cancelled the nine branches that had
#           already succeeded. Guards: per-branch timeout, degradation reported not
#           swallowed, failures negative-cached so a down provider costs once.
python3 -m tests.test_t2_fanout_bounds
# 3a-ter. cold-start contract — the amnesia path (docs/AMNESIA_PROTOCOL.md). Every agent starts
#         every session at zero; a lesson that lives only in a 5,672-line ledger changes nothing.
python3 -m tests.test_cold_start_contract
# 3a-quater. undefined names on the serving path — a NameError on a rarely-taken branch is
#            invisible to py_compile AND to production when the caller logs a warning. That
#            combination silently killed the T2 universe fallback (2026-08-06).
python3 -m tests.test_no_undefined_names
# 3a-quinquies. neutralisation (2026-08-07, S-103). `neutralize()` was cited in 71
#               files and defined in none, so no claim of alpha had ever been
#               separated from exposure. Guards both directions: pure beta must
#               neutralise to zero, and real alpha must survive — a neutraliser
#               that strips everything would refute every strategy including a
#               working one.
python3 -m tests.test_neutralize
# 3a-sexies. strategy-library durability (2026-08-07, S-105). The record library —
#            the graveyard CLAUDE.md calls the asset — spent 12 days in a 24h-TTL
#            Redis key because its Postgres migration (written 2026-07-26) was
#            never applied, so every write hit the fallback and logged a warning
#            that fired every time and therefore carried no information.
#            Guards: the fallback is COUNTED not just logged, and one failure is
#            already degraded — there is no acceptable rate of losing research.
python3 -m tests.test_strategy_durability
# 3a-septies. L0 data architecture (2026-08-07). asset_class lived on OBSERVATION rows,
#             where it actually recorded the SOURCE - 24 symbols carried conflicting
#             labels, and source determines candle convention (>1% open gaps: Crypto
#             31.3% vs DeFi 83.5%). So `where asset_class=...` was a source filter in a
#             class filter's clothing, which is how S-106 read a splice between two bar
#             conventions as market structure. Class now lives only in `assets`.
python3 -m tests.test_data_architecture
# 3a-octies-2. ① beta-core book (2026-08-07, oversight review). All five books accruing
#              a forward record were long/short market-neutral - the ④ construction that
#              produced the R76-R94 graveyard - while layer ①, the FoF core AND the
#              benchmark for every other book, had ZERO forward days. Guards the product
#              book's invariants: long only, exposure in [0,1.3], the vol scalar may
#              de-lever freely but never lever past the ceiling, unmeasured inputs resolve
#              to NEUTRAL rather than to large, and the benchmark leg is structural so
#              excess is arithmetic rather than a benchmark chosen at analysis time.
python3 -m tests.test_beta_core_book
# 3a-nonies. effective breadth (2026-08-08, S-115). Three ledger entries quoted
#            N/(1+(N-1)rho) as "independent bets". It is not: that formula is the
#            exact answer for equal-weight VARIANCE REDUCTION (long-only book), while
#            breadth in IR = IC*sqrt(breadth) is the correlation matrix's SPECTRUM
#            (neutral book). They diverge even when equicorrelation HOLDS - 2.99 vs
#            7.38 at rho=0.3 - so the error was never arithmetic, it was quoting a
#            breadth number without saying which book it constrains.
python3 -m tests.test_effective_breadth
# 3a-decies. storage hygiene (2026-08-08). Supabase hit 90% of its tier and the
#            obvious move was archiving rows. Measurement said otherwise: ~84 MB of
#            dead indexes plus ~128 MB of bloat from a same-day bulk UPDATE that
#            populated asset_id - autovacuum had already cleared the dead tuples, so
#            the waste was invisible to the usual check while the pages stayed fat.
#            449 -> 237 MB with zero rows archived. Guards the generalisable parts:
#            a bulk UPDATE on a large table must declare its storage cost, index
#            scan counts are evidence only when the stats are old enough, and the
#            archive order is set by REFETCHABILITY rather than by size.
python3 -m tests.test_storage_hygiene
# 3a-undecies. state persistence (2026-08-08, S-117/S-118). A layer-③ sleeve was
#              being built on `macro_regime`, whose median run is 3 DAYS with 51%
#              of runs ≤3d — more than half its "transitions" were label chatter.
#              A causal 5-day dwell filter takes the median to 19d and makes the
#              trigger legitimate, but drops EASING↔RISK_OFF from 8/8 to 3/3.
#              Guards: the filter is CAUSAL (a centred one would leak the future and
#              become the edge), and it reports BOTH costs — sample destroyed and
#              latency added — because reporting only the smoother chart is a pitch.
python3 -m tests.test_state_persistence
# 3a-duodecies. strategy intake (2026-08-08). Minimax-A asked for the service_role
#               key to write beta-strategy records. Declined; this endpoint replaces
#               it and is better on two counts. Blast radius: service_role bypasses
#               RLS on every table while a scoped token appends records and rotates
#               freely (Lesson #72 - a forged JWT passed every local check). And the
#               gate becomes unbypassable: with a raw DB key a SHIP record failing
#               the discipline floor can be written anyway, because the floor lives
#               in CI and CI is not in the write path. Here validate() runs BEFORE
#               the insert - a gate the writer can route around is a suggestion.
python3 -m tests.test_strategy_intake
# 3a-terdecies. regime write path (2026-08-09). Chasing a discrepancy flagged twice
#               and left unchased - the table said Tightening while the ① book had
#               read NEUTRAL - produced two bugs in one query. The daily snapshot
#               passed a MISSING regime through the lenient canonical_regime(), which
#               returns "NEUTRAL", and wrote it for all 58 symbols in one batch, once
#               a day. And the push receiver stored the Mac engine's label RAW, so the
#               table holds `Tightening` and `TIGHTENING` as if they were two regimes.
#               Live cost: the ① book sizes off this label (TIGHTENING 0.5, NEUTRAL
#               1.0) and ran FULL SIZE on day one of its forward record. A normaliser
#               that turns unknown into a legitimate value belongs on the READ side
#               only; on write, unmeasured is NULL (I1).
python3 -m tests.test_regime_write_path
# 3a-quaterdecies. degraded-value guard (2026-08-09, S-122). S-121 was the FIFTH
#                  instance in one day of an unmeasurable value being replaced by a
#                  plausible one and then stored, where no consumer can tell the
#                  substitute from a reading. Four of the five were found only after
#                  they had written data, and three only because the substitute
#                  happened to look wrong - which is luck that runs out exactly where
#                  the damage is worst: a default equal to the MAJORITY value is
#                  undetectable forever. trade_results.side defaulted to "LONG" while
#                  82% of rows are LONG, and shorts average -2.28% against longs'
#                  +0.26%, so the failure moved the worst trades into the long side of
#                  the record. Scans dict-value fallbacks inside functions that
#                  persist (transitively, so factoring the row builder out of the
#                  writer does not launder it), and unwraps .upper()/round() so a
#                  normalisation call cannot hide one. Read-side rendering is out of
#                  scope by construction - globally the same pattern returns 296 hits
#                  and a guard nobody can run is a guard nobody runs.
python3 -m tests.test_degraded_value_guard
# 3a-sexdecies. compliance language (2026-08-09). Hard rule 1 — no SFC Type 4/9
#               licence, so user-facing surfaces carry POSITIONING language only —
#               had never been enforced by anything. The full code check found NINE
#               live violations across five files. Every one was HEDGING prose
#               ("Avoid chasing parabolic moves", "not a buy list"): written to sound
#               prudent, which is exactly why they passed human review. The words
#               that read as caution to a colleague read as advice to a regulator,
#               so the check has to be mechanical. Scoped to routers + dashboard +
#               static HTML; research, tests and logs are explicitly out of scope per
#               the skill, and the methodology page may still RENDER the banned list.
python3 -m tests.test_compliance_language
# 3a-septdecies. SQL privilege idiom (2026-08-09). Four SECURITY DEFINER functions
#                that fetch over HTTP and write unbounded rows were callable by anon
#                — public by construction — with a caller-controlled batch count.
#                The scripts ALREADY revoked them, and had all along: `revoke ... from
#                anon` cannot remove a grant held by PUBLIC, which anon merely
#                inherits. It succeeds, returns nothing, and changes nothing. The
#                correct idiom (`from public`) already existed once in this repo, on
#                the one function that was actually locked. Same failure family as
#                S-105/S-116/S-122: an operation that reports success while doing
#                nothing. This guard reads scripts, so it proves the IDIOM, never the
#                database — the live check belongs to a scheduled probe.
python3 -m tests.test_sql_privilege_idiom
# 3a-duodevicesimo. embedding dimensions (2026-08-09, S-127). Measured on the live
#                   table: all 58 stored vectors had their FIVE CIS PILLAR dims set
#                   to exactly zero — identical for every asset — so the vector space
#                   ARCHITECTURE calls the geometric substrate carried no information
#                   from the thing the product is built on. `generate_embedding`
#                   inlined its own two-shape pillar lookup while the canonical
#                   four-shape extractor sat 150 lines above it in the SAME FILE, and
#                   `or 0` turned "shape not matched" into "scored zero". A
#                   zero-variance dim is worse than an absent one: it still inflates
#                   the norm, dragging every pairwise cosine toward 1 (measured median
#                   0.846, 29.9% of pairs above the 0.95 the MCP tool calls
#                   "near-identical"). Also pins that the two pillar resolvers —
#                   embedder._pillars_of and main._pillar_of — agree on all five
#                   shapes; each previously missed one the other handled.
python3 -m tests.test_embedding_dims_carry_information
# 3a-quaterdecies-bis. value added in DOLLARS (2026-08-10, S-132). Every sleeve we
#                have ever measured was denominated in percent. Berk & Green (JPE
#                2004) and Berk & van Binsbergen (JFE 2015): percentage alpha is
#                competed away by inflows and does not predict itself, while gross
#                alpha × assets DOES, out to ~10 years. The unit matters most in
#                crypto, where the characteristic deception is a large percentage on
#                a notional that could never be deployed — 40 %/yr on a $150k book
#                bounded by a $3m/day order book passes every percentage threshold we
#                own, because 40 is greater than all of them. So a SHIP verdict now
#                requires deployable_notional_usd + value_added_usd_yr + a stated
#                notional_basis ("assumed AUM" is the S-122 degraded-value pattern
#                wearing a dollar sign), with a $1m capacity floor single-sourced from
#                the schema. Also pins capacity(): it used to `continue` past names
#                whose ADV lookup failed, and since book capacity is a MINIMUM over
#                names, dropping one can only RAISE the answer — and the ones that
#                fail to resolve are the thin names that would have bound.
python3 -m tests.test_value_added_dollars
# 3a-quaterdecies-ter. HAR-RV study specification (2026-08-11, S-134). Guards a
#                STUDY rather than a production path, which earns its place here
#                because the study produced THREE verdicts on synthetic data where
#                the answer is known by construction, and only the third was right:
#                (1) exp(Xβ) predicts the MEDIAN, so QLIKE — asymmetric, punishes
#                under-prediction — declared the incumbent the winner; (2) the
#                textbook exp(Xβ+σ²/2) made it WORSE, because the LHS is a single
#                squared return, so log(r²) carries log-χ²₁ noise (var ≈4.93) and
#                the fitted σ² measures PROXY NOISE — σ²/2≈2.5 inflated every
#                forecast ~13x, and both losses then agreed on the wrong answer;
#                (3) Duan's smearing (JASA 1983) is nonparametric and lands ≈3.6.
#                Plus the structural point: QLIKE identifies the conditional MEAN
#                and MSE-on-log the MEDIAN, so "must win on both proper losses" is
#                incoherent unless each is scored against the functional it
#                identifies. A refutation from a mis-specified study is worse than
#                no study, because it goes in the ledger and stops the question
#                being asked again. Positive control: HAR must win on 5 synthetic
#                GARCH seeds where vol is persistent by construction.
python3 -m tests.test_har_rv_study_is_specified_correctly
# 3a-quindecies. written columns vs declared schema (2026-08-11, S-138). /api/v1/keys
#                POSTed a column named `intended_use`; the live table has `notes` and
#                never had the other. PostgREST 400s on an unknown column, _sb_post
#                collapsed every failure into "Key storage failed", and the endpoint
#                returned that same opaque 500 from the day it shipped — ZERO keys ever
#                issued. supabase_all_tables.sql declared intended_use too, so the file
#                and the table agreed with each other about being wrong.
#                The typo is not the lesson. The lesson is that ONE WORD survived THREE
#                confident diagnoses (anon lacks INSERT — it does not; SUPABASE_SERVICE_KEY
#                missing — not the cause; id has no sequence — id is GENERATED ALWAYS AS
#                IDENTITY, and information_schema reports column_default=null for identity
#                columns, which is exactly what a missing default looks like). Each was
#                invented to fill the space the error message left empty. A generic failure
#                message does not merely fail to help, it FUNDS wrong answers, and each one
#                costs a round trip through the one person with console access.
#                Guards both halves: written columns must be declared, and the endpoint
#                must pass PostgREST's own message through.
python3 -m tests.test_table_columns_match_the_code
# 3a-sexdecies. hard rule #8 — no implementation on investor-facing surfaces
#               (2026-08-11, S-139). The rule existed and was violated in TEN
#               rendered strings, including two the rule names directly: strategy.html
#               shipped "Execution → Freqtrade + CEX APIs", and the PAID TIER list
#               offered "Dedicated Mac Mini scoring lane" + "Historical score data
#               (Supabase)". A pricing page describing our hardware tells a competitor
#               what to clone and tells an allocator that a $500M target runs on a
#               desktop. Every asset footer read "Mac Mini local engine / Railway
#               estimation"; an error toast read "Railway may be starting up".
#               A rule that lives only in prose is re-broken by every author who did
#               not have it in mind that morning — the same argument that produced
#               test_compliance_language. That one governs what we CLAIM; this one
#               governs what we REVEAL. Replacements state the CAPABILITY
#               ("full-model score"), so the tier and its meaning stay visible and
#               only the part a competitor benefits from goes away.
python3 -m tests.test_no_stack_leakage_on_user_surfaces
# 3a-septdecies. usage metering can support an invoice (2026-08-11, S-140). Usage
#                lived ONLY in Redis under a 24h TTL and api_keys.request_count was
#                incremented by NOTHING — a column shown on the analytics page that
#                had read 0 since creation. There was no substrate to bill from: not
#                "billing is unbuilt", the usage itself did not survive a day. S-105's
#                shape (strategy library in a 24h-TTL Redis key) moved onto revenue,
#                and worse — research can be re-derived, a month of metered usage
#                cannot. Also S-131's shape: "made no calls" and "we failed to meter"
#                rendered identically.
#                Guards the property that makes it billable: the flush is MONOTONE
#                (requests = GREATEST(existing, incoming)) and that guarantee lives in
#                the database function, not the caller — so a replay cannot
#                double-count, a missed flush is recovered by the next, and a Redis
#                reset leaves the high-water mark. We under-count on a lost counter
#                and never over-count: a bill we can defend is a conversation, an
#                over-bill is a refund and a reputation. Also pins Postgres OFF the
#                request path (the 2026-07-29 saturation P0) and that the audit write
#                REPORTS whether it landed.
python3 -m tests.test_metering_is_billable
# 3a-octodecies. the research intake accepts evidence, never conclusions (2026-08-15,
#                S-164). Measured against the live DB: strategy_records and
#                asset_embeddings have RLS on with ZERO policies, experiment_runs has
#                SELECT only. Every key except service_role is refused — correctly.
#                Minimax-C was asked to land 172 mined artefacts down a path that was
#                closed, and found out by collision, because nothing said it was
#                closed. The service_role key is deliberately not shared with the
#                mining lanes, so /internal/research-intake opens the write path the
#                same way /internal/cis-scores already works: one credential boundary,
#                one normalizer, one schema echo.
#                WHAT THIS GUARDS is the asymmetry that makes that safe: a lane may
#                submit evidence of any strength and may NOT submit the conclusion.
#                SHIP is what test_strategy_discipline earns over the committed record
#                — documented cause, oos_survival=True, >=60d paper trade,
#                regime-conditional reporting. An intake that accepted a pre-declared
#                verdict would be a route around the only gate we have, and a bar that
#                can be asserted past is not a bar. Behavioural, not frozen: it asserts
#                that NOTHING submitted authorises deployment, over spellings nobody
#                has written yet — a frozen alias list would pass the day somebody adds
#                the 16th, which is exactly how the C3 table passed while transposed.
#                Also pins the upsert (retries must not duplicate — duplicates in
#                experiment_runs corrupt every base rate we make decisions with) and
#                that a declined write never reports accepted rows (the 80-day dead
#                signal_outcomes pipeline, rebuilt on purpose here so it cannot recur).
python3 -m tests.test_intake_cannot_declare_its_own_verdict
# 3a-undevicies. every table the code writes to must exist (2026-08-15, S-166).
#                Measured against the live DB: ELEVEN did not — both C2 and C3
#                sleeve NAV tables, strategy_params, the execution log, the fusion
#                paper book, crowd_clock_log. PROJECT_STATE read "C2 ⓠ + C3 size
#                complete; 79/79 smoke green" while neither sleeve had anywhere to
#                write a row. Every such write returns False and is swallowed,
#                which is indistinguishable from "no data yet" — the same shape as
#                the 80-day dead signal_outcomes pipeline and the strategy library
#                in a 24h-TTL Redis key. The system's way of failing looks exactly
#                like its way of being early.
#                AND IT WAS ALREADY WRITTEN DOWN. OPEN RISK #3(a), since
#                2026-07-26: "A table that was never created ... POSTed to a
#                nonexistent table, caught the exception, logged one WARNING,
#                returned False." That got fixed for ONE table; nothing compared
#                the SET the code writes against the SET that exists, so it
#                recurred eleven times.
#                This is the OFFLINE half — the manifest matches what the source
#                actually does, extracted by AST rather than hand-maintained.
#                The online half is GET /internal/schema-drift, called by the
#                deploy-verifier, because preflight is offline by contract (S-163)
#                and a check needing credentials belongs where they already are.
#                Neither half can pass vacuously: a stale manifest fails here, a
#                missing table fails there, deleting the manifest fails both.
python3 -m tests.test_every_written_table_exists
# 3a-vicies. no .sql file grants PUBLIC read or write (2026-08-15, S-167).
#            Measured live with `set local role anon`: api_keys readable (1 row),
#            signal_track_record readable (836 rows), experiment_runs readable
#            (43 rows). The last two ARE the product — ARCHITECTURE.md: "the
#            scarce resource is verifiable forward track record; the validation
#            apparatus IS the product." Readable with the key that ships in the
#            browser bundle.
#            WHY THE 2026-07-30 HARDENING MISSED IT: it added `<table>_service_only`
#            policies with USING (false), which READ like denials. Postgres
#            PERMISSIVE policies are OR'd — a permissive policy cannot subtract, so
#            USING(false) OR USING(true) = allowed. Lesson #71 was "a linter's
#            silence is not safety"; this is "a policy that reads like a denial is
#            not a denial", and it is worse, because the false denial made the
#            table look audited and audited things stop being checked.
#            Separately: 33 write grants + 23 read grants to PUBLIC across 8
#            migration files, none of them live. Drift ran FILE-MORE-PERMISSIVE-
#            THAN-PRODUCTION — the dangerous direction, since these files are
#            idempotent, exist to be re-run, and one WAS re-run that same day.
#            Two of this guard's own findings were mine: it first matched the
#            comments it had just written (the SIXTH guard-reads-its-own-prose bug
#            here), and it caught three permissive USING(false) policies I added
#            in the same hour as the ledger entry explaining why they do not work.
python3 -m tests.test_no_sql_file_grants_public_access
# 3a-unvicies. a read-only production must be impossible to miss (2026-08-15,
#              S-168). The live deployment reported `environment: replica`, so
#              S-149's role gate refused EVERY write to the system of record —
#              cis_scores, beta_core_nav and experiment_runs all stop on
#              2026-08-12, three days before anyone noticed. The Mac T1 engine
#              was pushing the entire time (last_cis_push age 38 min, 43 assets,
#              stale=false): the push arrived, returned 200, and was discarded.
#              Arriving-and-discarded looks exactly like arriving-and-stored.
#              ROOT: a belief about another system, written down and never
#              probed. runtime_role.py said "Railway sets ENVIRONMENT=production
#              explicitly, so the mapping preserves the live deployment". It does
#              not. The sentence was emphatic — "deliberate and load-bearing" —
#              and that emphasis is what stopped anyone checking. Confidence in
#              prose is not evidence, and a comment cannot probe an env var.
#              `environment: replica` was on /health the whole time; it names the
#              ROLE, not the CONSEQUENCE. Every failure this week had that shape:
#              the state was visible and the consequence was not. So /health now
#              carries a `writes` block that says "READ-ONLY — nothing is being
#              persisted" in words and names the exact fix.
#              Also pins the gate FAILING CLOSED: unset must stay replica.
#              Defaulting to production would let any laptop write the LP-facing
#              record, which is worse than the outage it would prevent.
python3 -m tests.test_production_can_write
# 3a-duovicies. Mac-lane writes come through Railway, and cannot report a write
#               that did not happen (2026-08-18, S-169 / Mac-A's
#               §NO-DIRECT-SUPABASE step 2). Confirmed 2026-08-16 on the Mac:
#                 [M-WO-D1] built 58 rows ... ERROR SUPABASE_KEY missing ...
#                 [M-WO-D1] push complete
#               Build succeeded, write did not, script said "complete". Measured
#               2026-08-18: asset_embeddings_history 0 rows, risk_meter_history
#               0 rows — that path never landed a single row. Mechanism: the Mac
#               .env holds the ANON key and both RPCs are SECURITY INVOKER, so
#               they run with the caller's privileges and RLS denies the tables.
#               service_role is deliberately in no .env, so the write is routed
#               to the process that already holds it rather than the key handed out.
#               PINS: ok=false always carries rows_written=0 and a NAMED reason
#               (role gate vs Supabase rejection — different owners, different
#               fixes, and collapsing them sent us down the wrong one twice this
#               week); and the write uses supabase_rpc_write, not the ungated
#               supabase_rpc, which predates S-149 and would have put Mac writes
#               OUTSIDE the boundary while supabase_insert_table beside it refuses.
python3 -m tests.test_mac_push_wrappers
# 3a-trevicies. §NO-DIRECT-SUPABASE step 5, INFO-ONLY for now. Sequence is
#               (1) Mac sweep → (2) wrappers → (3) Mac switches callers →
#               (4) backfill → (5) this goes hard-fail. Step 2 landed today;
#               step 3 has not, so failing now would block every push on a
#               violation that is expected, and a gate that fires on known-and-
#               planned state teaches people to use --no-verify.
#               Three-valued: violations / clean / NOT-CHECKED-because-unmounted.
#               The third state is said out loud — this greps a Mac volume absent
#               from the sandbox and CI, and a silent skip would report "clean"
#               from a machine that never looked (the S-163 vacuous-pass hazard).
#               Flip with NO_DIRECT_SUPABASE_STRICT=1 once step 3 lands.
bash scripts/check_no_direct_supabase.sh
# 3a-quattuorvicies. every <Component> used in .jsx is in scope (2026-08-18,
#                    S-171). Clicking "Asset Radar" gave a BLANK page, sidebar
#                    and all: `ReferenceError: AssetRadar is not defined`.
#                    App.jsx:390 rendered it; App.jsx never imported it. The
#                    import was lost in 227edcd (App.jsx 1046 -> 445); the same
#                    split dropped DiagnoseHome, which a human caught in e9c5b4d.
#                    One of the two was noticed. The other shipped.
#                    NOTHING ELSE COULD HAVE CAUGHT IT: the Vite build stayed
#                    green because CISContent.jsx lazy-imports the same component
#                    for its own tab, so the chunk was emitted and no warning
#                    fired — a module referenced somewhere is not a module in
#                    scope here, the same distinction as "declared in a .sql
#                    file" vs "exists in the database" (S-166). The
#                    SectionErrorBoundary could not help: the name resolves while
#                    App itself renders, above every boundary inside App, so the
#                    whole tree unmounted. test_no_undefined_names is PYTHON ONLY
#                    — its founding incident was `market_cap is not defined`
#                    silently killing T2, the identical shape, and the guard's
#                    scope stopped at the language boundary while the code did not.
#                    ESLint 9 IS configured here and `no-undef` does NOT flag it
#                    (measured: exit 0 on a probe). react/jsx-no-undef would;
#                    it needs eslint-plugin-react, which is not installed —
#                    installing it is the correct long-term fix. Until then this
#                    uses a criterion that needs no parser: a name occurring ONLY
#                    as `<Tag` and nowhere else in the file cannot have been
#                    defined. Verified by negative control — removing the restored
#                    import makes it fail on App.jsx again.
python3 -m tests.test_no_undefined_jsx_components
# 3a-undevicesimo-bis. dashboard/dist/ freshness vs dashboard/src/ (B-4, 2026-08-25,
#                       Minimax-B authored). Same shape as the S-171 incident but a
#                       different cause: the build was SKIPPED. `git add src/ ...`
#                       without `cd dashboard && npm run build` and a follow-up
#                       `git add dashboard/dist/` lands a stale bundle on Railway,
#                       which auto-deploys regardless of CI. The guard compares the
#                       newest src mtime to the newest dist mtime; one-way (src
#                       newer → fail). The fix is mechanical and given in the
#                       failure message. Second incident of this shape in 2026-08.
python3 -m tests.test_vite_bundle_freshness
# 3a-undevicesimo-ter. Millennium DD-stop floor (2026-08-25, Minimax-B, §5b-ter).
#                         Every SHIP-verdict StrategyRecord MUST carry
#                         max_dd_stop + capital_action_on_breach +
#                         backtest_included_stop=True. StrategyRecord.validate()
#                         already enforces this at write time (src/data/vector/
#                         strategy_schema.py:305-310) — this test is the backstop
#                         against legacy hand-edited Redis rows and against the
#                         verdict-change-without-revalidate class. Pin the schema
#                         fields exist (a rename without a parallel guard is the
#                         next failure mode). Vacuous-pass logged, not silenced
#                         (S-163 hazard).
python3 -m tests.test_ship_records_have_dd_stop
# 3a-duodevicies. the moat is claimed only where it is measured (2026-08-12, S-141).
#                ARCHITECTURE.md line 164: "A signal we have not run through our own
#                loop is one we must not claim. Claiming it unproven is
#                self-deception, and self-deception cannot teach." Measured live:
#                58/58 assets returned out_of_circle_risk="low" with stage=null and
#                source="market_proxy", and a driver reading "no out-of-circle stress
#                DETECTED" — a negative finding asserted by a test that never ran.
#                The band borrowed the vocabulary of a real holder/attention reading,
#                so a never-firing indicator and a switched-off one rendered
#                identically (S-131's cap_source, on the concept ARCHITECTURE calls
#                the moat). Now: no diffusion input ⇒ band "unmeasured", an explicit
#                diffusion_measured flag, and a driver naming what is missing.
#                This one matters more than the plumbing bugs it resembles because
#                the consumer CANNOT check us — the provenance we hand over IS the
#                product, and provenance that says "measured" when it means "guessed"
#                destroys the proposition rather than one endpoint.
python3 -m tests.test_moat_claims_are_measured
# 3a-undevicies. no route is shadowed by a path parameter (2026-08-12, S-143).
#               FOUR endpoints were deployed and unreachable: /factors/performance,
#               /factors/discovery, /strategy/stats, /ohlcv/coverage. FastAPI matches
#               in REGISTRATION order, and a single-segment /{param} registered first
#               swallows every literal sibling after it.
#               It survived because the 404 is PLAUSIBLE — "Factor 'performance' not
#               found" reads like a missing factor (a data question) rather than a
#               hijacked route (a routing question), so anyone checking concluded the
#               endpoint worked and looked in the wrong place. Same class as S-138's
#               "Key storage failed" and S-141's "low": a believable wrong answer.
#               /factors/discovery was shadowed ACROSS ROUTERS — factors_router's
#               /{factor_id} eating discovery_router's literal — which is invisible
#               when reading either file, so code review cannot catch this class.
#               The guard flattens fastapi.routing._IncludedRouter and asserts the
#               route COUNT: its first version scanned 31 of 197 and printed a clean
#               result, which is the same defect committed inside its own fix.
python3 -m tests.test_no_route_is_shadowed
# 3a-unetvicies. /internal/ rejects anonymous callers — BEHAVIOURALLY (2026-08-30, S-262).
#            Three static scanners answered "how many /internal/ routes lack a token
#            gate" with 13, then 22, and both were wrong: four of the 22 "new" finds
#            (rebalance, sl-tp-exit, research-intake, asset-vectors/rebuild) are gated
#            via helpers named `expected`/`tok`/`_auth()`. A scanner matches SPELLING,
#            not "will this route refuse an unauthenticated caller".
#            In the same hour I gated two endpoints and wrote FOUR consecutive bugs
#            that only fire on the error path (undefined _INTERNAL_TOKEN, unimported
#            HTTPException, `os` shadowed by a later local import). All four passed
#            import, py_compile and the happy path; each returned 500 instead of 401
#            to the exact caller the gate exists to stop.
#            So this guard sends REAL requests, with each route's REAL methods —
#            its own first version only sent GET, read the 404s from 23 POST-only
#            endpoints as "closed", and thereby committed the defect its docstring
#            describes. It found /internal/telegram/webhook accepting anonymous POSTs
#            (`if secret and ...` skipped the whole gate when the secret was unset:
#            absent and correct took the same branch), now fail-closed.
python3 -m tests.test_internal_routes_reject_anonymous
# 3a-vicies. vector schema version is single-sourced (2026-08-12, S-144). Live:
#            asset_embeddings held 72 rows ALL stamped schema_version=2, 18 days
#            stale, with TWO different `dims` (18 and 27) under the same version —
#            and /api/v1/cis/embeddings answered 503.
#            The writer was not dead. embedder.SCHEMA_VERSION went to 3 on
#            2026-08-09 while store.py wrote the LITERAL 2 under a comment claiming
#            it was embedder.SCHEMA_VERSION, and pgvector_store defaulted to 2. So
#            the store stamped a version it was not producing.
#            A version stamp that does not track the thing it versions is WORSE than
#            no stamp: absent, a reader knows they do not know; wrong, they are
#            confident and mistaken. Two dims under one version is the visible
#            symptom of exactly the property a version exists to make impossible.
#            The one test asserting the version asserted ==2 and was never wired
#            into the gate — the check that could have caught the drift was itself
#            holding the stale value, and never ran. Both are fixed and both now run.
python3 -m tests.test_vector_schema_version_is_single_sourced
# 3a-vicies-bis. the stale fallback must survive a COLD process (2026-08-12, S-146).
#              Overnight 08-11→12 every Mac cycle logged "CIS universe build timed out
#              and no cached payload available", and the day's writes died with it:
#              trending_log 0, conviction_verdicts 0, narrative_snapshots 0,
#              cause_snapshots 0, beta_core_nav 0, causal_paper_nav 0 — while
#              cis_scores wrote 116 (it does not depend on that build). ONE SLOW BUILD
#              STARVED EVERY WRITER DOWNSTREAM OF IT FOR A DAY.
#              A stale fallback existed. It read _UNIVERSE_CACHE, a module-level dict,
#              and the scheduler runs each task as a FRESH PROCESS — so the net was
#              empty at the exact moment it was consulted. Present in the code, tested,
#              and unreachable in the one situation it was built for.
#              The fix is not a longer budget (that moves the failure date); it is a
#              cross-process copy, which changes the failure MODE from "no record for a
#              day" to "a record marked stale". Both 503 paths chain to it, and stale
#              is never served silently (S-104).
python3 -m tests.test_stale_fallback_survives_a_cold_process
# 3a-vicies-ter. exactly one process may WRITE the record (2026-08-12, S-149).
#              Running the app locally starts 20+ background loops, a dozen of which
#              write Supabase and share Redis state keys with Railway. Both would
#              have marked beta_core_nav for the same day off different panels — the
#              forward record, the one artefact that cannot be re-derived, becoming a
#              function of which machine woke first. The only thing preventing it was
#              that SUPABASE_KEY happened to be EMPTY locally. Safety by accident.
#              And the default made it worse: ENVIRONMENT defaulted to "production",
#              so an UNSET variable made any laptop a live writer.
#              Boundary is WRITE, not CONNECT — reading prod from a laptop is useful
#              and harmless. Gate sits on the two write functions, not the loops,
#              because loops keep being added and a gate you must remember to apply
#              is one that will be forgotten (same argument as GREATEST living inside
#              api_usage_upsert). Unset ⇒ replica; an unknown role refuses to boot;
#              APP_ROLE=dev is refused until it has a private namespace, because a
#              'dev' writer sharing prod state keys IS the hazard.
python3 -m tests.test_only_one_process_writes_the_record
# 3a-quaterdecies-bis. sizing cannot invert (2026-08-12, S-151). C3's 5x5 conviction
#                table was transposed on BOTH axes: max leverage at max regime
#                unfamiliarity with the weakest signal, and 1.20x gross with no inputs
#                at all. It survived because the table, its smoke test and the hook
#                docstring all agreed with each other — only the module's stated design
#                dissented, so every consistency check passed. A frozen-value check
#                cannot catch this: the table was transposed BEFORE it was frozen, and
#                freezing preserves it. So the guard asserts BEHAVIOUR (monotonicity;
#                no leverage on no information), which holds for every correctly
#                oriented table and fails for every inverted one — including ones not
#                written yet, which is the only guard worth having now that the values
#                live in `strategy_params` and can change without a deploy.
python3 -m tests.test_sizing_cannot_invert
# 3a-quaterdecies-ter. universe membership is recomputed, not inherited (S-153).
#                Measured: universe_membership WHERE universe='investable' had 75 rows,
#                valid_from = 2025-05-03 for EVERY asset including BTC, valid_to NULL on
#                all of them — one birthday, no deaths. Every multi-year backtest that
#                filtered on it was holding, in 2021, a basket selected for surviving to
#                2026. The `coverage` universe carried the truth all along (488 listings
#                back to 2015, 125 recorded delistings); it was never used. The guard is a
#                TRUNCATION test — the answer on the full panel must equal the answer on a
#                panel truncated at as_of — because look-ahead enters through a window
#                boundary or a <= that should be <, and no amount of reading catches that.
python3 -m tests.test_universe_is_point_in_time
# 3a-quaterdecies-quater. capacity tripwire (S-154). R66-C's edge sits in names too
#                small to hold at size: the ten clearing a $5M ADV floor summed to
#                -21.3% of a +154.6% total. At $500M that disqualifies it; at $10k it
#                is irrelevant. Both true, expiring at different times — and the sleeve
#                will never announce that it outgrew its universe, the fills just get
#                worse, and worse fills look exactly like a decaying edge. So the alarm
#                is on SIZE, and the ceiling is RECOMPUTED (COMP measured $1.4M and
#                $0.3M ADV in the same hour, so a stored number is wrong by 4.7x within
#                a session). Also separates the two costs: impact vanishes with size,
#                spread does not and is wider on exactly the thin names carrying the edge.
python3 -m tests.test_aum_tripwire
# 3a-quaterdecies-quinquies. execution log records the MISSES (S-155). The $10k book
#                starting 2026-08-17 exists to measure the one input a backtest cannot
#                have: what we actually pay to trade. R66-C assumed 10bps and showed
#                break-even at 150bps, but that ladder priced FEES — the entire VIP0→VIP9
#                ladder is ~3.3bps while crossing a $1-2M ADV alt perp spread is 25-50bps,
#                which at ~28 rebalances/yr is 56%/yr against a realised ~96%/yr.
#                Posted orders fill through ADVERSE SELECTION, so a fills-only log measures
#                execution as excellent and deletes the tracking error — survivorship moved
#                to the execution layer, and easier to commit here than anywhere else
#                because an unfilled order leaves no trace in the account, the P&L or the
#                exchange statement. An intent is written before the order exists and
#                resolved exactly once, to a fill OR an expiry.
python3 -m tests.test_fill_log_records_the_misses
python3 -m src.data.signals.tests.test_beta_core_size_smoke
python3 -m src.data.signals.tests.test_beta_core_size_hook_smoke
python3 -m src.data.vector.tests.test_embedder_v2_smoke
# 3a-quindecies. inception identity (2026-08-09, S-123). The ① book was re-inceptioned
#                after its v1 run was found to have sized off a 23-day-stale regime.
#                The integrity property this pins is the product's: a forward track
#                record whose NAV can be quietly reset proves nothing, because the
#                reader cannot distinguish sixty days of survival from the sixtieth
#                attempt. So `_INCEPTION_ID` must be a CODE constant — re-inception
#                costs a commit and is therefore dated, attributed and permanent in
#                git log — never an env var, which would move the decision somewhere
#                with no history. All three read paths (state recovery, continuity,
#                published curve) are scoped to the live incarnation and exclude
#                voided rows: unscoped recovery would resurrect the voided NAV on the
#                next cache eviction while logging a healthy recovery, and an unscoped
#                curve would splice a void segment onto a live one and read as
#                continuous. Superseded runs are voided in place, never deleted.
#                (Enforced by test_beta_core_book, already invoked at 3a-octies-2 —
#                 one invocation, so there is no second copy to drift.)
# 3a-quater. venue consolidation — the wrong-ASSET class (2026-08-01). cis_provider
#            mapped HYPE to Binance spot HYPERUSDT, which is Hyperlane: $0.0558 vs
#            Hyperliquid's $52.32, a 937x error that scored the asset D/UNDERWEIGHT
#            through a +256% run while every completeness check stayed green. A
#            populated wrong number is invisible to "is the field set?" and obvious
#            to "do independent venues agree?". Offline/deterministic — the LIVE
#            cross-venue probe belongs in loop_health SENSE, not in a code gate.
python3 -m tests.test_venue_consolidation
# 3a-quinquies. CIS drift detector (the HYPE case, 2026-07-30): pure detection
#              logic must regress-safe; live supabase probe lives in scheduled cron,
#              not in a code gate (offline/deterministic only here).
python3 -m tests.test_cis_drift_detector
# 3a-sexies. ⓠ REGIME OVERRIDE enforcer (2026-08-06, first cut): wraps research-side
#             m_wo_q_o1_stablecoin_gate.assign_band_hysteresis into production-shape
#             API (apply_regime_override, apply_regime_override_series). PIT-safe,
#             allows only the v1 allowed-cap set {0.0, 0.5, 1.0, 1.3}.
python3 -m tests.test_regime_override_enforcer
# 3a-septies. ⓠ REGIME OVERRIDE paper track (2026-08-06, parallel paper NAV under
#              enforcer). Tests pure backtest/aggregation logic; live paper runner
#              is wired into daily_runner.py post-validation (60d forward paper).
python3 -m tests.test_fusion_paper_regime_track
# 3a-octies. build_l1_observations.py smoke (2026-08-07, Lesson #72 follow-up): the
#             script's --diagnose probe verifies the live Supabase key against the
#             server (the 2026-08-02 forged-key class). It cannot run inside the
#             offline gate; this test pins the script shape (imports, constants,
#             resolve_panel_source('none'), compute_panel_series, diagnose()
#             contract) so a structural regression can't reach Railway. The actual
#             network probe belongs in the scheduled cron path.
python3 -m tests.test_build_l1_observations_smoke
# 3b. contract schema echo — the drift class preflight previously couldn't see (Mac push schema
#     changed, Railway didn't follow). Prints the canonical SCHEMA_VERSION so it's in every log,
#     and fails loudly if the contract module stops importing.
python3 - <<'PY'
from src.api.contracts.cis_push import SCHEMA_VERSION
from src.data.vector.embedder import SCHEMA_VERSION as VEC_SCHEMA, ASSET_DIMS_V2
print(f"  ✓ cis_push contract SCHEMA_VERSION={SCHEMA_VERSION} · vector schema v{VEC_SCHEMA} ({ASSET_DIMS_V2}-dim)")
PY

# 3a-quinvicies. the two forward records actually record (2026-08-18, S-173).
#                S-172 measured -1.85% 20d excess (t=-5.23) for depth-up/price-flat
#                IN SAMPLE; depth_divergence_log tests it forward, inception
#                2026-08-18, gate 2026-10-17. holder_concentration_history is the
#                timeseries holder_provider.py has been deferring since inception
#                — its own code reads `"chuquan": False,  # Phase 2 (needs
#                timeseries)` and every refresh wrote concentration into a TTL'd
#                Redis map and let yesterday expire. A velocity cannot be computed
#                from one snapshot, so the entire holder-cohort direction was
#                gated behind a table nobody created.
#                GUARDS TWO PROPERTIES, both learned the hard way this week:
#                (1) a row records how much of the panel it saw. The FIRST call to
#                refresh_depth_divergence() wrote 25 rows against a 262-symbol
#                panel — the Crypto feed is 10 days stale while the other classes
#                are current. Unrecorded, the log fills with 25 rows a day and
#                looks healthy.
#                (2) an outcome column is never written at creation time, and a
#                failed persist is REPORTED. Six incidents this week were all the
#                same shape — computed and discarded, healthy from outside:
#                activation_z (no write path), the strategy library in a 24h Redis
#                key, signal_outcomes dead 104 days, eleven missing tables, a
#                read-only production, asset_embeddings_history at 0 rows.
#                Also pins compliance (#1): the emitted vocabulary is
#                UNDERWEIGHT/NEUTRAL only — a negative conditional in a long-only
#                book is a WEIGHT decision, never a direction.
python3 -m tests.test_forward_records_actually_record

# 3a-sesvicies. the page's two curves must size a position the same way
#               (2026-08-19, S-176). The Signal Performance page showed
#               "CUMULATIVE ALPHA −97.45%" on the chart and "MAX DRAWDOWN −37.31%"
#               in the stat strip — same book, one page, 60 points apart.
#               _compute_metrics builds THREE compounding loops. The POSITION_FRAC
#               correction (whose own comment names "the -94% artifact") had landed
#               on the one feeding max_drawdown and CAGR, and on NEITHER of the two
#               dated series the chart renders. **The fix reached the statistics
#               and missed the picture.** Instance, not class — the same shape as
#               eleven tables made one at a time, a probe that checked reads only,
#               and a schema_version defaulted in one writer and not its twin.
#               The third loop was found only because this guard sweeps EVERY
#               compounding loop rather than the one that prompted it.
#               ⚠️ It protects the arithmetic, not the strategy: alpha win rate is
#               26.6% and average 30d alpha −4.09%. Removing an artifact that sat
#               on top of a real problem is not fixing the problem.
python3 -m tests.test_both_equity_curves_agree_on_position_size

# 3a-septvicies. one definition of "how honest is this vector" (2026-08-19, S-178).
#                asset_embeddings_history has two writers: backfill_embedding_history.py
#                computed measured_dims / source_completeness inline and dropped thin
#                rows; the Mac daily push wrote neither and dropped nothing. One table,
#                one honest writer and one not — S-169's shape, and the daily path
#                would have filled it with vectors nobody could tell from complete ones.
#                THE NUMBER WAS ALMOST WRONG: Minimax-A's plan proposed
#                MIN_MEASURED_DIMS = 4, having read MIN_SHARED_DIMS = 4 — a different
#                quantity (cosine's refusal threshold). The write floor is 10 of 27.
#                Acked as written, the two writers would have run two thresholds, which
#                is exactly the hole the shared helpers were closing. He asked for it to
#                be confirmed from source rather than trusting his own reading; that
#                request is what caught it.
#                Pins: one owner for the floor · writers import SCHEMA_VERSION and never
#                assign it · pgvector column stays NULL so unmeasured never becomes
#                measured-zero (I1) · no always-True honesty flag (S-105 in column form)
#                · the receiver ECHOES what arrived and does not reject on mismatch,
#                because a receiver cannot know which of two deployments is right.
python3 -m tests.test_one_definition_of_honesty

# ── S-180/S-181: the T1↔T2 boundary ──────────────────────────────────────────
# A Redis read failure was indistinguishable from "the Mac has not pushed", so
# one dropped request demoted all 58 assets to T2 at once — a ~13-point score
# shift that crosses the grade AND positioning boundaries — and the hourly loop
# wrote those rows into cis_scores as the permanent record. 8 of 266 hours
# affected (3.0%), 473 rows, most recently inside the 08-19 rally window.
# Pins: the read reports WHY it is empty · the tier decision uses that status ·
# the T2 writer checks the table before shadowing a live T1 · not-knowing blocks
# the write · two views of one number refresh on one clock · no UI box promises
# an indicator no endpoint produces · no SWR window outlives what it caches.
# Each assertion verified to FAIL under a reintroduction of its bug.
python3 -m pytest tests/test_tier_integrity.py -q || {
  echo "  ✗ tier-integrity suite FAILED — do not push"; exit 1; }
echo "  ✓ tier integrity (S-180/S-181)"

# ── S-185: PostgREST filter columns must exist ───────────────────────────────
# The S-180 occupancy guard filtered cis_scores on `created_at`, which has never
# existed (it is `recorded_at`). PostgREST 400s → the helper says "could not ask"
# → the fail-closed writer declines → the hourly T2 snapshot silently wrote
# nothing for two cycles, with no error raised anywhere. A fail-closed guard
# converts a typo into a SILENT outage, so the guard needs a guard.
# Authority is schema/public_columns.json (live information_schema), NOT
# scripts/*.sql — those have drifted, and validating against them produced three
# false positives and zero true ones.
python3 -m pytest tests/test_postgrest_columns_exist.py -q || {
  echo "  ✗ a PostgREST filter names a column that does not exist — do not push"; exit 1; }
echo "  ✓ postgrest columns exist (S-185)"

# ── S-186/S-187: the macro brief ─────────────────────────────────────────────
# Pins: ONE prompt in the repo (a second one had zero callers for six weeks and
# was the file an "upgrade the prompt" request landed on first) · compliance
# rules ENFORCED not merely requested, because a P0 asked politely of a 9B local
# model is not a P0 · the receiver rejects before publishing · unmeasured inputs
# named absent, never narrated (I1 in prose) · the CDN window derived from the
# poll interval so the cache cannot silently become the freshness ceiling.
# 12 mutations, 12 caught.
python3 -m pytest tests/test_macro_brief_contract.py -q || {
  echo "  ✗ macro-brief contract FAILED — do not push"; exit 1; }
echo "  ✓ macro brief contract (S-186/S-187)"

# ── S-189: the search discount ───────────────────────────────────────────────
# `experiment_runs.dsr` existed from the day the table was created and was never
# populated once, while R70's best-of-grid Sharpe sat on an investor page with no
# multiple-testing correction. Computed: DSR 0.27 at the honest N of 216 against
# a 0.95 bar, and the observed 1.58 is BELOW the 2.38 that chance alone is
# expected to produce as the best of 216 draws. Pins: the page reports what the
# module computes · no forward promise on an investor surface · the finding
# itself, so a future re-run that "passes" stops the push instead of shipping.
python3 -m pytest tests/test_deflated_sharpe.py -q || {
  echo "  ✗ deflated-Sharpe suite FAILED — do not push"; exit 1; }
echo "  ✓ search discount (S-189)"

# ── S-191/S-192: the price source ────────────────────────────────────────────
# Asked whether the book caught the 08-19 rally, our stored CoinGecko bars said
# BTC +0.30% and Hyperliquid said +7.15%. Ours were right about the number and
# wrong about the DAY: `trade_date=2026-08-19` holds HL's 08-18 close, because
# the CoinGecko writer stamps rows with the WRITE date rather than the bar date.
# Hyperliquid ships the epoch with the candle, is not geo-blocked (Binance is,
# from Railway US — 1 of 262 panel symbols had a bar), and is the venue we will
# execute on. Pins: the date comes from the bar not the clock · a separate
# source label so two bar conventions never splice · the coverage floor blocks
# the write · the loop is actually registered.
python3 -m pytest tests/test_hyperliquid_source.py -q || {
  echo "  ✗ hyperliquid source suite FAILED — do not push"; exit 1; }
echo "  ✓ price source integrity (S-191/S-192)"

# ── S-193: ONE pinned price route ────────────────────────────────────────────
# Jazz: 交易和读取的 route 都要写死啊,不可以乱来啊 — "不然就是回测好看,实盘根本
# 没办法用,就算给你接 TradingView 和 Hyperliquid 就是浪费钱."
# The read path resolved a fallback chain while the trade path is one venue; the
# two disagreed about ETH on 08-19 by seventeen points. Pinned: tradeable symbols
# price from the venue or REFUSE — never a substitute. And the ① book may only
# hold what the venue lists (88 of the 262-name panel), because a NAV for an
# unholdable portfolio is exactly the backtest-good/live-impossible failure.
python3 -m pytest tests/test_price_route.py -q || {
  echo "  ✗ price-route suite FAILED — do not push"; exit 1; }
echo "  ✓ pinned price route (S-193)"

# ── S-194: a dead feed is not a flat day ─────────────────────────────────────
# All five paper books computed daily return as `pnl = 0.0` then a conditional
# accumulate, so "could not price" and "did not move" were the same number.
# Measured while the panel ran +23.99% over five sessions: two_layer 6/6 marks
# at 0.00%, beta_core/causal 3/6, combined+scalable stopped entirely. Nothing
# caught it because realized_vol kept rising correctly off the same data.
# One shared guard, weighted by held notional, refusing below 80%.
python3 -m pytest tests/test_mark_coverage.py -q || {
  echo "  ✗ mark-coverage suite FAILED — do not push"; exit 1; }
echo "  ✓ books refuse to mark unpriceable holdings (S-194)"

# ── S-199/S-200: the gate must finish, and T2 must not run behind a request ──
# The direct-write sweep was an unbounded recursive grep over a MOUNTED external
# volume — 0.002s in the sandbox where the volume is absent, minutes on the Mac
# where it is not. It hung a deploy. Now scoped, excluded and hard-bounded, and
# a sweep that cannot finish reports NOT-CHECKED rather than clean.
#
# T2: railway_t2_ms measured 110,390 against a 12,000 budget. Only a COMPLETED
# build writes the cache, so a build that always overruns means the cache never
# fills and every request rebuilds and is cancelled — a deadlock that served 43
# T1-only assets with macro_regime=None. T2 now precomputes off the request path
# with a real budget, exactly as T1 has for months.
python3 -m pytest tests/test_t2_off_request_path.py -q || {
  echo "  ✗ T2-off-request-path suite FAILED — do not push"; exit 1; }
echo "  ✓ T2 precomputed off the request path (S-200)"

# ── S-202: the IC-weight chain must be honest about being empty ──────────────
# `trigger_regime_fitness` returned ok=True with rows=0 for four months while
# cis_regime_fitness stayed empty, the IC multiplier could not load, and CIS
# scored every asset on NEUTRAL weights. Nothing said so — the log line read
# like a normal run. Backfilling realized_return_7d then showed the samples span
# SIX days (and one day for RISK_ON, whose five pillar ICs came out identical at
# -0.017 — a collapsed cross-section). The old floor passed on five pairs from
# one day. Pins: empty is degraded not ok · the floor counts DAYS · a skip says
# why · neutral weights announce themselves.
python3 -m pytest tests/test_ic_weight_chain.py -q || {
  echo "  ✗ IC-weight-chain suite FAILED — do not push"; exit 1; }
echo "  ✓ IC weight chain honest when empty (S-202)"

# ── S-205: bulk fan-out belongs on a paid source ─────────────────────────────
# Jazz had said this before and it was violated twice in one week: 262 symbols
# against Binance's free mirror (panel dead for days), then 232 against a free
# DEX endpoint at ~53 req/s (429 on 57 including BTC, write refused two days).
# Both were "fixed" at the symptom — a floor that blocks, a gentler pace —
# neither touched the rule. A reminder given and violated twice has to become
# something that fails a build.
# And the real lesson was cheaper than either fix: metaAndAssetCtxs returns
# mark/oracle/funding/OI for ALL 232 perps in ONE request. The 232-call loop
# existed because nobody looked for a bulk endpoint.
python3 -m pytest tests/test_source_policy.py -q || {
  echo "  ✗ source-policy suite FAILED — do not push"; exit 1; }
echo "  ✓ bulk fan-out on paid sources only (S-205)"

# ── S-197: pod aggregator guards (Strategy 3) ────────────────────────────────
# The aggregator wraps three cross-sectional legs (R46/R62/R76) inside a single
# book with three safety properties: (1) cross-pod correlation gate drops the
# LOWEST-Sharpe pod on breach (lesson #42, max |corr| < 0.30) so a structural
# surprise that turns two pods into one factor is detected as one, not three;
# (2) vol targeting at 12% ann, with the unit-test bound at 13% so the test
# itself cannot drift the target; (3) per-pod DD circuit breaker at -15% PERMANENTLY
# zeros a pod's contribution, monotonic — recovery is impossible by construction
# because a breached pod is an opinion about regime that has now been falsified.
# Pure-Python + synthetic-data smoke — sandbox-safe and offline.
python3 -m src.research.validation.tests.test_pod_aggregator_smoke || {
  echo "  ✗ pod-aggregator smoke FAILED — do not push"; exit 1; }
echo "  ✓ pod aggregator guards (S-197)"

# ── S-198: cross-asset factor tilt guards (Strategy 4) ────────────────────────
# The long-only tilt is built from three pillars (quality + momentum + low-vol)
# that share three hard properties: (1) tilt_weights NEVER produces a negative
# weight, and the bottom quartile by RANK gets exactly 1/N each so a long-only
# claim is auditable from one DataFrame; (2) PIT-safe z-score — z(t) uses only
# data through t-lag, so a target-day observation cannot influence its own rank
# and the entire claim to "no look-ahead" reduces to one assertion; (3) H3.2
# conviction sizing is hard-clipped to [0.5, 1.75], so the worst-case notional
# exposure is bounded regardless of conviction input.
# Pure-Python + synthetic-data smoke — sandbox-safe and offline.
python3 -m src.research.validation.tests.test_factor_tilt_smoke || {
  echo "  ✗ factor-tilt smoke FAILED — do not push"; exit 1; }
echo "  ✓ cross-asset factor tilt guards (S-198)"

# ── S-205: R76 strategy-2 paper-book guards (Strategy 2) ─────────────────────
# R76 is the only survivor of the cross-sectional funding-residual family
# (LEVEL=✓ / IVOL=PARTIAL / MOMENTUM=PARTIAL). Three hard properties the
# 770-day-panel verdict (gross_t=+2.06, OOS_t=+2.47, 5/6 windows positive)
# depends on: (1) the score is cross-sectionally demeaned (mean-zero per
# time) so the long/short legs balance to zero gross; (2) the target
# weights split into 3 terciles with gross=2/3 (R76 standard); (3) the
# cell constants are frozen at the validated best cell
# (5d/0bps/k=3/high_fund_long on 28-asset strict universe) so live
# execution cannot drift from the verdict.
python3 -m src.research.validation.tests.test_r76_strategy2_smoke || {
  echo "  ✗ r76-strategy-2 smoke FAILED — do not push"; exit 1; }
echo "  ✓ R76 strategy-2 paper-book guards (S-205)"

# ── S-217: simulate-paper-trade harness guards (§SIMULATION-60D, Seth 2026-08-24)
# Per user directive "继续模拟两个赚钱的策略的运行 不用60day真实记录", the 60d
# forward-clock gate on §STRATEGY-DISCIPLINE is WAIVED in favor of SIMULATED
# marks produced by simulate_paper_trade.py. This harness re-uses the same
# frozen cells as R77 (fusion) and R76 (standalone) and runs the actual L/S
# engine on real historical data. Five hard properties the simulation
# depends on: (1) score_r76 is mean-zero per time; (2) _cadence_ls_sim
# returns a Series aligned to rets.index; (3) R76 frozen cell matches
# the backtest (5d/0bps/k=3/high_fund_long on 28 assets); (4) R77 frozen
# weights match the backtest (w_R46=0.25/w_R62=0.75/w_R76=0.30); (5) the
# output directory exists.
python3 -m src.research.validation.tests.test_simulate_paper_trade_smoke || {
  echo "  ✗ simulate-paper-trade smoke FAILED — do not push"; exit 1; }
echo "  ✓ simulate-paper-trade harness guards (S-217)"

# ── S-206: a citation must point at something ────────────────────────────────
# Measured 2026-08-24: 30 S-numbers were cited in code and in this file's own
# stage banners with NO ledger entry anywhere — including nine written the same
# week. The banner above says "(S-197)"; there is no S-197. A citation nobody can
# follow is a justification that exists only inside the head of whoever wrote it.
bash scripts/check_ledger_citations.sh || {
  echo "  ✗ dangling ledger citation — do not push"; exit 1; }

# ── S-237: 规则 #8 —— 投资人可见的前端不出现实现细节 ─────────────────────────
# CLAUDE.md 硬规则 #8 写了几个月,从来没有任何东西检查它。实测 2026-08-25:
# QuantMonitor.jsx 两处上屏文本带模型名,而 App.jsx 把它渲染在主面板首屏。
# 守卫先剥注释再匹配 —— 否则一条"此处禁止模型名"的注释自己就会命中。
python3 -m tests.test_no_investor_facing_internals || {
  echo "  ✗ 规则 #8 违规 — do not push"; exit 1; }

# ── S-236: src/research 必须真的能 import ────────────────────────────────────
# py_compile 只查语法,app boot smoke 不碰 research —— 于是一个 import 就炸的模块
# 可以躺任意久。实测 2026-08-25:11 个模块 import 失败,其中 8 个是因为我在
# S-189 整份重写 deflated_sharpe 时删掉了 8 个模块依赖的名字(含 signal_factory)。
# 三值:ok / missing(已声明依赖本环境没装)/ broken(真错)。只有 broken 让构建失败。
python3 -m tests.test_research_imports || {
  echo "  ✗ src/research import 失败 — do not push"; exit 1; }

# ── S-244: 存在的测试必须真的被运行,而且调用方式要对 ────────────────────────
# S-243 的台账写着「回归测试:tests/test_one_regime_one_spelling.py(13 passed)」。
# 文件在,13 条断言全绿 —— 而 preflight 里没有一行提到它,所以它从写完那天起
# 一次也没跑过。实测 2026-08-27:tests/ 75 个文件里 9 个从未被引用,
# 合计 74 条绿断言守护空气,外加 test_factory 的 9 条红断言无声地烂着。
#
# 这条守卫的分类器我连错两次(先"有 def test_ 就算 pytest 式",再"__main__ 里
# 必须有 sys.exit"),两次都刷出几十条假阳性 —— 所以它自带合成样本负控制,
# 分类器坏了先响,不报结论。
python3 -m tests.test_every_test_is_registered || {
  echo "  ✗ 有测试文件从不被运行,或调用方式执行不到断言 — do not push"; exit 1; }

# 下面九条是 S-244 补注册的。它们此前全部存在、全部有断言、全部从不运行。
python3 -m pytest tests/test_one_regime_one_spelling.py -q || {          # S-243 回归
  echo "  ✗ 一份响应里出现了两个 regime — do not push"; exit 1; }
python3 -m pytest tests/test_regime_reaches_the_signal_feed.py -q || {
  echo "  ✗ regime 没有走到 signal feed — do not push"; exit 1; }
python3 -m pytest tests/test_outcome_canonical.py -q || {
  echo "  ✗ outcome 规范化 — do not push"; exit 1; }
python3 -m pytest tests/test_cis.py -q || {
  echo "  ✗ CIS 核心 — do not push"; exit 1; }
python3 -m tests.test_pit_replay || {                                    # S-207 自跑式
  echo "  ✗ PIT 重放守卫 — do not push"; exit 1; }
python3 -m tests.test_strategy_vector_smoke || {
  echo "  ✗ strategy vector — do not push"; exit 1; }
python3 -m tests.test_two_layer_paper_smoke || {
  echo "  ✗ two-layer paper book — do not push"; exit 1; }
python3 -m tests.test_spa_deep_links_resolve || {
  echo "  ✗ SPA 深链 — do not push"; exit 1; }

# ── S-245: 几何基底的写者 —— 单源 · 定盘 · 写前地板 ──────────────────────────
# 实测 2026-08-27:`market_state_vectors` 的 582 行里 **568 行(97.6%)混了价源**
# (229 行含 yfinance,568 行含 coingecko,两者都被 S-195/S-230 禁用于收益序列),
# 而 2025-01 之后 ohlcv_daily 有 17,876 个 symbol-day 存在 ≥2 个源,平均差 190.6bps。
# 入口是 build_l1_observations.fetch_panel() 里一句没有 source 过滤的查询 ——
# 同一天同一标的,后到的源静默覆盖先到的。
# 五个变异全部被打回,其中"地板"那条第一版是 AST 版,被 `if False:` 打穿(第九次
# 「匹配构造存在,而非可达」),改成行为验 + upsert 探针。
python3 -m tests.test_market_state_writer || {
  echo "  ✗ 几何基底写者守卫 — do not push"; exit 1; }

# ── S-247: 异常原文不得进入 HTTP 响应 ────────────────────────────────────────
# 仓库里已有 tests/test_no_stack_leakage_on_user_surfaces.py,名字写着"不泄漏栈信息",
# preflight 每次都跑、每次都绿 —— 实测它的 5 条断言【全部】在扫 dashboard/src 里的
# 厂商名,Python API 不在扫描范围内。于是 src/api/ 里 21 处把异常原文塞进
# HTTPException(detail=...) 从来没被任何东西看过(auth.py 钱包路由是无截断 str(e))。
# 名字宣称了一个属性,而没有任何东西检查它 —— S-244 的形状,落在安全面上。
# 键用"路径::表达式"而非行号:变异 A 证明行号键会因无关插行而误报,
# 而误报会训练人盲刷基线,连真新增一起吞掉。
python3 -m tests.test_exception_text_never_reaches_the_client || {
  echo "  ✗ 异常原文进入了 HTTP 响应 — do not push"; exit 1; }

# ── S-248: 战绩面板 —— 一次只用一种度量,拒绝比数字更有信息 ──────────────────
# Jazz 2026-08-27:「我们不是有几个赚钱的吗?」有,而且指对了地方。实测四条叠加:
#   ① 面板标题写「CUMULATIVE ALPHA VS BTC/SPY」,而 _compute_metrics 复利的是
#      return_pct(绝对收益,不含基准)—— 标签与数据不是一回事
#   ② 曲线用 8 天退出价,胜率用固定 30 天窗口;23 个 WIN 行里 12 个两者符号相反
#   ③ 出口价源 83/95 被禁(coingecko market_chart S-195 / yfinance 已死 S-230),
#      可信子集只有 12 行,而它的 ret30 是 +1.64% vs coingecko 的 −13.38%(差 15pp)
#   ④ regime 分组不规范化,EASING/Easing 与 RISK_ON/Risk-On 各拆成两行(差 12pp,
#      符号相反),而拼写切换发生在 2025-06-17 —— 那是时代边界,不是 regime 边界
# 变异⑤曾存活:改 payload 抑制逻辑而测试不红,因为该分支里那个值本来就是 None。
# 已补"即使算出了数也不得放出"的直接断言。
python3 -m tests.test_track_record_measures || {
  echo "  ✗ 战绩度量守卫 — do not push"; exit 1; }

# ── S-284 O fix: display_score 默认 dp 常量守住 (2026-09-04) ────────────────
# 把 dp=1 从签名默认值提到模块级 DISPLAY_SCORE_DP 常量;契约 = 默认值与常量
# 必须一致,且显示值不跨 grade band (S-252 74.97 → 74.9 不跨 75)。
python3 -m tests.test_display_score_dp || {
  echo "  ✗ display_score dp 常量守卫 — do not push"; exit 1; }

# ── S-251: 价源判活按【覆盖标的数】,不按 max(trade_date) ─────────────────────
# supabase_ohlcv_daily_freshness() 的全部查询是 `order=trade_date.desc limit 1`
# —— 全表一行,不分源不分标的。实测 2026-08-27:binance_hist 自 08-09 起每天
# 只写 BCH 一个标的,连写 19 天,于是全表 max 天天前进,而 260 个标的已经死了;
# /internal/data-freshness 照报 verdict="fresh", age_days=0.5。
# 那个探针的 docstring 写着自己是为 silent pipeline death 建的,并列了三次前科。
# 加密侧当前三个源:binance_hist DEAD · hyperliquid DEAD · coingecko 在写但被
# S-195 禁用于收益 ⇒ **没有可用价源**,而任何全局判决都会说 ok(eodhd 活着)。
# 窗口按域给:加密 3 天,TradFi 6 天 —— main.py 那段"周末会狼来了"的警告
# 正对着这个模块,我第一版全局 3 天就会在周二早上把 eodhd 报成 DEAD。
python3 -m tests.test_source_freshness || {
  echo "  ✗ 价源判活守卫 — do not push"; exit 1; }

# ── S-283: NAV 估值政策即 CI(docs/NAV_POLICY.md)─────────────────────────────
# 三个 P0 同时存在于 ① 这本"产品账本"上,而它是所有其他账本的 benchmark:
#   ① _STATE_KEY 未按 _INCEPTION_ID 分版本。Postgres 侧的 inception 过滤是对的,
#     漏的是它前面那层缓存 —— v3→v4 切换时 Redis 里旧 state 还在,
#     `state.get("weights")` 为真,受保护的 recovery 分支根本没跑。v4 第一行因此
#     从 v3 的 NAV 1.047005 起算,并对着 v3 停在 08-20 的 mark_prices 求收益,
#     把 3 天压成一个 +20.187% 的"日"收益。**守住了持久层、漏掉了先应答的那层。**
#   ② get_curve 用 last/first 而非从单位 NAV 起算。仓库里其余每一本账都写
#     `(navs[-1] - 1)`,只有 ① 用浮动基数 —— 于是发布的 −0.177% 是 12 天窗口
#     收益冒充账本收益,并且正好把被污染的第一行排除在标题之外。两个缺陷互相
#     抵消比任何一个单独存在更糟:读者看到一个像样的小数字,没有理由去看。
#   ③ 没有 elected valuation point。`sleep(24*3600)` 锚在进程启动上,Railway
#     每次 push 都重锚一次,实测 12 个 mark 间隔 10.6h–35.9h(3.38 倍)。这些行
#     标着 daily,喂给 realized_vol_30d → vol_target_scalar → gross。
#     **未选定的估值时点不是报表瑕疵,它一路走到了仓位大小。**
# 加密没有收盘,所以估值时点必须"选",不选不等于没有 —— 等于让调度器替你选。
python3 -m pytest tests/test_nav_policy.py -q || {
  echo "  ✗ NAV 估值政策守卫 — do not push"; exit 1; }

# ── S-289: 摄入只有一条 lane —— 规则 3b 不能只活在散文里 ─────────────────────
# M-118 是在规则写下之后、完全待在 minimax 自己的路径里、又建了第三个 fetcher,
# 去抓我们已经有的数据(S-276:PENDLE 820 天被重抓)。判据是**写**不是**抓**:
# 抓价格的地方很多而且大多对的(研究面板、请求路径取行情),真正的危险是持久化 ——
# **两个摄入器 = 两条看起来是同一个量、实际不是的序列**,S-273/274/275 同日三发。
# 本守卫看不见 Mac 侧,已在文件里写明作用域边界(第七次「作用域差一格」的预防)。
python3 -m tests.test_one_ingestion_lane || {
  echo "  ✗ 摄入 lane 守卫 — do not push"; exit 1; }

# ── S-289: 交接块必须能直接粘贴 ────────────────────────────────────────────
# Jazz 说过几次:git add/commit/push 行后面不能跟注释,终端认不到。反复发生的原因
# 不是没人记住,是 **CLAUDE.md 的模板自己带着注释** —— 规则在模板下面,而被复制的
# 是模板。守卫的对象因此是 CLAUDE.md 自己:散文管不住散文,测试可以。
python3 -m tests.test_handoff_commands_are_runnable || {
  echo "  ✗ 交接命令守卫 — do not push"; exit 1; }

# ── S-263: regime 标签要看【几票通过】,不只看它多新 ──────────────────────────
# S-251 上面那段修的是价源:标的数从 261 掉到 1 而探针报 fresh。同一个形状在
# regime 上又来一次,而这次连修法都是现成的却没人用:`daily_macro_regime` 这个
# VIEW 每天算出 n_obs 与 n_sources,**两个消费者都只 select d,regime**
# (beta_core_paper._regime_history / market_state_writer),把票数直接扔了。
# 实测 2026-09-01 的 Supabase:08-17/08-21/08-22 的 n_sources=1,标签自 07-27
# 起 36 天没翻过,而 _regime_history 的新鲜度检查全绿 —— 新鲜度证明的是
# "这行是今天写的",不是"这行今天被想过"。一致性由减员产生,不是由共识产生。
#
# 这条守卫里最容易写错的两处,都不是阈值:
#   · 当天那行还在填(09-01 上午 n_obs=86 vs 基线 1450 = 6%),按它判会每天
#     早上误报一次 COLLAPSED。区分"写完了"和"塌了"的不是行数,是日期。
#   · 基线必须排除近端,否则慢速塌陷把自己的基线一起拖下去,判据永不触发。
#     实测:近端 20 天中位信源数 = 1,排除近端 = 3。差别来自窗口,不来自数值。
python3 -m tests.test_regime_quorum || {
  echo "  ✗ regime 配额守卫 — do not push"; exit 1; }

# ── S-264: 我们买了什么、用了多少、哪些买了没用 ──────────────────────────────
# 2026-09-01 我告诉 Jazz「我们测不了流,没有任何持久化的流量序列」。他的回答是
# 「coingecko pro 应该是有的 …… 这点已经说过好多次了,我买了 139 刀每月的 pro api」。
# 他是对的,而且**这件事本来就写在 src/data/market/source_policy.py 里** ——
# S-205 的正文明写着 CG Pro 给 "market caps, dominance, categories, trending,
# breadth across ~17,000 assets. We pay monthly for exactly this and were using
# the free-shaped endpoints"。我没读自己 lane 的模块就断言了缺失,与 2026-08-19
# 那次(CLAUDE.md 为它加了「说不存在之前先 grep」一整段)是同一个动作。
# 实测:Analyst 档 500,000 次/月,已用 2,074 = **0.4%**。整个 session 我在为
# Supabase 免费版的 500MB 做取舍,而旁边这个付费额度几乎全新。
# 守卫测两件可机械化的事:① 付费源必须登记 entitlement + VERIFY;
# ② **摄取状态三值** —— unwired / ephemeral(调了就扔)/ persisted。
# 第三个值是实测逼出来的:/coins/categories 有调用点,但只取 16 家 VC 组合、
# 10 分钟 TTL、从不落库。「有调用点」和「有历史」是两回事,而二值把它们合并了。
python3 -m tests.test_paid_capability_is_known || {
  echo "  ✗ 付费能力登记守卫 — do not push"; exit 1; }

# ── S-265: 兜底不得抹掉自己的报警;服务层级必须可见 ──────────────────────────
# 2026-09-01 部署后 health 报 `macro_brief: missing`,而 /api/v1/macro/brief 正常
# 返回内容。两件事同时为真,因为服务的是【兜底】:Mac 生成器暗着,Railway 用
# macro-pulse 现算一份模板顶上 —— 而它生成后 `redis_set_key(_REDIS_KEY, ...)`
# **写回了 health 判活读的那把钥匙**。
#     Mac 死 → health 报 missing → 兜底跑一次 → 把自己写进 macro:brief
#            → health 变绿,而 Mac 仍然是死的
# 那次之所以看得见 missing,只是因为兜底那份 15 分钟 TTL 刚好过期。
# **一个会把自己的报警清掉的兜底,比没有兜底更危险** —— 没有它时故障是可见的,
# 有它时故障是可见的一小会儿。
# 另两处同源:四条返回路径用四种 `source` 写法(mac_mini/auto/回落/none)外加一条
# `model:"template"`,下游没有任何字段可以问「这是第几层」;而 "mac_mini" 直接出现在
# 面向用户的 /api/v1/ 响应里(规则 #8 的守卫只扫 dashboard/*.jsx —— S-262 在
# /internal/ 上发现过同一个盲区,这是它在公开 API 上的第二例)。
python3 -m tests.test_serving_tier || {
  echo "  ✗ 服务层级守卫 — do not push"; exit 1; }

# ── S-266: 代币化 RWA 面板 —— 高维对象在前,标量在后 ─────────────────────────
# Jazz 2026-09-01:「多重判断来决定股票和 etf 全市场持仓量」→「**往高维度走**」。
# HIGH_DIM_ONTOLOGY §5 的空间表里 Entity/Decision 一行写着「待定义 · frontier ·
# **内核的缺失层;从 holder/flow/治理事件起步**」——  发行方 = Entity,
# 把一只传统资产搬上链 = 它的 Decision,那只代币的链上市值 = 这个决策吸到的 flow。
# CG Pro 的 /rwas/* 正好按这个形状给数据(且明说 tokenized_market_data 反映的是
# 链上代币化市场,**不是标的的现货市场** —— 那正是「相对不影响那边」的可观测形式)。
#
# 守卫盯两件事,都不是聚合算得对不对:
#   ① **market_cap: null 不得塌成 0。** 市场数据嵌在 tokenized_market_data 里,
#      顶层没有 market_cap;取错层会拿到 250 个 null,而 sum(null→0) 会给出一个
#      「$0 全市场持仓量」并且不报错 —— 一个静默的 0 会一路流进图表。(I1)
#   ② **标量必须带着裁决一起走。** 公开来源几周内给过 $2.3B/$2.4B/$2.6B/「破 $3B」
#      四个说法,成因是口径边界、重复计暴露、背书模型、时点。一个不带成色的
#      「持仓量」是在假装这个分歧不存在。裁决 agree/dispersed/single_source/no_data。
# 五条变异全部杀死(含「未测当已测」「离散超限仍判 AGREE」「外部锚掺进计算」)。
python3 -m tests.test_rwa_panel || {
  echo "  ✗ RWA 面板守卫 — do not push"; exit 1; }

# ── S-267: 渗透率 —— 唯一跨越两个世界的比值 ──────────────────────────────────
# Jazz 2026-09-01 更正:「**链上的换手只是映射**,多少比例和资产的发行占总流通盘
# 才更重要。现在链上资产发行方其实只是相当于一个中小型券商和做市商。」
# S-266 我把 turnover 写成「流的强度」—— 错的:代币化 NVDA 换手一百次,
# NVDA 那边一股没动。换手度量的是映射层内部的活跃度,对标的完全沉默。
#
# 渗透率 = 代币化发行量 / 标的总流通盘,分子在链上、分母在传统世界。
# 实测量级 1.5–4.6 bp ⇒ 「中小型券商」的定量形式;它的**变化率**比水平有信息量。
#
# 守卫盯的是分母:data_layer.py:2951 在取不到真实市值时用 price×volume×30 兜底
# (对 F 支柱合理 —— 宁可粗糙也别把 mcap 饿成 0)。**但拿它做渗透率的分母,
# 分子精确到美元、分母是 30 倍 ADV 的猜测,得到的比例看起来完全正常而毫无意义。**
# 所以分母来源走【白名单】:新增来源必须显式获批,不是「不在黑名单就放行」。
# 判别性断言:两次调用输入数值完全相同,只有来源标签不同 → 裁决必须不同。
python3 -m tests.test_rwa_penetration || {
  echo "  ✗ 渗透率守卫 — do not push"; exit 1; }

# ── S-268: 主导率的【轨迹】,以及两条序列对齐 ────────────────────────────────
# HIGH_DIM_ONTOLOGY §5b-bis 把 ⓪ 层(流动性周期判断)称作「我们最该建的能力」,
# 判据是「在崩塌里是否把回撤削掉」。一个只知道此刻主导率 59% 的系统,
# 回答不了它任何问题 —— **拐点是轨迹的性质,不是水平的性质。**
# 而 /global 在 data_layer 里是 ephemeral:读了给页面从不落库,所以主导率
# 一天历史都没有,不是拿不到(/global/market_cap_chart 是 Analyst 档独有,
# 我们付着钱一次没调过)。
#
# 守卫盯的是【对齐】:分子(BTC 市值)与分母(全局市值)来自两个端点,
# 采样时刻不保证一致。**静默的外连接会产生一条形状对、数值错的曲线** ——
# 每隔几天用错一次分母,而主导率仍落在 50–60% 这个看起来正常的区间。肉眼查不出来。
# 这是「两个东西一个表示」的时间维版本:两条不同节奏的序列被当成一条。
python3 -m tests.test_global_history || {
  echo "  ✗ 主导率轨迹守卫 — do not push"; exit 1; }

# ── S-269: 往回走到每个标的自己的起点,不是走到一个全局的 2013 ────────────────
# Analyst 档给日线 from 2013(Basic 只给 2 年),这是深盘面板的解药 ——
# binance_hist 死了、market_state_writer 只拿到 343 天,而这里有 4,700 天。
# 但从 2013 对每个标的全量走是错的:一个 2024 上线的代币前 11 年全是空块。
#
# 守卫盯的是**何时停**,而那是这层唯一真正的判断:
#   一个空块可能是「这个标的还没上线」(该停),也可能是「数据源有洞」(不该停)。
#   **两者在一个空块上完全同形。** 以第一个空块为终止条件,遇到缺口就会把它
#   之前的全部历史静默丢掉 —— 结果是一个天数更少、但看起来完全正常的面板。
#   所以判据是【连续】MAX_EMPTY_CHUNKS 个空块;孤立的洞跨不过这个门槛。
#   变异验证:门槛改成 1 → 2 条断言立刻变红。
#
# 另一条:**要求多深与实际多深是两个字段**(S-260 同一课 —— 那次要 2022-01-01、
# 实际只拿到 343 天,而差额在任何日志里都看不见,直到有人去数行数)。
# 面板层报 p10 与最短,不只报中位数:**横截面窗口由最短的那批决定。**
python3 -m tests.test_deep_walk || {
  echo "  ✗ 深度回溯守卫 — do not push"; exit 1; }

# ── S-270: regime 的日内颗粒度 —— 标签之外还有它有多确定 ─────────────────────
# 实测 2026-09-02:cis_scores 每天写约 22.6 个小时槽,而 daily_macro_regime
# 把它压成每天一个众数。压掉的是:13/59 天(22%)日内出现 >1 种 regime,
# 其中 4 天(7%)众数占比 < 80%,最低的一天只有 62.5%。
# cis_scores 有 pillar_f/m/o/s/a、confidence、score_zscore —— **没有任何一列
# 是 regime 的置信度或边界距离**。一个 51/49 的判断和一个 95/5 的判断,
# 在下游是同一个字符串,而 ⓪ 层的拐点恰恰发生在一致度塌下去的时候。
#
# 守卫盯两条:
#   ① **一致度必须与观测数一起给。** 2/2 的「100% 一致」不是共识,是只有一个
#      投票人 —— S-263 的 n_sources 塌陷同一个陷阱:分母消失时比例假装健康。
#   ② **缺测不是一个标签。** 把 None 计进类别数会把停机说成分歧,
#      而且是往「看起来更有信息」的方向虚增。
python3 -m tests.test_regime_granularity || {
  echo "  ✗ regime 颗粒度守卫 — do not push"; exit 1; }

# ── S-271: 加密圈自己的宏观 —— 与美元宏观分层,不合并 ─────────────────────────
# Jazz 2026-09-02:「现在的 macro regime 主要判断全球、以美元资金主导的宏观,
# 需要分层细化出加密圈的宏观,这是新的边际增长。crypto 是 ai native 的 money。」
# 这解释了今天那次 GOLDILOCKS/TIGHTENING 混乱:data_layer:2410 的分类器吃的是
# CPI/GDP/利率 —— 纯美元宏观,而同期 BTC +24.6%。**两件事从来不矛盾,
# 它们是两个货币体系上的两个 regime,而我们只有一个标签描述它们两个。**
#
# 守卫盯的第一条是**这一层不发标签**,而且「不发标签」被做成可测的性质:
# 断言 label is None + 模块里不得出现加密 regime 枚举常量。发一个枚举需要
# 因 + 基础率 + OOS 存活,三样都没有 —— R76–R94 那 15 次连败正是
# 「先发明分类器、后找证据」。从五个连续量塌成六值枚举,是这条链上最贵的降维。
#
# 第二条:**「没读数」不等于「平静」。** 五维里今天只有 funding_rate 与
# btc_dominance 落了库(完备度 0.4 < 门槛 0.6),而缺的 stablecoin_supply
# 是这套框架的货币基数 —— 没有它,「加密宏观」这个词不成立。
python3 -m tests.test_crypto_macro || {
  echo "  ✗ 加密宏观守卫 — do not push"; exit 1; }

# ── S-274: 一个分位数不带窗口就不许发出去 ──────────────────────────────────
# Jazz 2026-09-02:「可以寻找各种大类资产和相对估值和相关性,还有相应历史估值分位。」
#
# 实测当天:GLD/UUP 在 1 年窗口是 **43 分位**、在 11 年窗口是 **95 分位** ——
# 同一个价格,**52 个百分点的差纯粹来自窗口选择**。一个不带窗口的「历史分位」
# 因此不是一个市场读数,是一个我们自己选出来的数。
#
# 第二条,也是更重要的一条:**spread 大不一定是数据脏,也可能是切点没找对。**
# Jazz 指出 2019 是新周期起点后,同一批数据 spread 从 0.52 掉到 0.033(robust)。
# 三个黄金比价对 2019 **之前**的分位是 100.0% —— 高于那段的每一个交易日,
# 所以那 875 天对「今天在哪」零信息量。**把它平均进来只会稀释结论**,
# 所以 `percentile_since` 把它单列而不是并入。
python3 -m tests.test_cross_asset || {
  echo "  ✗ 跨资产分位守卫 — do not push"; exit 1; }

# ── S-275: ETF 是产品,不是资产 ────────────────────────────────────────────
# Jazz 2026-09-02:「要找对资产的指数先,etf 是产品,所以你现在的逻辑不对的,
# 价格也不会对。」
#
# 实测:TradFi 面板 14 个 symbol 全部是 ETF,规范对象 0 个。TLT 按月付息 ——
# 票息是债券回报的主体,而它不在价格里;USO 是期货 ETF,展期拖累可达 −30%/年。
#
# 但「ETF 不能用」太粗:泄漏可量化,所以约束是**这个代理最多撑多长的窗口**
# (容差 2%)。GLD 撑 1260 天、TLT 126 天、USO 16 天。S-274 用了 1926/2801 天,
# 差一个数量级 —— 该条已挂 ERRATUM。
#
# 守卫里最重要的一条是我自己犯的:第一版只比 convention,GLD/TLT 判 True,
# 因为两者都是 price_return —— **而泄漏 40 vs 400,差十倍**。
# 一个标签装着两个差异巨大的状态,正是这个模块要修的形状。
python3 -m tests.test_asset_index || {
  echo "  ✗ 资产/产品守卫 — do not push"; exit 1; }

# ── S-276: 回填的基线是跨源并集,不是任一个源 ──────────────────────────────
# M-118(minimax-c)拿 binance_hist(PENDLE 2023-07-03)当基线,把 Supabase
# 已有的 coingecko(PENDLE **2021-04-28**,起始日一模一样)报成「+820 天大赢家」。
# 判别性测试证明陷阱可复现:只看 binance 会算出 +796 天。
#
# 根因不是粗心,是他读不到 Supabase。修法是给基线,不是要求更小心 ——
# /internal/data-coverage + ohlcv_symbol_coverage RPC。
python3 -m tests.test_coverage || {
  echo "  ✗ 跨 lane 覆盖基线守卫 — do not push"; exit 1; }

# ── S-283: 未知列必须拒绝,不能静默丢弃 ────────────────────────────────────
# Mac 侧 4 个 daily writer 等我开代理端点等了 18 天(risk_meter_history 自 08-15)。
# 「不许直写 Supabase」的原则是对的,但只立原则不开口子等于把对方逼回直写。
#
# 守卫的那一条:先做「挑出已知列」的过滤,一个拼错的字段(regime vs macro_regime)
# 会被悄悄丢掉 → 写进一行看起来正常、实际缺列的数据,两边都以为成功了。
# 而 risk_meter_history 用 `regime`、asset_embeddings_history 用 `macro_regime` ——
# **这正是会写错的地方**。列名取自 information_schema 实查,不抄 Mac 侧代码。
python3 -m tests.test_mac_writes || {
  echo "  ✗ Mac 代理写入守卫 — do not push"; exit 1; }

# ── S-278: 未来日期不是新鲜,是污染 ────────────────────────────────────────
# data-freshness 原本只看 ohlcv_daily 的【数据源】,而静默死亡这个失败类
# (它自己的 docstring:「已经代价三次」)大多发生在【生产者表】上。
#
# 实测 2026-09-02 三个活的故障:signal_outcomes 停 122 天(docstring 里记着
# 它曾死 80 天)· market_state_vectors 停 27 天 · risk_meter_history 有一行
# d=2099-12-31 —— **一个未来日期让 max() 判活永远报新鲜,表死了也没人知道**。
# 判活器最坏的失败不是漏报,是被它监视的数据本身关掉。
#
# 第二条:写时钟(写入者活着吗)与事件时钟(内容当期吗)必须分开 ——
# 「写入者活着但在写陈旧内容」是最阴的一种,单一个数字会把它报成健康。
python3 -m tests.test_producer_freshness || {
  echo "  ✗ 生产者判活守卫 — do not push"; exit 1; }

# ── S-279: 「没有颜色」比「是红色」更危险 ──────────────────────────────────
# Jazz 2026-09-02:「怎么都说健康,都说没问题,但就是没有做完?总发现有东西停了?」
#
# 查下来端点没撒谎 —— 它们此刻正在报 degraded/stale。真正的机制是**覆盖缺口**:
# 它们回答的是一个比「系统健康吗」小得多的问题,而名字承诺了全景。
# 实测:库里 67 张表,S-278 只看 10 张;**9 张 NAV 表只有 1 张在被判活** ——
# 而产品就是可验证的前向记录,NAV 表就是那个记录本身。
#
# 本层产出 `n_not_covered`:一个**能收敛到零的整数**(守卫数量不会收敛)。
# 清册现查 information_schema,所以明天新建的表明天就在缺口里,不靠人记得。
#
# 而覆盖不全**不把裁决压红** —— 覆盖不全会持续数周,一盏常亮的红灯和一盏
# 坏掉的灯在行为上是同一个东西,那正是这个模块要修的病。改为给裁决加范围声明。
python3 -m tests.test_watch_census || {
  echo "  ✗ 覆盖清册守卫 — do not push"; exit 1; }

# ── S-280: 跨 Python 版本的地雷 ────────────────────────────────────────────
# 沙箱 3.10.12 / Mac 3.14.3,差四个小版本,而 **preflight 是在 Mac 把门的**。
# asyncio.get_event_loop() 在 3.12 是 DeprecationWarning、3.14 是硬错 ——
# 于是一个测试在我这里绿、在把门的地方红。
#
# 硬错零容忍;datetime.utcnow()(3.12 弃用,3.14 仍可跑)走**只减不增预算**,
# 不逼一次大改,但不许新增 —— 一个不能变大的数比一句「以后要改」有用。
python3 -m tests.test_python_version_landmines || {
  echo "  ✗ Python 版本地雷守卫 — do not push"; exit 1; }

# ── S-282: 一个只进 stdout 的失败等于没有发生 ──────────────────────────────
# 查 signal_outcomes 为什么死 123 天,答案是四行代码:
#     except Exception as _e:
#         print(f"[OUTCOME] ⚠️  daily run failed: {_e}")   ← 只进 stdout
#     await _asyncio.sleep(_OUTCOME_INTERVAL_S)             ← 然后继续睡
# 循环活着、每天准时跑、每天失败,而没有任何监控知道。
#
# 实测 39 个真实循环、28 个是这个形状(第一次报 67/64 是把 _start_* 包装
# 函数也数进去了 —— 夸大动机数字,当天第二次)。已接 11 个,覆盖全部 9 张
# NAV 表的写入者;其余走**只减不增预算**。
#
# 三个状态不是一个 bool:never_ran(可能根本没被调度,market_state_vectors
# 就是)/ ok / failing(带连续次数)。**两者在 max() 上同形而修法完全不同。**
python3 -m tests.test_loop_beat || {
  echo "  ✗ 循环心跳守卫 — do not push"; exit 1; }

# ── S-288: 宁可空且标记,不可编造(规则 #9 那条 audit standing 终于清了) ────
# src/data/vc/deal_flow.py 有三个 _get_mock_*(),在 10 个返回点上把失败替换成
# 假数据。最坏的不是 402 那条,是:
#     return rounds if rounds else self._get_mock_funding_rounds()
# **一个成功但为空的响应会被替换成虚构的融资** —— 真实的「没有」变成虚构的
# 「有」。而那些假数据署了真实机构的名(Paradigm/a16z/Sony):
# 一般的假数据是噪声,**署名的假数据是关于真实公司的虚构事实**。
#
# 守卫用 tests/_source.py:code_only 剥注释与 docstring —— 说明文字里就写着
# 那些模式名,不剥会被自己的解释绊倒(当天第五次)。
python3 -m tests.test_no_fabricated_data || {
  echo "  ✗ 编造数据守卫 — do not push"; exit 1; }

# ── S-290: 未披露的成本不是零成本 ──────────────────────────────────────────
# Jazz 问「CG Analyst 有没有 VC 融资」。答:**任何档都没有**;DeFiLlama 的
# /raises 与 /emissions 实测 HTTP 402(对照组 /protocols 200/8179 证明不是网络)。
# 但 /companies/public_treasury 免费可用,而且它比 VC 轮次更适合 Entity/Decision:
# **有披露义务背书**,不是自我披露的新闻稿。
#
# 实测 BTC 180 家持 6.15% 供应,**88 家没披露成本**。把 entry_value=0 当成
# 零成本,current/entry 会变成 +∞,而那个数会一路走进「抛压强度」的排序。
# I1:未测 ≠ 0 —— 所以浮盈是 Optional,且披露率与它永远一起给
# (ETH 侧 47% 披露 ⇒ 判 thin,守卫在活数据上验证过)。
python3 -m tests.test_treasury || {
  echo "  ✗ 企业持币守卫 — do not push"; exit 1; }

# ── S-291: 付费能力必须真的被调用,否则那是白付的钱 ────────────────────────
# Jazz 2026-09-04:「我们有 coingecko analyst 是 139 刀一个月的。。。你又把他
# 忽略了?**这件事已经被失忆了很多次**,你害我浪费多少钱了!」他是对的:
# S-264 我自己写下那 14 项能力清单,此后 Entity 那批**零调用**;S-290 我还用
# 免费端点建了快照层并写下「历史买不来,今天开始攒」—— 而付费档直接给到
# 2020-08-11。我判「不可用」的依据是一次 HTTP 403,那是 **Cloudflare 1010
# 客户端指纹拦截**(裸 urllib),不是权限。换 httpx 立刻 200。
# **「我探测失败」和「我们没有这个能力」是两个状态。**
#
# 台账、注释、CLAUDE.md 都已经存在过而失忆照样发生 —— 因为那些要人主动去读。
# 这个守卫不需要谁记得它:每项付费能力要么有真实调用点,要么显式登记未接并
# 带理由,未接数只减不增。
python3 -m tests.test_paid_capability_is_used || {
  echo "  ✗ 付费能力使用守卫 — do not push"; exit 1; }

# ── S-291: 覆盖率两个口径 + 未解析不静默丢 ─────────────────────────────────
# entity_id 推导不出来(microstrategy 404 / strategy 200 —— 改名了)。
# 按家数 57%、**按持仓 88.9%** —— 差 32 个百分点,回答的是不同的问题。
# 未解析的 13 家显式列出(MARA 35,303 枚…)—— **未解析 ≠ 没有数据**。
python3 -m tests.test_treasury_decisions || {
  echo "  ✗ 决策流守卫 — do not push"; exit 1; }

# ── S-292: 一块没连线的卡,和没买这块卡是一样的 ────────────────────────────
# Jazz:「我们建了那么多东西,必须要连通呀,现在就像买了显卡、存储、网卡,
# 但是服务器不是连通的。」所以这个循环必须同时插进四个面:
#   心跳 (S-282) · 判活 (S-278) · 覆盖清册 (S-279) · Supabase 落库
# signal_outcomes 死 123 天 = 循环有了但心跳没接;market_state_vectors 停 27 天
# = 写了一次但从没上日程。**两个前车都在这张表的隔壁。**
#
# 实跑发现:BTC 按家数 19.4% / 按持仓 87.0%;ETH 按家数 61.8% / **按持仓 22.9%**
# —— 最大的 BitMine 解析不出 id。只报一个口径,这个洞看不见。
python3 -m tests.test_treasury_writer || {
  echo "  ✗ 决策流落库守卫 — do not push"; exit 1; }

# ── S-272: 判活响应必须在【顶层】给一个裁决 ─────────────────────────────────
# 2026-09-02 Jazz 问「系统检测说 ohlcv 又停了,是否如此」。查下来:
# **没有任何东西是新停的** —— coingecko 完整日连续 12 天 25/25、eodhd 33/33;
# hyperliquid(10d)与 binance_hist(13d)从 08-23/08-20 就停了,当天只是又老一天。
#
# 但 /internal/data-freshness 有**两个嵌套裁决而顶层一个都没有**:
#     by_source.verdict    "domain_without_usable_source"   ← 权威
#     ohlcv_daily.verdict  "fresh"                          ← 更浅、词更眼熟
# **两个裁决都没说错**,错的是没有字段回答「所以我该担心吗」——
# 于是告警只能在两者里挑一个,而 "fresh" 更像整体健康判断。
#
# ⚠️ 我先前把这件事说成「旧那块是 S-251 要替掉却还留着的」。**错的** ——
# 代码注释明写它是有意保留的第二个维度。没读注释就断言动机,今天不是第一次。
# 修法因此比我原说的窄:两块都留,各自声明 answers,顶层补一个权威裁决
# (与 S-265 的 tier 同一个做法:一个字段、封闭取值、放在消费者真正读的层级)。
python3 -m tests.test_freshness_has_one_top_verdict || {
  echo "  ✗ 判活顶层裁决守卫 — do not push"; exit 1; }

# ── S-252: 显示的分数不得落进比它评级更高的带 ────────────────────────────────
# 实测 2026-08-27 排行榜首屏:Aave 75.7 = A,Uniswap 75.0 = B+。
# UNI 的 raw 是 74.97 —— get_grade 给 B+ 是【对的】,而 round(74.97,1)=75.0
# 四舍五入跨过了 grade 自己遵守的那条线。数字在 A 档,徽章在 B+ 档,就在产品首屏。
# 修的方向是把【数字让下去】(74.97→74.9),不是让 grade 按显示值算 ——
# 后者等于让呈现层决定评级,四舍五入变成升级机制。
# 守卫用【穷举】0.00–100.00 每 0.01:我的第一版查错了边界,手挑的例子全过,
# 穷举当场显示 34 处矛盾、一个都没修。边界 bug 只在边界上,抽样碰不到。
python3 -m tests.test_score_never_contradicts_grade || {
  echo "  ✗ 分数与评级矛盾 — do not push"; exit 1; }

# ── S-254: paper-trade 执行器 —— 拒绝比成交更有信息 ──────────────────────────
# M-86-SHIP 的签核栏写着「Seth/Austin (execution): PENDING」,而 paper_trading/
# 目录根本不存在。三个 OOS 验证过的 spec(M-86 ④ / M-87 ② +19.94% SR+2.27 /
# M-88 ③ +29.90% SR+1.91)ship 到 Mac 侧后没有执行路径。
# 关键行为:M-86 的价源是 binance_hist,而它最近 3 天 0/212 标的(S-251)——
# 照 spec 跑会用 7 天前的价开仓,产生一条看起来正常、不可分辨的污染记录。
# 所以 panel 超龄 → BLOCKED。三值:ENTERED / SKIPPED(规则)/ BLOCKED(算不了)。
# 守卫本身是四值:第四态 NOT CHECKED —— Shadow 未挂载时不得静默报绿(S-163)。
python3 -m tests.test_spec_runner || {
  echo "  ✗ paper-trade 执行器守卫 — do not push"; exit 1; }

# ── S-258: CG Pro 深盘落库 —— 不覆盖旧数据,不伪造成交量 ─────────────────────
# get_cg_ohlc_range() 早就存在且被 /api/v1/ohlcv 调用,而 ohlcv_daily 里
# coingecko_pro_ohlc 是 0 行 —— 能力接通、被读过、从未被持久化(S-214 形状)。
# 现在紧:binance_hist 0/212、hyperliquid 0/177(S-251),加密侧无可用价源;
# 而 M-91 量过 binance_hist 天花板 343 天,M-92 用 CG Pro 拿到 1811 天。
# 最要命的一条:ohlcv_daily 唯一键是 (symbol, trade_date, source),
# on_conflict 少写 source 会让新行覆盖 48,853 行旧数据 —— 不可逆,
# 而那批行本身就是 S-195「用错端点四个月」的证据。
python3 -m tests.test_cg_pro_backfill || {
  echo "  ✗ CG Pro 回填守卫 — do not push"; exit 1; }

# ── S-227: 部署后验证器必须存在,且能分开四个状态 ────────────────────────────
# 这个关卡不跑验证器(preflight 离线),只保证它没被删/没被削掉那四个区分。
# 验证器本体在 push 之后跑:bash scripts/postdeploy_verify.sh
# ── S-220: asset_embeddings 的调度写者 ───────────────────────────────────────
# 缺陷不是 loop 坏了,是【没有 loop】。所以最要紧的一条断言是"这个写者真的被
# 调度了" —— 而它的第一版 mutation 存活:查名字出现分不出【定义】和【调用】,
# 而 31 天停摆正是一个被定义、从没被调用的写者。改成 AST 查
# create_task(_embedding_rebuild_loop())。
python3 -m tests.test_embedding_loop || {
  echo "  ✗ embedding-loop guards FAILED — do not push"; exit 1; }

# ── S-224: A 类教训补关卡 ────────────────────────────────────────────────────
# S-223 量出 26 条教训只是散文。这一批把有明显可执行形式的补上,每条都过了
# mutation 测试(其中两条第一版存活,S-216 那条被我自己的 docstring 满足 —— 
# 同一 session 第七次踩到 tests/_source.py 记录的那个失败)。
python3 -m tests.test_lesson_guards || {
  echo "  ✗ lesson guards FAILED — do not push"; exit 1; }

# ── S-223: 试错价值 = 被强制执行的那一部分 ───────────────────────────────────
# 一条只被写下来的教训,在下一个失忆的 session 里和不存在没有区别。这个关卡把
# "写下 → 强制"的脱节变成一个只能升的数字。今天 76/102。
bash scripts/check_lesson_enforcement.sh || {
  echo "  ✗ lesson enforcement regressed — do not push"; exit 1; }

echo ""
echo "✅ PREFLIGHT PASSED — imports + boots + discipline green. Safe to push."
