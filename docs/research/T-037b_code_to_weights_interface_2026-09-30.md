---
task: T-037b
lane: B (Seth/Austin)
parent: T-037
status: in_progress
acceptance: "对清单里代码在仓库里的每一行,写一句「哪个函数产出目标权重、输入是什么」。零模拟、零数字。"
date: 2026-09-30
---

# T-037b — 代码 → 目标权重函数 接口表

**Per JAZZ §S-440 2026-09-30.** T-037 阶段 1 清点已合入 docs/research/,S-440 复算了 −58.84% vs −7.5%
差异,**「等权面板 24 名」本身就是一个从未被度量过的风格暴露**。本表(T-037b)给 JAZZ 把所有策略接进
v0.2 阶段 1 公用记账内核 `nav_kernel(target_weights, prices, cost_bps, lag=1)` 时要用的接口表。

**零模拟、零数字。** 只考古:函数签名、模块路径、输入字段、目标权重形状。JAZZ 拿这张表做 nav_kernel
adapter,任何"重算"由 JAZZ 用同一套 nav_kernel + 守卫做,本表不预设答案。

---

## §A · spec_runner canonical entry —— 6 个 family 分派表

**唯一入口**:`paper_trading/spec_runner.py::decide(spec, panel, *, as_of, regime, n_open, features, last_rebalance)`
按 `spec_family` 分派到 family-specific 函数。**`spec_family` 不在表里 → 拒绝并提示**(spec_runner.py:335-351)。

| # | spec_family | Spec 名 | 产出函数 | 函数签名(关键输入) | 目标权重形状 |
|---|---|---|---|---|---|
| A1 | `panel_long_only` | `A17_PANEL_LONG_ONLY` (panel-wide ①) | `decide_panel_long_only` (spec_runner.py:1243) | `(spec, panel, *, as_of, regime, n_open, last_rebalance)` | panel 5 币等权(weekly rebalance, regime-blind);`spec.universe` 驱动 |
| A2 | `panel_long_only_simple_factor` | `A17_PANEL_LONG_ONLY_SIMPLE_FACTOR` (S-393 AND-gate) | `decide_panel_long_only_simple_factor` (spec_runner.py:1430) | `(spec, panel, *, as_of, regime, n_open, last_rebalance)` | A1 形态 + 每币 factor AND-gate 过滤 |
| A3 | `btc_trend_regime_ladder` | (M-152 BTT-LEX standalone ①) | `decide_btc_trend` (spec_runner.py:1126) | `(spec, panel, *, as_of, regime, n_open)` | BTC-only ① trend × regime ladder(MA200 + mom60, lag-1 × 1.30/1.15/1.00/0.80/0.00) |
| A4 | `survivors_only_lag1_book` | `M115_BOOK_B_M93_R14` (Book B) / 隐含 Book A | `decide_survivors_book` (spec_runner.py:1017) | `(spec, panel, *, as_of, regime, n_open, features)` | **2-sleeve book:① regime-gated BTC long + ④ cross-section L/S**;spec.params 决定 sleeve_R14 vs sleeve_R19 |
| A5 | `panel_long_short_jev_overlay` | `S397_JEV_LS_OVERLAY` | `decide_panel_long_short_jev_overlay` (spec_runner.py:1648) | `(spec, panel, *, as_of, regime, n_open, last_rebalance, jev_actor, jev_decision)` | A1 base + Jev multi-primitive L/S overlay(jev_actor 从 kwargs 注入) |
| A6 | `single_asset_long_short_ml_walkforward` | `ETH_LS_WALKFORWARD_V1`(🚫 **PAUSED 2026-09-29 JAZZ pivot**) | `decide_*`(具体 family 实现待复核) | — | ETH-only single-asset ML(§5b ④ 在 ETH 上的第 16 次尝试,**JAZZ 拍"wrong shape"**) |

**`Panel` 对象(spec_runner.py:730-757)是所有 decide_* 的输入本体:**
- `panel.closes: dict[symbol, dict[iso_date_str, close_price]]`(PIT-safe)
- `panel.n_symbols / panel.source / panel.last_bar / panel.age_days(as_of)`
- 内部方法:`_return_over(closes, upto, n)` —— 取最近 n 日 return(用于 trend 判定)

**`Spec` dataclass(spec_runner.py:225-328)** —— 每个 spec JSON load 成 Spec 对象,含
`spec.universe / spec.parameters / spec.target_size / spec.rebalance_cadence / spec.max_position_pct` 等。

---

## §B · Off-spec_runner —— 研究/账本/Outter 的代码路径

这些 **不** 走 spec_runner 分派表,但都有自己"产出目标权重 / 信号"的函数,接 nav_kernel 时需要单独接。

