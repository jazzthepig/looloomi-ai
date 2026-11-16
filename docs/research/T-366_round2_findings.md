# T-366 第二轮:返工记录与实测证据(2026-11-17, lane-b)

**卡** T-366(台账 S-842)· 第二轮(返工 Seth 2026-11-13 的八条 CHANGES:§Seth-1113o 四条 + §Seth-1113q 的 ⑤–⑧)
**脚本** `docs/research/T-366_coverage.py`(已重写)· **探针** `docs/research/T-366_probe.py`
**状态**:八条(①②③④⑤⑥⑦⑧)已全部落地 —— 交付脚本已重跑(`python3 docs/research/T-366_coverage.py`),
JSON 与报告(由 JSON 渲染)已重新生成,卡改 `in_review`。
本轮修掉的脚本 bug:① `bars` 是 5 元组(日期,收,高,低,qv),口径差那段按 2 元组解包会炸;
② `funding_history` 分片拉返空响应 ⇒ 改逐币 `limit=25`;③ 零分布抽样用了 numpy 没有的 `rng.sample` ⇒ 改 `rng.choice`;
④ 报告里的 `0.5%` 没转义成 `%%` ⇒ `ValueError: unsupported format character`;
⑤ `days_since(...) or 10**6` 把「今天(age=0)」当成缺失 ⇒ funding 新鲜度统计恒为 0;
⑥ `compute_full_vec` 的全仓 grep 把本脚本自己的字符串算进去 ⇒ 自指命中,已排除。
**funding 口径的关键决定**:`[11]` 资金费只有「最后一次结算距今 ≤7 天」才算实测(写端要的是**当前**资金费)——
这正是本轮与 Seth §Seth-1113o 的 per_symbol 分组对齐的那把尺子(逐组差 ≤2 个币)。

---

## 1. 八条 CHANGES 的状态

| # | CHANGES | 状态 | 落在哪 |
|---|---|---|---|
| ① | 「补 OI 后达 10 维」的币数:第一轮写 172 是错的 | **脚本已改**(逐币实测:OI ⇒ N₁,OI+funding ⇒ N₂) | `T-366_coverage.py::minimal_plan.n_reaching_floor_plus_oi[_plus_funding]`、缺维分组 `missing_dim_groups_after_oi_plus_funding` |
| ② | 结论 2 改成「两边都赚」 | **脚本已改**(报告渲染器明写「未覆盖组也赚钱」+ 净/\|P&L\|) | `render_report()` 第 0 节与第 3 节 |
| ③ | 数字一律从 JSON 生成 | **已改**:报告由 `render_report(res)` 从 JSON 渲染 | `T-366_coverage.py::render_report` |
| ④ | 改完重跑交付脚本 | **已完成**(2026-11-17 03:51 JST 跑通) | JSON + 报告已重新生成;增量重算/重渲染用同脚本的 `--recompute-plan` / `--refresh-writer` / `--render-only` |
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

1. ~~跑一次 `python3 docs/research/T-366_coverage.py`~~ —— **已跑**(2026-11-17 03:51 JST),
   `T-366_traded_universe_coverage.json` 与 `.md` 已重新生成;之后又用同脚本的
   `--recompute-plan` / `--refresh-writer` / `--render-only` 三个模式做了增量重算与重渲染
   (取数没变、只是口径或渲染器改了时不必再等一轮 12 分钟)。
2. ~~卡 `T-366` 改 `in_review`~~ —— **已改**。
3. **还差一项没测出来**:资金费的场所口径差(Binance 8h vs Hyperliquid 1h)—— DB 侧
   「近 30 天资金费」的带时间窗查询在 PostgREST 上返空 ⇒ 0 个币可配对。
   **这不是「两边没差」,是这一项没测到**;补测方式:逐币 `symbol=eq.X` 取最近 N 条再按日归一。
4. `src/` 侧三件事本卡不能做(`forbidden_paths` 含 `src/`),需另开卡 @seth:
   ① 写端 `unmeasured_as_nan` 口径(活路径别填默认值);② `upsert_embeddings` 过 `is_thin`;
   ③ `asset_embeddings` 补 `measured_dims` / `source_completeness` 列,让消费方能过滤。
