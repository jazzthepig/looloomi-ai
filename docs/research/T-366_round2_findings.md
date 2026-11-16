# T-366 第二轮:返工记录与实测证据(2026-11-17, lane-b)

**卡** T-366(台账 S-842)· 第二轮(返工 Seth 2026-11-13 的八条 CHANGES:§Seth-1113o 四条 + §Seth-1113q 的 ⑤–⑧)
**脚本** `docs/research/T-366_coverage.py`(已重写)· **探针** `docs/research/T-366_probe.py`
**状态**:八条里的 ①②③⑤⑥⑦⑧ 已落到脚本/探针并有实测;**④「重跑交付脚本」本轮未完成** ——
本轮上下文用量触发 lane_bot 降级保护(只放行改卡 / 情景 / 报告 / task_board / git 降落),
脚本跑完才能重生成 JSON 与报告。下一步:Mac 侧跑一次 `python3 docs/research/T-366_coverage.py`。

---

## 1. 八条 CHANGES 的状态

| # | CHANGES | 状态 | 落在哪 |
|---|---|---|---|
| ① | 「补 OI 后达 10 维」的币数:第一轮写 172 是错的 | **脚本已改**(逐币实测:OI ⇒ N₁,OI+funding ⇒ N₂) | `T-366_coverage.py::minimal_plan.n_reaching_floor_plus_oi[_plus_funding]`、缺维分组 `missing_dim_groups_after_oi_plus_funding` |
| ② | 结论 2 改成「两边都赚」 | **脚本已改**(报告渲染器明写「未覆盖组也赚钱」+ 净/\|P&L\|) | `render_report()` 第 0 节与第 3 节 |
| ③ | 数字一律从 JSON 生成 | **已改**:报告由 `render_report(res)` 从 JSON 渲染 | `T-366_coverage.py::render_report` |
| ④ | 改完重跑交付脚本 | **未完成**(降级保护) | 需 Mac 侧跑一次脚本 |
| ⑤ | 维度依据引真实写端;`[25][26]` 归写端未实现 | **已改 + 已实测**(见 §2) | `writer_probe()`、`DIMS` 表 |
| ⑥ | JSON 键与脚本对齐 | **已改**:JSON 整体由脚本重生成(第一轮那份是手改过的,含脚本没有的键、缺脚本会产出的键) | `main()` 落盘段 |
| ⑦ | 最小方案补 funding 到 72 币 + 永续/现货口径差 | **已改**:funding 取 DB∪Mac(Hyperliquid)并实测口径差 | `minimal_plan.sources`、`perp_spot_basis`、`funding_venue_diff` |
| ⑧ | §7 随机 24 币对照**或**降级 | **两条都做了**:降级有硬证据(§2.1)+ 同口径对照已实现 | `state_probe()`、`flow_control()` |

## 2. 本轮实测证据(探针跑的,可复核)

### 2.1 §7 的归属错误 —— 硬证据
`state_daily` 里第一轮引用的四个量,**`entity` 全是 `panel`**(面板级,不是币级):

| feature | 2026-11-15 | 2026-11-14 | 2026-11-13 |
|---|---|---|---|
| `breadth_above_ma50` | 0 | 0 | 0.0417 |
| `mom_20` | −0.1933 | −0.2117 | −0.1620 |
| `oi_chg_30d` | −0.2002 | −0.1805 | −0.1746 |
| `funding_7d_ann` | +0.0275 | +0.0366 | +0.0530 |

⇒ 第一轮「向量与 CIS 描述的那 24 个币恰好在最弱的一档」**归属不成立**,本轮降级为面板级读数。
`state_daily` 当天共 23 个 feature,entity 只有 `panel` 一种。

### 2.2 写端:`compute_full_vec` 不存在,真实写端是 `generate_embedding`
- 仓内 grep `compute_full_vec`:**0 命中**(脚本会全仓扫一遍并把命中列表写进 JSON)。
- 真实写端:`src/data/vector/embedder.py::generate_embedding`(:235),活路径调用点 `src/api/routers/vector.py:549`。
- `unmeasured_as_nan` 参数在 :243;**`:281` `_missing = _NAN if unmeasured_as_nan else 0.0`** ——
  缺字段填**默认值 0.0**,不是 NaN;docstring 写的却是「unmeasured is NaN, never 0」(两者不一致)。