| # | 策略 | 模块路径 | 产出函数 | 函数签名 | 目标权重形状 | spec_runner wired? |
|---|---|---|---|---|---|---|
| B1 | **BETA_PLUS ②-MOM**(周频 7 份分批 + 月频 4 臂) | `src/data/signals/beta_plus_momentum.py` | `combo_signal(P)` → `tilt_targets(x, k=K)` → `compute_path(px, panel, source, end)` | `combo_signal(P: pd.DataFrame) -> DataFrame[date × coin combo 分]` <br> `tilt_targets(x: Series, k=K) -> Series[coin → w]`(只做多合计 1) <br> `compute_path(px, panel, source, end=None) -> list[dict]`(每天每臂一行,4 臂) | 24 币 panel 内按动量[14/28/90]+52w 高点排名 → z=2·rank−1−1/n → tilt(只做多、k=K) | ❌ 直接写 Supabase `beta_plus_daily`(S-428 研究路径),spec_runner 没接 |
| B2 | **TOKENIZATION_TILT ②-TOK** | 同 `beta_plus_momentum.py`(同 `compute_path`,不同 `panel_universe()`) | 同 B1 + 不同 basket | 同 B1 | 75% panel + 25% basket(LINK/ONDO/PENDLE/POLYX/AAVE/UNI/HYPE),月度再平衡,只做多 | ❌ 直接写 Supabase `tokenization_tilt_daily` |
| B3 | **M-189 (T-034) MECH_tom** | `paper_trading/hl_book.py` | `tom_targets(feats, ans, book)` | `(feats: dict[coin, dict], ans: Answers, book: dict) -> dict[coin, w]`(做多,tom_targets 主体) | HL 4 币(BTC/ETH/SOL/HYPE);w 由 `t3_base(f)` × `CROWDED_MULT` × press/defend 模式算出 | ❌(只跑 `m189_replay.py`,**不接 spec_runner**) |
| B4 | **M-189 (T-034) VOL_tom** | `paper_trading/research/m189_replay.py:109` | `tom_targets_vol_formula(feats, ans, book, target_vol_annual=0.50)` | `(feats, ans, book, target_vol_annual=0.50) -> dict[coin, w]` = `hl_book.tom_targets(feats, ans, book)` × per-coin vol multiplier | MECH_tom 输出 × vol_formula_size_multiplier 缩放 | ❌ |
| B5 | **Outter v1.1**(advisory layer,**不直接产出目标权重**) | `lane-b/research/outter/outter_v11_producer.py` | `_fetch_beta_plus(sb) + _fetch_macro_regime(sb) + _upsert(sb, as_of, overrides) + main()` | `_fetch_*(sb) -> pd.DataFrame`(只读 Supabase) <br> `main() -> dict`(写 `outter_v11_overrides_daily` 表,**只写 state + size_mult + early_exit_flag,不改 target weights**) | **(state ∈ {CONFIRMED, NEUTRAL, CONTRA}, size_mult ∈ {0.7, 1.0, 1.3}, early_exit_flag ∈ {True, False})** | ❌ Outter 是 advisory;**nav_kernel 必须接受 size_mult / early_exit 作为参数**,Outter 不参与权重计算 |
| B6 | **M-129 §5b-ter stop rule** | (尚未单独 ship;spec_runner 没显式 family;参考 S-397 spec 包含 max_dd_stop 字段) | (待 ship —— v0.2 phase 1 nav_kernel 必须原生支持 `max_dd_stop` + `capital_action_on_breach` per ALLOCATION_ARCHITECTURE_v0.2 §3 P3 + §5b-ter) | — | (any spec with DD stop;nav_kernel 要在 breach 时按 spec 字段动作) | ❌ / 🟡 部分(s397 spec 含字段,但 runner 行为待 ship) |

---

## §C · Research signal builders(用于回测,不直接 spec_runner)

这些是 spec_runner 没接、但**回测**时用的 signal → weight 函数。v0.2 重算时可以直接复用它们的 score
函数,然后统一过 nav_kernel。

