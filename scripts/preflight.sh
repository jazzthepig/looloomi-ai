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
cd "$(dirname "$0")/.."

# ── OUTPUT DISCIPLINE (S-157, 2026-08-13) ────────────────────────────────────
# Measured before this change: 798 lines, 48s, and the app's 40-line startup
# banner printed THREE times (smoke_test, the route-shadow guard, the breaker
# suite each boot it). 21% of the output was boot noise repeating verbatim.
#
# Jazz, watching it: "preflight 不断在重复 info, 跑不到 push". He was right about
# what he saw and wrong about the cause — it was finishing, in 48s, every time.
# But you cannot tell a 48-second run from a hang when the same forty lines
# scroll past three times, so the gate had become unreadable, and an unreadable
# gate is one you start skipping. That is the same failure as a guard nobody
# runs: not wrong, just not load-bearing any more.
#
# So: QUIET WHEN GREEN, COMPLETE WHEN RED. Each suite's output is captured. On
# success we print one line with its check count. On failure we dump that
# suite's ENTIRE output and stop — the failing suite is exactly when you want
# every line, and the passing ones are exactly when you do not.
# THE GATE MUST NOT DO THE APP'S JOB (S-158). Three suites boot the FastAPI app.
# With network egress its 31 startup loops then run a real daily cycle — Moralis,
# CoinGecko Pro, Binance, the paper-book marks — so on Jazz's Mac preflight stalled
# after check 27 while finishing in 48s in a sandbox with no egress. A gate whose
# runtime depends on whether the laptop has internet is a coin flip you cannot read.
# Exported here so EVERY suite inherits it, including ones added later.
export DISABLE_BACKGROUND_LOOPS=1

_PF_T0=$(date +%s)
_PF_N=0
_PF_TIMEOUT=${PF_TIMEOUT:-180}

# A HANG MUST BE VISIBLE AND BOUNDED (S-159, 2026-08-13).
#
# The first cut of this helper captured each suite's output so a green run would
# be 52 lines instead of 798. It worked, and it introduced a worse failure: when
# a suite hung, the screen showed nothing at all, so "stuck" and "thinking" and
# "dead" were the same picture. Jazz hit it twice on the boot smoke. Making the
# gate quiet without bounding it traded 798 lines of noise for zero lines of
# signal, which is not an improvement, it is the same mistake in the other
# direction.
#
# So: the label prints BEFORE the suite runs, so the screen always names what is
# executing right now. Every suite gets a wall-clock limit. On timeout it is a
# FAILURE with whatever output it managed to produce, because a check that never
# returns has not passed — and treating it as passing is how a gate silently
# stops gating.
run() {
  local label="$1"; shift
  local out; out="$(mktemp)"
  _PF_N=$((_PF_N + 1))
  printf "  %2d ⏳ %-52s" "$_PF_N" "$label"

  "$@" >"$out" 2>&1 &
  local pid=$!
  local waited=0
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$waited" -ge "$_PF_TIMEOUT" ]; then
      kill -9 "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
      printf "\r  %2d 🔴 %-52s TIMEOUT after %ss\n" "$_PF_N" "$label" "$_PF_TIMEOUT"
      echo
      echo "════════ 🔴 TIMED OUT: $label ════════"
      echo "  (partial output — the suite never returned; raise PF_TIMEOUT to allow longer)"
      cat "$out"
      echo "════════ 🔴 TIMED OUT: $label ════════"
      rm -f "$out"
      exit 1
    fi
    sleep 1; waited=$((waited + 1))
  done
  wait "$pid"; local rc=$?

  if [ "$rc" -eq 0 ]; then
    local n; n=$(grep -c '✓' "$out" 2>/dev/null || echo 0)
    printf "\r  %2d ✓ %-52s %3s checks  %3ds\n" "$_PF_N" "$label" "$n" "$(( $(date +%s) - _PF_T0 ))"
    rm -f "$out"
  else
    printf "\r  %2d 🔴 %-52s FAILED\n" "$_PF_N" "$label"
    echo
    echo "════════ 🔴 FAILED: $label ════════"
    cat "$out"
    echo "════════ 🔴 FAILED: $label ════════"
    rm -f "$out"
    exit 1
  fi
}


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
run "import + boot smoke" env INTERNAL_TOKEN=preflight ENVIRONMENT=ci python3 scripts/smoke_test.py