- `MIN_MEASURED_DIMS = 10`(:584)只在 `is_thin()`(:599)里用;`pgvector_store.upsert_embeddings`(:123)
  **不调用 is_thin** ⇒ 门槛在活路径上惰性;`measured_dims`(:587)只数 NaN ⇒ 填出来的 0.0 被算成「实测」。
- `vector.py:549` 的调用**没有传** `unmeasured_as_nan` ⇒ 活路径走默认值。
- `[25][26]`:`vector.py:519-532` 从 `asset_edge_moments` 视图取 —— 本轮实测该视图 **0 行** ⇒ 写端无数据可取。

### 2.3 存量向量里的默认值污染(实测)
`asset_embeddings` 存量行的 `vec_full`:

| 币 | [11] 资金费 | [12] OI | [13] ATH | [6] 市值 | [25][26] |
|---|---|---|---|---|---|
| AAPL | 0.0 | 0.0 | 0.5 | 0.4 | null / null |
| BTC | 0.015 | 0.0 | 0.5 | 0.8077 | null / null |
| ETH | −0.002 | 0.0 | 0.5 | 0.7565 | 0.5871 / −0.4423 |

⇒ AAPL/BTC 的 [11][12][13] 是**写端默认值**(AAPL 根本没有资金费/OI);ETH 的 [25][26] 非空是**历史遗留** ——
今天视图 0 行,写端已取不到。`asset_embeddings` 表**没有** `measured_dims` / `source_completeness` 列
(实测列名:symbol, asset_class, macro_regime, schema_version, dims, vec, vec_full, computed_at, superseded_reason)
⇒ 消费方无法按「实测维数」过滤存量向量。

### 2.4 资金面:最新截面与向量长度
- `asset_flow_daily` 最新**有 vec** 的一天 = 2026-11-15,**32 个币**有 vec(前一日 35 个)。
- 存的 `vec` 列长度**不是 11**(实测 122 / 127)⇒ 做 11 维对照必须用 `q_*` 百分位列
  (`q_fund7,q_doi7,q_crowd,q_smart,q_taker7,q_mom7,q_mom30,q_vol30,q_vratio,q_turn,q_dd90`),
  维序见 `src/data/state/asset_flow.py:13-24`,百分位当截面分位、居中到 [−1,1]。

### 2.5 口径与场所(报告里要引的 file:line)
- Mac 端 payload:`/Volumes/CometCloudAI/cometcloud-local/vector_push.py:86` `_extract_assets` 读的就是
  `cis_scores_latest.json`(= CIS 宇宙)⇒ **非 CIS 的币进不了 payload** ⇒ 扩面板要扩 payload 契约或新开写路径,
  不是「扩抓取器 universe」。
- 已有 derivatives 抓取器:`src/data/market/data_layer.py:1953` `get_derivatives_map`。
- Mac 数据根:`_data/hyperliquid_funding/` 有 **94 个 `*_funding_1h.csv`**(1h 结算)、
  `research/s681/_um_daily.jsonl` 永续日线(bars=[date,o,h,l,c,qv],**不含资金费**)。
- 现价(`ohlcv_daily`,2026-11-15):BTC 65,312 / ETH 1,834.76 / SOL 72.71。

## 3. 还差什么(下一轮或 Mac 侧)

1. **跑一次 `python3 docs/research/T-366_coverage.py`** → 重生成 `T-366_traded_universe_coverage.json` 与
   `T-366_traded_universe_coverage.md`(报告由 JSON 渲染)。本轮已修的两处 bug:
   ① `funding_history` 分片拉会返回空响应(改为逐币 `limit=25`);② 零分布抽样用了 `rng.sample`
   (numpy Generator 没有该方法,改为 `rng.choice(..., replace=False)`)。
   若还有别的 traceback,请贴回来 —— 本轮受降级保护限制没能再跑。
2. 脚本跑通后,卡 `T-366` 才能从 `open` 改 `in_review`(本轮**没有**改状态,避免冒充已交付)。
3. `src/` 侧三件事本卡不能做(`forbidden_paths` 含 `src/`),需另开卡 @seth:
   ① 写端 `unmeasured_as_nan` 口径(活路径别填默认值);② `upsert_embeddings` 过 `is_thin`;
   ③ `asset_embeddings` 补 `measured_dims` / `source_completeness` 列,让消费方能过滤。