| # | 模块路径 | 关键函数 | 输入 | 输出 | 服务于 |
|---|---|---|---|---|---|
| C1 | `src/research/validation/r77_r76_as_fusion_contribution.py` | `build_r76_sleeve_28(funding_daily, rets, tradeable, sign, rebal_days, cost_bps)` | `funding_daily: DataFrame[date × coin]` · `rets: DataFrame[date × coin]` · `tradeable: list[coin]` | `pd.Series[date]`(daily factor return) | R77 Leg 3(R76 资金费率残差 sleeve) |
| C2 | 同上 | `fuse3(fac_2, fac_r76, w_r76)` | 2 路 baseline + 1 路 R76 + 权重 | `pd.Series[date]`(3 路加权因子) | R77 3-leg fusion 核心 |
| C3 | `src/research/validation/r76_funding_residual_ls.py` | `score_funding_residual(funding_daily, tradeable)` | 同 C1 | `DataFrame[date × coin]`(cross-sectional demean 后的 funding) | R76 / R77 score 函数 |
| C4 | 同上 | `funding_residual_ls(score_wide, rets, k_terciles, cost_bps, rebal_days, sign)` | score wide + rets | `pd.Series[date]`(L/S daily P&L) | R76 L/S 引擎(委托 R73 的 pillar_a_level_ls) |
| C5 | `src/research/validation/r62_fragility_gated_funding.py` | `score_funding_zwide + build_w5_detector(...)` | funding + features | `Series[date]`(gated funding factor) | R62(fragility detector)→ R77 Leg 2 |
| C6 | `src/research/validation/r73_pillar_a_level_ls.py` | `pillar_a_level_ls(score_wide, rets, k_terciles, cost_bps, rebal_days, sign)` | score wide + rets | `Series[date]`(L/S P&L) | R73 / R46 / R76 共享 L/S 引擎 |
| C7 | `src/research/validation/pillar_a_ls.py` | `score_pillar_a_long(cis_long) / score_pillar_a_change(...) / pillar_a_ls(...)` | `cis_long: DataFrame[date × pillar × coin]` | `Series[date]`(pillar_A L/S factor) | R46 / R70 / R73 共享 |
| C8 | `src/research/validation/pod_aggregator.py` | `pod_aggregator(...)` | 多 pod weights + rets | `Series[date]`(aggregator factor) | Strategy 3(REFUTED on real data,但代码存) |
| C9 | `src/research/validation/cross_asset_factor_tilt.py` | `cross_asset_factor_tilt(universe, weights)` | 41-asset crypto + 17 TradFi ETFs | `Series[date]`(tilt factor) | Strategy 4(REFUTED) |
| C10 | `src/research/validation/r95_funding_ivol_residual.py` / `r96_funding_momentum_residual.py` | funding IVOL / MOMENTUM residual → L/S | funding_daily + rets | `Series[date]` | R95 / R96(PARTIAL) |

**C1-C10 都是 score → factor return(单 Series),**不是 target weights;v0.2 nav_kernel 接它们时
需要在 score 层加一步 `factor_to_weights(score, universe, k, sign, gross)` 转换成目标权重。

---

## §D · Wrappers(只加闸,不重算)

| # | 函数 | 路径 | 加什么 | 与 decide() 的关系 |
|---|---|---|---|---|
| D1 | `decide_gated` | spec_runner.py:768 | regime_quorum 5-value(OK / THIN 放行;COLLAPSED / frozen / no_baseline / no_data → SKIPPED)| 包 `decide()`,quorum 不可用 → SKIPPED |
| D2 | `decide_gated_2d` | spec_runner.py:812 | M-128d Path γ 2D gate(`composite_z` 与 `composite_z_source`)| 包 `decide_gated()`,RISK_OFF × NEUTRAL → CASH(per M-128c) |
| D3 | `should_run_today(spec, *, as_of, last_entry)` | spec_runner.py:1856 | rebalance cadence 闸 | 不在 decide 内,paper-trader loop 调 |
| D4 | `exit_due(spec, *, entry_date, as_of, ...)` | spec_runner.py:1863 | exit trigger(M-129 §5b-ter stop 等) | 同上 |

**所有 wrapper 不产出 weights;只是改 verdict / 触发 exit / 改 cadence。** v0.2 nav_kernel 必须原样吃
这些闸的输出。

---

## §E · Gaps —— 策略/账本没接 spec_runner,接 nav_kernel 时需要补

