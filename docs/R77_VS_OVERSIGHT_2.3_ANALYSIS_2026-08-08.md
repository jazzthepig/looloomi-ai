# R77 vs OVERSIGHT §2.3 — lane analysis — 2026-08-08

*Seth. Question surfaced in task #280: "R77 lane 是 post-2023 funding-coverage sleeve — 既然
OVERSIGHT §3 P0 #2 把 3 L/S demote 了,R77 是不是 §2.3 唯一存活的 directional shape 候选?"
Short answer: **No — R77 is a ④-layer fusion cell, not a §2.3 directional candidate.
They are two distinct product roles and the §2.3 directional-shape question is still open.**
Long answer below.*

---

## 0. The two product roles

| OVERSIGHT framing | Role | Construction | Status today |
|---|---|---|---|
| §2.3 directional shape (①+③) | capture panel beta + time exposure | **long-only net**, regime-scaled, gross ∈ {0, 0.5, 1, 1.3} | **①层 live (commits 121b54c + 922d0c5)**. **③ directional sleeve = OPEN** — TREND named but not yet tested standalone |
| §3 P0 #2 demoted 3 L/S books | ④-layer pure alpha | market-neutral L/S, Σw ≈ 0 | demoted to RESEARCH RECORD (commit fc4d331); loops continue, graveyard is the asset |
| R77 multi-leg fusion cell | ④-layer locked STRATEGY_1 | w_R46=0.25 + w_R62=0.75 + w_R76=0.30, all L/S, all market-neutral | locked per `STRATEGY_PLAYBOOK.md` · frozen weights unhashed (honesty marker) |

The ①+③ direction product IS partially shipped (①layer live, ⓠ regime override wired).
The ③ **directional beta sleeve** — the part OVERSIGHT §2.3 specifically identifies as
"the only surviving shape candidate" — is NOT shipped. R77 does not fill that slot.

---

## 1. Why R77 ≠ §2.3 directional candidate

