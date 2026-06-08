# UX ↔ Proposition Review — 2026-06-07

**Lens:** does the live experience deliver CometCloud's stated proposition?
Proposition (CLAUDE.md): institutional FoF + intelligence, *"built for human LPs
and autonomous AI agents equally,"* James Turrell × ONDO, *"the best interfaces
feel like installations… systems feel like living things… no tolerance for
things that feel dead."*

## Verdict

**The skin matches the proposition; the state and the soul don't yet.** The
void-black Turrell palette and typography are genuinely on-brand, but the
flagship intelligence surface cold-loads to a *dead* screen — the exact opposite
of the stated value. Most of the gap is closed by fixes already in flight
(never-empty universe, narratives, executability) once they ship, plus a
deliberate pass on "aliveness" (started below).

## Scorecard vs each pillar

| Proposition pillar | Grade | Why |
|---|---|---|
| Feels alive / nothing dead | ✗→◐ | Cold-load showed "0 assets / Unknown / $0.00M". Aliveness pass started (below). |
| Built for LPs **and** agents equally | ◐ | Agent API page nails the agent half; in-app the duality is told, not shown. |
| Institutional-grade trust | ◐ | Shell reads institutional; data layer undercuts it (zeros, −100 bug, number contradictions, public −85% panel). |
| Art / living intelligence / convergence | ✗ | Competent terminal; doesn't yet evoke an intelligence *thinking*. Narratives + macro brief are the seeds. |

## Prioritized moves

1. **Never show dead** — never-empty universe (built, pending push), fix
   cold-start latency (warm-keep / longer cache), zeros → "—".
   *Status: zeros→"—" SHIPPED (this pass); never-empty built/pending push;
   cold-start latency open.*
2. **Make it breathe** — Turrell ambient light + motion + a living regime state.
   *Status: SHIPPED (this pass) — regime banner now has a regime-keyed breathing
   glow + live pulse dot + "Calibrating" instead of dead "Unknown"; loading state
   reads "Scoring the universe" with a pulse. More surfaces TBD.*
3. **Show the duality** — in-app "view as API / one MCP call away" affordance;
   surface executability + narrative as the human face of machine data. *Open.*
4. **Earn data trust** — one source of truth for numbers, honest empty states
   (VC done), gate the −85% signal panel, show provenance/freshness. *Open.*
5. **Give the intelligence a voice** — narratives + macro brief + regime as
   first-class design elements. *Narratives built (pending push); design
   elevation open.*

## Shipped this pass (frontend, built + verified, pending git push)

- `CISWidget.jsx` — living regime banner (ambient glow, pulse, "Calibrating");
  loading state reads as the engine thinking, not a dead screen.
- `IntelligencePage.jsx` — `fmt.amount(0)` → "—" (no dead "$0.00M").

## "太AI味道" — de-AI detail audit (2026-06-07)

The root of the generic-AI feel is **uniformity**: every label is uppercase
letter-spaced mono on the same void card with the same indigo glow. Crafted
products vary treatment and hide their plumbing. Itemized:

**Fixed this pass (built, pending push):**
- Macro Brief rendered **raw `### ` markdown** literally → now parsed (h3–h6
  handler; redundant "### CometCloud Macro Brief" title dropped).
- Macro Brief leaked the internal model name **`google/gemma-4-26b-a4b`** → now
  "Looloomi AI" (also compliance rule #3: no internal tech on investor pages).
- "Intelligence · **AI Market Analysis**" → "· Market structure, live" (the
  most on-the-nose "AI" label on the page).
- "CIS v4.1 · **Real-time API** · N assets" → "· Live ·" (dropped dev jargon).
- (earlier) regime "Calibrating" + breathing glow; loading "Scoring the
  universe"; dead `$0.00M` → "—".

**Catalogued — still reading generic (recommended next):**
1. **Uppercase-mono everywhere** — "MACRO EVENTS", "VC ROUNDS", "ECONOMIC
   INDICATORS", every column head. Selectively move to sentence case + lighter
   weight; reserve uppercase for true eyebrow labels. Single biggest de-AI lever.
2. **Plumbing leaked in copy** — "COINGECKO+DEFILLAMA" pill, "RSS + CoinGecko ·
   Live", "CoinGecko · 10min", "Sources: The Block · Blockworks…". Replace with a
   single quiet "Live data" / freshness chip; vendors are our supply chain, not UX.
3. **Emoji** — flag emojis (🇺🇸🇭🇰🇨🇳) + wallet glyph. Swap flags for clean text
   codes (US/HK/CN) or inline SVG; drop the wallet emoji.
4. **Generic indigo accent** — default `#6366f1` glow + purple toggle reads
   template. Pick one distinctive brand accent.
5. **"Intelligence" overload** — "INSTITUTIONAL INTELLIGENCE" + "AI" badge +
   "Intelligence" title + "Intelligence Score" on one screen. Vary the vocabulary.
6. **Empty chip rows** — FED/10Y/VIX/DXY/CPI all "—" reads unfinished; populate
   or hide the row until there's data.
7. **"Multi-Source"** stat value — generic; name the actual edge instead.

## Next (in priority order)

- Cold-start latency on `/cis/universe` (warm-keep ping or longer cache).
- Duality affordance: "view as API" on the CIS table.
- Provenance/freshness chip ("scored Nm ago by the engine") — uses build-state.
- Gate / relabel the −85% signal-performance panel until 30d outcomes resolve.