| 策略 | 现在哪里 | 缺什么 |
|---|---|---|
| **C-5 / C-12 / C-16 / C-17 ① NAV** | 仅研究(Min-C `_reports/absorb_input/nav_panel_v*.json`)| **没有可调用的 Python 函数** —— 只是历史 JSON。重算需 nav_kernel 接受 `(panel, equal_weight, rebalance_cadence, cost_bps)` 直接算 NAV |
| **M-93 单 sleeve** | `decide_survivors_book` 内部组件 | 不独立;但 `decide_survivors_book` 自身需要把 M-93 sleeve 的 weight 输出暴露(目前藏在 verdict 里)|
| **M-115 Book A vs Book B** | 同上;`spec.params` 区分 R14-Lite vs R19-Lite | 同上 |
| **M-128d 2D gate** | `decide_gated_2d` wrapper,但**没有 spec_family** | 需要建一个 `btc_trend_2d_gate` 或 `panel_long_only_2d_gate` family 接进 `decide()` 分派表 |
| **M-130 / M-131 ⓪ OVERRIDE** | research-only(M-119 engine smoke 也提过)| 需要 ship family 或专用 decide wrapper |
| **M-140 / M-146 / M-147 ⓪+④ composition** | research-only | 同上 |
| **M-152 CDCB-A v2**(BTT-LEX + CCCL 双臂)| BTT-LEX 单独 ship(`btc_trend_regime_ladder`);**CCCL 没 ship** | 需要建 `cdcb_a_v2_book` family,内含 BTT-LEX + CCCL 两条腿 |
| **R70 / R77 / R76 / R95 / R96** | research-only | 这些是 cross-section L/S shape,想 live 必须 ship 到 spec_runner |
| **Strategy 3 / Strategy 4 / R82-R94** | REFUTED,代码存档 | 不接(spec_runner 已拒) |
| **Outter v1.1** | 独立 producer | nav_kernel 必须支持 size_mult + early_exit 作为参数(S-435 fixture rejected,但 contract 不变) |
| **V7_MTF / M-95c / M-108 / M-110 / M-112** | VOIDED | 不接(M-112 same-bar leak) |
| **m147 walk-forward v2 / eth_ls_walkforward_v1** | PAUSED + archived(JAZZ 2026-09-29)| 不接 |

---

## §F · v0.2 nav_kernel 接口(per ALLOCATION_ARCHITECTURE_v0.2 §3 L2 + §3 P3)

```python
def nav_kernel(
    target_weights: dict[date, dict[coin, float]],  # 时间序列的目标权重
    prices: dict[date, dict[coin, float]],          # PIT-safe 价格
    cost_bps: float,                                 # 单边成本
    lag: int = 1,                                    # 默认 1(spec_runner 默认;M-95c 那次 0 = same-bar leak)
    size_mult: Optional[dict[date, dict[coin, float]]] = None,  # Outter advisory 输入
    early_exit_flags: Optional[dict[date, set[coin]]] = None,  # Outter advisory 输入
    max_dd_stop: Optional[float] = None,             # §5b-ter;None = 不设
    capital_action_on_breach: Optional[str] = None,  # "cash" / "flat" / spec-defined
    rebalance_cadence: int = 1,                      # 默认 daily mark
) -> dict[date, dict[coin, float]]:                 # 每日 NAV + per-coin position
    ...
```

**已有可提的内核候选:**
1. **`beta_plus_momentum._simulate`** —— S-431 已证明可逐位复现;Seth 提为公用
2. **`hl_book.simulate + apply_turnover_limits`** —— M-189 用过;trade band + gross cap 已 ship
3. **`spec_runner._return_over(closes, upto, n)`** —— return 计算公用函数

**v0.2 phase 1 三件必做(JAZZ §S-440):**
1. 提 nav_kernel 本体(`beta_plus_momentum._simulate` → 公用,带 size_mult + early_exit + max_dd_stop 三个新参数);
2. 重算 §B 25 条策略 + §C 10 个 score builder,统一过 nav_kernel;
3. 公用守卫 M-114 / regime_quorum / M-145 在 nav_kernel 输出的 NAV 上跑一次。

**这三件不属于 T-037b。** T-037b 只到"接口表"为止。

---

## §G · 卡号 + handoff

- **T-037b** 是 T-037 的扩展卡,Seth/B(我)拥有,parent=T-037。
- 不开 git(per Rule 4)。
- 不跑数字(per JAZZ §S-440)。
- 不动 `src/` / `paper_trading/`(per Rule 3 ownership);本表是**接口约定**,不是实现提案。
- 实现提议另起卡(Seth lane 拍后),按 CLAUDE.md handoff block 走 Mac-side commit。

**待 JAZZ 拍的事项:**

| Q | 问题 |
|---|---|
| Q1 | nav_kernel 三个新参数(size_mult / early_exit / max_dd_stop)的具体接口签名(本表 §F 是初步) |
| Q2 | C-5/C-12/C-16/C-17 ① NAV 重算是否要 ship 一个 `_compute_001_nav(panel, equal_weight, rebalance_cadence, cost_bps)` 公用函数 |
| Q3 | M-128d 2D gate 的 spec_family 命名(建议 `panel_long_only_2d_gate` 或 `btc_trend_2d_gate`) |
| Q4 | M-152 CCCL(动量 / 截面 / 因子哪一条腿)与 BTT-LEX 的组合是否需要 ship `cdcb_a_v2_book` family |
| Q5 | T-037 / T-037b 这套"清点 + 接口"是不是 v0.2 phase 1 唯一前置;还有哪些要先接 |

---

*Lane: B (Seth/Austin) · Status: in_progress · 验收:每行有函数 + 签名 + 输入 ✓ · 零模拟 ✓ · 零数字 ✓*
