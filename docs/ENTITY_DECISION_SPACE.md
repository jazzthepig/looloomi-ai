# Entity/Decision Space — design doc (v1, Seth, 2026-07-27)
*M-WO-7.5 deliverable: design-first for the kernel's missing object. Companion to
`docs/HIGH_DIM_ONTOLOGY.md` §5 and `ARCHITECTURE.md` §Kernel. Review → then Minimax+Seth build.*

## 0. Why this object, restated once
Everything we ship today models the REFLECTION (Asset/Quality/price). The kernel says the cause is
the **marginal decision of an influential entity, propagating through the field**. S-81 proved the
operational corollary: diffusing levels (reflections) carries nothing; **the signal to diffuse is the
CHANGE — and a Decision is exactly a change event at a point in the field.** This space makes
Decisions first-class so the propagation layer finally has the right source term `s`.

## 1. Objects & minimal schemas (build no more than this in v1)

**Entity** — an influence NODE (not a person profile; an address-cluster/institution/protocol-org/policy source).
```
entity_id    text pk          -- e.g. 'whale:0xabc…', 'inst:blackrock', 'proto:curve-gov', 'policy:fed'
kind         text             -- whale | institution | protocol_gov | policy | exchange
vec          vector(12)       -- influence coordinates (below), pgvector HNSW
meta         jsonb            -- names, addresses, links; provenance mandatory
```
**Influence coordinates (12-dim, all measurable today or near):** capital_log (可动资本量级) ·
breadth (touches how many assets) · directionality (net long/short bias) · persistence (how long
positions held) · lead_score (historical: did its moves LEAD field moves — the earned coordinate) ·
reach_attention (D4 coupling) · reach_flow (D1 coupling) · gov_power (vote/emission control) ·
opacity · activity_freq · regime_sensitivity · confidence(data quality).

**Decision** — a dated CHANGE EVENT emitted by an entity (the source term for propagation).
```
decision_id  bigserial pk
entity_id    → entity
d            date             -- PIT: known-by date, not occurred date
kind         text             -- accumulate|distribute|unlock|list|delist|gov_vote|policy|allocate
direction    float            -- signed push on the target (+risk-on / −risk-off), NEVER buy/sell language
magnitude    float            -- normalized size (fraction of target ADV or float)
targets      text[]           -- asset symbols hit directly (edge into asset space)
half_life_d  float            -- prior decay of the push (unlock ≠ policy ≠ accumulation)
provenance   jsonb            -- source url/tx/filing; NO provenance ⇒ NO row (anti-imposter)
```
**Kernel edges become rows:** Entity→Decision (fk) · Decision→Asset (targets[]) · propagation to the
rest of the field = `propagation.propagate()` over asset similarity graph with `s = Σ decisions·direction·magnitude·decay`.

## 2. What we can populate TODAY (no new vendors; graded honestly)

| Decision source | From (exists now) | Grade |
|---|---|---|
| Unlock/forward-supply overhang | `forward_supply.py` (risk, float_ratio, overhang) | A — scheduled, dated, sized |
| Positioning extremes flips | `positioning.py` positioning_pressure crossings | B — entity=crowd-aggregate, not a node |
| Whale volume anomalies | `market.py` whale_alerts (vol_ratio) | B− — detection, needs address clustering for entity_id |
| Attention ignition | trending_log D4 (rank enters top-15) | B — crowd-level decision proxy |
| Listings/delistings | exchange announcements (manual/scraper) | A — discrete, dated, high-magnitude |
| Governance votes | protocol forums/snapshots (manual v1) | B+ — low freq, high signal |
| Policy events | macro calendar (fed/cpi already fetched) | A — dated, field-wide targets |
**v1 entity set is SMALL and honest:** ~10-30 nodes (top unlock-emitters, 2-3 exchanges, policy:fed,
protocol-gov top5, crowd:aggregate as a pseudo-entity). Depth over breadth — 大象无形 applies to
entities too: model few nodes WELL.

## 3. The falsifiable first experiments (gauntlet-first, in order)
1. **E1 — unlock propagation (cheapest, data grade A):** do unlock Decisions at node X depress the
   FIELD NEIGHBOURS of X (entanglement_delta<0 spillover) beyond X itself, in the 2017+ panel?
   Event-counted (unlocks are naturally discrete events — the pseudo-replication trap is structurally
   avoided). Pass bar: neighbour-effect sign-stable per cycle + episode-t>2.
2. **E2 — lead_score is earned, not assigned:** for each entity, corr(its decision dates, subsequent
   field moves) on PIT data → becomes the `lead_score` coordinate. Entities with no lead get ~0 and
   the vector says so (I1: no fake influence).
3. **E3 — decision-sourced diffusion beats level-diffusion (the S-81 rematch):** propagate
   `s = decision pushes` instead of CIS levels; compare IC vs the refuted −0.16 baseline AND vs own-Δ.
   This is THE kernel test: if decision-diffusion carries IC where level-diffusion failed, we have
   empirically reached one step upstream. If it fails → logged, and the space stays a RISK lens
   (unlock overhang already earns its keep) — either way the object pays rent.
## 4. Boundaries (what v1 refuses)
No social-graph scraping · no per-person profiling (nodes are capital/governance structures) · no
KOL sentiment (D4 covers crowd attention) · no claimed influence without E2-earned lead_score · no
investor-facing exposure until E1/E3 clear the gauntlet (compliance: this is research infrastructure).

## 5. Build split
Seth: schemas + `entity_store.py` (pgvector, mirrors pgvector_store) + E1/E3 harness on the deep panel.
Minimax: decision extractors from the four A/B-grade sources it owns pipelines for + backfill.
Order: schema → unlock extractor → E1 → (pass?) E2 → E3. Each step = one ledger entry.