# 3-ZERO. THE TREE THAT DEPLOYS IS THE TREE THAT GETS CHECKED (S-156, 2026-08-12).
#         Runs FIRST because everything below it reads the working tree, and on
#         2026-08-12 the working tree lied: store.py imported src.api.runtime_role
#         at module level while that file had never been committed. 504 checks
#         green, production down. Preflight validated the WORKING TREE; Railway
#         deploys the GIT TREE; nothing compared them. This exports HEAD and
#         resolves every src.* import inside it.
run "git tree is deployable" python3 -m tests.test_git_tree_is_deployable
run "gate does not run the app" python3 -m tests.test_the_gate_does_not_do_the_apps_job
echo "→ [3/3] discipline + schema-drift guard (philosophy compiled to CI, 2026-07-27) ..."
# 3a. strategy discipline — cause/OOS/paper/regime evidence floor on every SHIP record
run "strategy discipline" python3 -m tests.test_strategy_discipline
# 3a-bis. resilience — the 2026-07-29 P0 (Supabase saturation → 33s hangs → retry storm,
#         while /health lied "healthy"). Guards: no retry on timeout, breaker opens, fails
#         fast, RECOVERS after cooldown, 4xx doesn't trip it, health reflects reality.
run "supabase breaker" python3 -m tests.test_supabase_breaker
run "cis universe lock" python3 -m tests.test_cis_universe_lock
# 3a-bis-2. T2 fan-out bounds (2026-08-07, S-104). The lock test above bounds the
#           CALLER; this bounds the CALLEE. `/cis/universe` returned 200 for 56 min
#           while serving a payload frozen at 01:03 — the build never completed
#           because one 24h-cadence decoration branch (cg_dev: 25 coins, sem 4,
#           15s each) overran the budget and cancelled the nine branches that had
#           already succeeded. Guards: per-branch timeout, degradation reported not
#           swallowed, failures negative-cached so a down provider costs once.
run "t2 fanout bounds" python3 -m tests.test_t2_fanout_bounds
# 3a-ter. cold-start contract — the amnesia path (docs/AMNESIA_PROTOCOL.md). Every agent starts
#         every session at zero; a lesson that lives only in a 5,672-line ledger changes nothing.
run "cold start contract" python3 -m tests.test_cold_start_contract
# 3a-quater. undefined names on the serving path — a NameError on a rarely-taken branch is
#            invisible to py_compile AND to production when the caller logs a warning. That
#            combination silently killed the T2 universe fallback (2026-08-06).
run "no undefined names" python3 -m tests.test_no_undefined_names
# 3a-quinquies. neutralisation (2026-08-07, S-103). `neutralize()` was cited in 71
#               files and defined in none, so no claim of alpha had ever been
#               separated from exposure. Guards both directions: pure beta must
#               neutralise to zero, and real alpha must survive — a neutraliser
#               that strips everything would refute every strategy including a
#               working one.
run "neutralize" python3 -m tests.test_neutralize
# 3a-sexies. strategy-library durability (2026-08-07, S-105). The record library —
#            the graveyard CLAUDE.md calls the asset — spent 12 days in a 24h-TTL
#            Redis key because its Postgres migration (written 2026-07-26) was
#            never applied, so every write hit the fallback and logged a warning
#            that fired every time and therefore carried no information.
#            Guards: the fallback is COUNTED not just logged, and one failure is
#            already degraded — there is no acceptable rate of losing research.
run "strategy durability" python3 -m tests.test_strategy_durability
# 3a-septies. L0 data architecture (2026-08-07). asset_class lived on OBSERVATION rows,
#             where it actually recorded the SOURCE - 24 symbols carried conflicting
#             labels, and source determines candle convention (>1% open gaps: Crypto
#             31.3% vs DeFi 83.5%). So `where asset_class=...` was a source filter in a
#             class filter's clothing, which is how S-106 read a splice between two bar
#             conventions as market structure. Class now lives only in `assets`.
run "data architecture" python3 -m tests.test_data_architecture
# 3a-octies-2. ① beta-core book (2026-08-07, oversight review). All five books accruing
#              a forward record were long/short market-neutral - the ④ construction that
#              produced the R76-R94 graveyard - while layer ①, the FoF core AND the
#              benchmark for every other book, had ZERO forward days. Guards the product
#              book's invariants: long only, exposure in [0,1.3], the vol scalar may
#              de-lever freely but never lever past the ceiling, unmeasured inputs resolve
#              to NEUTRAL rather than to large, and the benchmark leg is structural so
#              excess is arithmetic rather than a benchmark chosen at analysis time.
run "beta core book" python3 -m tests.test_beta_core_book
# 3a-nonies. effective breadth (2026-08-08, S-115). Three ledger entries quoted
#            N/(1+(N-1)rho) as "independent bets". It is not: that formula is the
#            exact answer for equal-weight VARIANCE REDUCTION (long-only book), while
#            breadth in IR = IC*sqrt(breadth) is the correlation matrix's SPECTRUM
#            (neutral book). They diverge even when equicorrelation HOLDS - 2.99 vs
#            7.38 at rho=0.3 - so the error was never arithmetic, it was quoting a
#            breadth number without saying which book it constrains.
run "effective breadth" python3 -m tests.test_effective_breadth
# 3a-decies. storage hygiene (2026-08-08). Supabase hit 90% of its tier and the
#            obvious move was archiving rows. Measurement said otherwise: ~84 MB of
#            dead indexes plus ~128 MB of bloat from a same-day bulk UPDATE that
#            populated asset_id - autovacuum had already cleared the dead tuples, so
#            the waste was invisible to the usual check while the pages stayed fat.
#            449 -> 237 MB with zero rows archived. Guards the generalisable parts:
#            a bulk UPDATE on a large table must declare its storage cost, index
#            scan counts are evidence only when the stats are old enough, and the
#            archive order is set by REFETCHABILITY rather than by size.
run "storage hygiene" python3 -m tests.test_storage_hygiene
# 3a-undecies. state persistence (2026-08-08, S-117/S-118). A layer-③ sleeve was
#              being built on `macro_regime`, whose median run is 3 DAYS with 51%
#              of runs ≤3d — more than half its "transitions" were label chatter.
#              A causal 5-day dwell filter takes the median to 19d and makes the
#              trigger legitimate, but drops EASING↔RISK_OFF from 8/8 to 3/3.
#              Guards: the filter is CAUSAL (a centred one would leak the future and
#              become the edge), and it reports BOTH costs — sample destroyed and
#              latency added — because reporting only the smoother chart is a pitch.
run "state persistence" python3 -m tests.test_state_persistence
# 3a-duodecies. strategy intake (2026-08-08). Minimax-A asked for the service_role
#               key to write beta-strategy records. Declined; this endpoint replaces
#               it and is better on two counts. Blast radius: service_role bypasses
#               RLS on every table while a scoped token appends records and rotates
#               freely (Lesson #72 - a forged JWT passed every local check). And the
#               gate becomes unbypassable: with a raw DB key a SHIP record failing
#               the discipline floor can be written anyway, because the floor lives
#               in CI and CI is not in the write path. Here validate() runs BEFORE
#               the insert - a gate the writer can route around is a suggestion.
run "strategy intake" python3 -m tests.test_strategy_intake
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
run "regime write path" python3 -m tests.test_regime_write_path
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
run "degraded value guard" python3 -m tests.test_degraded_value_guard
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
run "compliance language" python3 -m tests.test_compliance_language
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
run "sql privilege idiom" python3 -m tests.test_sql_privilege_idiom
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
run "embedding dims carry information" python3 -m tests.test_embedding_dims_carry_information
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
run "value added dollars" python3 -m tests.test_value_added_dollars
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
run "har rv study is specified correctly" python3 -m tests.test_har_rv_study_is_specified_correctly
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
run "table columns match the code" python3 -m tests.test_table_columns_match_the_code
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
run "no stack leakage on user surfaces" python3 -m tests.test_no_stack_leakage_on_user_surfaces
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
run "metering is billable" python3 -m tests.test_metering_is_billable
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
run "moat claims are measured" python3 -m tests.test_moat_claims_are_measured
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
run "no route is shadowed" python3 -m tests.test_no_route_is_shadowed
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
run "vector schema version is single sourced" python3 -m tests.test_vector_schema_version_is_single_sourced
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
run "stale fallback survives a cold process" python3 -m tests.test_stale_fallback_survives_a_cold_process
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
run "only one process writes the record" python3 -m tests.test_only_one_process_writes_the_record
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
run "sizing cannot invert" python3 -m tests.test_sizing_cannot_invert
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
run "universe is point in time" python3 -m tests.test_universe_is_point_in_time
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
run "aum tripwire" python3 -m tests.test_aum_tripwire
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
run "fill log records the misses" python3 -m tests.test_fill_log_records_the_misses
run "beta core size smoke" python3 -m src.data.signals.tests.test_beta_core_size_smoke
run "beta core size hook smoke" python3 -m src.data.signals.tests.test_beta_core_size_hook_smoke
run "embedder v2 smoke" python3 -m src.data.vector.tests.test_embedder_v2_smoke
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
run "venue consolidation" python3 -m tests.test_venue_consolidation
# 3a-quinquies. CIS drift detector (the HYPE case, 2026-07-30): pure detection
#              logic must regress-safe; live supabase probe lives in scheduled cron,
#              not in a code gate (offline/deterministic only here).
run "cis drift detector" python3 -m tests.test_cis_drift_detector
# 3a-sexies. ⓠ REGIME OVERRIDE enforcer (2026-08-06, first cut): wraps research-side
#             m_wo_q_o1_stablecoin_gate.assign_band_hysteresis into production-shape
#             API (apply_regime_override, apply_regime_override_series). PIT-safe,
#             allows only the v1 allowed-cap set {0.0, 0.5, 1.0, 1.3}.
run "regime override enforcer" python3 -m tests.test_regime_override_enforcer
# 3a-septies. ⓠ REGIME OVERRIDE paper track (2026-08-06, parallel paper NAV under
#              enforcer). Tests pure backtest/aggregation logic; live paper runner
#              is wired into daily_runner.py post-validation (60d forward paper).
run "fusion paper regime track" python3 -m tests.test_fusion_paper_regime_track
# 3a-octies. build_l1_observations.py smoke (2026-08-07, Lesson #72 follow-up): the
#             script's --diagnose probe verifies the live Supabase key against the
#             server (the 2026-08-02 forged-key class). It cannot run inside the
#             offline gate; this test pins the script shape (imports, constants,
#             resolve_panel_source('none'), compute_panel_series, diagnose()
#             contract) so a structural regression can't reach Railway. The actual
#             network probe belongs in the scheduled cron path.
run "build l1 observations smoke" python3 -m tests.test_build_l1_observations_smoke
# 3b. contract schema echo — the drift class preflight previously couldn't see (Mac push schema
#     changed, Railway didn't follow). Prints the canonical SCHEMA_VERSION so it's in every log,
#     and fails loudly if the contract module stops importing.
python3 - <<'PY'
from src.api.contracts.cis_push import SCHEMA_VERSION
from src.data.vector.embedder import SCHEMA_VERSION as VEC_SCHEMA, ASSET_DIMS_V2
print(f"  ✓ cis_push contract SCHEMA_VERSION={SCHEMA_VERSION} · vector schema v{VEC_SCHEMA} ({ASSET_DIMS_V2}-dim)")
PY

echo ""
echo "✅ PREFLIGHT PASSED — imports + boots + discipline green. Safe to push."