**Construction:** R77 is three market-neutral L/S sleeves fused. Each leg satisfies Σw ≈ 0
in expectation:
- **R46** = CIS quality L/S (long high CIS, short low CIS, demean'd against panel)
- **R62** = funding-z fade-the-crowd (long low-funding, short high-funding, demean'd)
- **R76** = funding residual cross-sectional demean (long negative-residual, short positive)

Sum of three market-neutral weights is still market-neutral. **R77 is structurally a ④
construction.** OVERSIGHT §2.3 says the directional shape is "long-only net, regime-scaled",
which is the opposite.

**What OVERSIGHT §2.3 actually says (verbatim):**
> "我们把'研究'和'产品'搞混了... 而 FoF 的产品是 ①+③:吃到面板 beta,并在正确时点调整总暴露。
> 它不需要广度、不需要选股 alpha、不需要预测顶部 — 它需要一个正确的基准、一个可靠的暴露规则,
> 和时间。三样我们都有能力立刻开始。"

And §7.2 on scalable_paper demotion:
> "scalable_paper ... TREND sleeve is the only OVERSIGHT §2.3-surviving shape candidate
> for a DIRECTIONAL beta sleeve (not this market-neutral construction)"

The directional candidate is the **TREND sleeve** — multi-horizon TSMOM (CTA engine),
net-long by construction, capacity-scalable, no crowding. R77 doesn't contain TREND.

---

## 2. Why R77's role is still valid (and locked)

R77 is the locked STRATEGY_1 in STRATEGY_PLAYBOOK per memory `[§STRATEGY-2-DEFERRED]`:
- gross_t=+3.10 · OOS_t=+3.61 · maxDD=−8.91% · Sharpe=+2.06
- frozen weights w_R46=0.25 / w_R62=0.75 / w_R76=0.30
- 12-test smoke test (deb97d0) confirms layered honesty disclosure

This is a **④-layer product candidate**, not the ③ direction product. Both can ship in
the final FoF — they are orthogonal roles:
- ①layer = hold the panel, capture beta
- ③direction = time the exposure (long-only directional sleeve, TBD)
- ④alpha = market-neutral L/S excess (R77 = locked candidate)

The final FoF product is the sum: ① + ③ + ④. Demoting 3 L/S books was about **not
shipping as if they were the product** when they are ④ candidates, not the product itself.
R77 has a different status: it's a vetted ④ candidate with a frozen cell and a SHIP-eligible
construction.

---

## 3. What's still missing — the §2.3 directional-shape open question

**A TREND-only directional sleeve** has not been built or measured. The scalable_paper
TREND leg exists (per STATUS docstring) but lives inside a market-neutral 3-sleeve blend,
where its net direction is cancelled by the L/S FACTOR + CARRY legs. Pulling TREND out
standalone, with regime-scaled gross in {0, 0.5, 1, 1.3}, would be the §2.3 candidate.

This is the same shape as the 12-attempt graveyard R82/R83/R85/R86/R87/R88/R89/R90/R91/
R92/R93/R94 (memory `[R94 Directional Crypto Beta Refuted]`) — all directional shapes
on the 731-day panel REFUTED. The 731-day panel is bear-dominated (per `[§STRATEGY-2-DEFERRED]`
structural finding). **The lever is panel length, not shape** — until §OHLCV-EXTENSION
delivers the 11yr panel, any directional attempt is sunk-cost.

So:
- R77 (④ fusion) = ready, locked
- §2.3 (③ directional) = open, blocked by §OHLCV-EXTENSION
- ① layer (① beta) = live, forward-clock 1+ days

---

## 4. Recommendation to R77 lane

**R77 module (deb97d0) is correct for its role.** The layered honesty disclosure (full 731d,
funding-coverage window, frozen-weights unhashed marker, deferred 11yr disclosure) is
exactly what §2.1 / §2.2 / §7.2 demand. Don't change anything in the R77 module for
§2.3 purposes — that would be a category error.

**The §2.3 directional-shape work is a DIFFERENT task**, owned by whoever picks up
§OHLCV-EXTENSION first. Until that lands:
- Don't try to retrofit R77 to be directional (it's structurally L/S)
- Don't propose R77 as the §2.3 surviving candidate (the candidate is TREND sleeve,
  currently living inside scalable_paper's 3-sleeve blend, not pulled out standalone)
- Don't re-litigate STRATEGY_1 (R77 is locked, that's the right cell)

**The §2.3 question is OPEN and that's OK.** It's blocked by the same thing blocking
12 other directional attempts: panel length. The discipline of NOT filling the slot
with the wrong shape is itself a §P2 claim.

---

## 5. Source-of-truth chain

| Claim | Cite this |
|---|---|
| R77 is ④-layer L/S fusion | `src/research/validation/r77_multicycle_revalidation.py` lines 111-113 (frozen weights) + R76/R62/R46 sleeve definitions |
| R77 is locked STRATEGY_1 | memory `[§STRATEGY-2-DEFERRED]` · R77 cell at w_R46=0.25/w_R62=0.75/w_R76=0.30, Sharpe +2.06 |
| §2.3 directional shape = TREND | `OVERSIGHT_2026-08.md` §2.3 + §7.2 (scalable_paper STATUS docstring) |
| 12 directional attempts all REFUTED | memory `[R94 Directional Crypto Beta Refuted]` + `[§STRATEGY-2-DEFERRED]` |
| Panel length is the lever | memory `[§STRATEGY-2-DEFERRED]` structural finding · §OHLCV-EXTENSION in MEMORY |
| ① layer is the ① product (not R77) | `OVERSIGHT_2026-08.md` §0 + §3 + commit 121b54c |

---

*Analysis prepared by Seth, 2026-08-08, per task #280 ("都做啊"). R77 module unchanged;
recommendation is to NOT change it for §2.3 purposes. The §2.3 slot stays OPEN pending
§OHLCV-EXTENSION.*
