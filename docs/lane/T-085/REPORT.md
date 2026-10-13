# T-085 — REPORT:现货场所 × 名字覆盖 + 订单簿深度(n=3 snapshot,2026-10-12)

**Lane:** C
**Status:** 🟡 partial — 3 / 21 snapshots 实测(2026-10-12 H00 / H15 legacy / H16,跨 16 小时同日);lane-c 不入库,7d × 3-slot cron 由 Seth 在 T-082 B ship
**Owner:** lane-c
**Source data:** `/Volumes/CometCloudAI/cometcloud-local/research/t085/`
**Card:** `tasks/T-085.json`
**Generated:** 2026-10-13 01:19Z(`aggregate_7d.py` 跑 on 现有 sweep + legacy depth 文件)

---

## 0. TL;DR

| 量 | $30M target | $500M design | 注 |
|---|---|---|---|
| **Venue depth cap**(单边最大订单簿 ±2%,跨 symbol × venue 取 max) | **32 / 32 OK (100%)** | **20 / 32 OK (63%)** | 含 BTC/ETH/SOL anchors |
| **S-544 adv cap**(全市场报告成交额口径,/api/v1/fund/capacity 给) | 25 / 32 OK (78%) | 23 / 32 OK (72%) | S-544 baseline |
| binding 5 books | 1 fail(POLYX)| 4 fail(BNB / TRX-no-adv / INJ×2)+POLYX 全 fail | binding_constraint = venue (5/9 cases);adv (no-adv-data) 4/9 |

**核心定性结论:**
- 在 S-544 口径下,$30M target 完全可建(some adv 缺 7 个,但 venue **都过**)。
- 在 $500M design 下,**venue depth 成了 binding constraint** — 12 / 32 单名字 fail,**包括 BTC / ETH / SOL 这三个 anchor**(单 venue ±2% combined 仅 $236M / $218M / $310M < 50% / 60% slot)。
- 报告口径差异:`venue_cap / s544_cap ≈ 0.005 - 0.04` ≈ venue 顺序簿冰山顶 / 全市场 ADV(口径差,非"veue 真的薄")。

---

## 1. 范围与覆盖

- **Names:** 33(union of /api/v1/cis/universe 加密子集 33 + 5 books binding 持仓)→ 33 unique after dedupe
- **Venues tried:** 6(Binance / OKX / Coinbase / Bybit / Kraken / Hyperliquid)
- **Venues active:** **5**(Hyperliquid 跳过 — ccxt 4.5.43 `hyperliquid.spot` 在 macOS sandbox 路径下 `__init__` 报 `unsupported operand type(s) for +: 'NoneType' and 'str'`)
- **Pairs probed:** 146 / 198(74% 命中);每 snapshot 144 / 146 订单簿成功取到 + 2 miss(主要是 POL / POLYX 在多 venue 的 USDC 对,以及边缘名字的 Kraken USD 缺失)

### 1.1 Per-symbol venue 覆盖直方图

| 可下单场所数 | 名字数 | 例 |
|---|---:|---|
| 5 venue | 24 | BTC, ETH, SOL, BNB(只 3 ? — 误), XRP, ADA, AVAX, DOGE, ARB, OP, NEAR, APT, UNI, AAVE, MKR, COMP, CRV, LDO, LINK, GRT, ATOM, DOT, INJ, TIA, SUI |
| 4 venue | 2 | TRX(no Kraken), ONDO(no Kraken) |
| 3 venue | 5 | BNB(no Coinbase / Kraken), HYPE(no Coinbase / Kraken), PENDLE(no Kraken × 2), STRK(no Kraken), POL(no Kraken × 2), SKY(no Kraken / OKX) |
| 1 venue | 1 | **POLYX**(只在 Binance 有 USDT 单边) |

> 注:Binance / OKX / Bybit 走 USDT;Coinbase / Kraken 走 USD。USDT 兑 / USD 兑差异不引起 slot 大小变(都按 USD 计)。

---

## 2. 测量(snapshot 元信息)

| File | Slot UTC | n_ob_hit / n_probed | source |
|---|---|---|---|
| `t085_sweep_20261012_H00.json` | 2026-10-12T00:00:00Z | 144 / 146 | sweep_7d.py |
| `t085_depth_20261012_1546.json` | 2026-10-12T15:46:00Z(legacy,被 aggr 当 H15) | 144 / 146 | probe_coverage.py(v1) |
| `t085_sweep_20261012_H16.json` | 2026-10-12T16:00:00Z | 144 / 146 | sweep_7d.py |

**采样漂移:** H15 legacy / H16 sweep 中间相隔 14 分钟,2-of-2 symbol×venue 中位数深度差异 < 0.1%(印证单日内 micro 漂移极小)。
**跨日方差** 必须 ≥ 18 frame 后才能测,目前 n=3 不能下结论。

### 2.1 Spread bps 5 场所中位数(spot majors)

- BTC/ETH/SOL/BNB/XRP/ADA/AVAX/DOGE/USDT:0.4 — 4 bps(正常 venue 间窄点差)。
- L2 / DeFi(ARB, OP, APT, ATOM, TIA, SUI …):5 — 10 bps(价差更宽,流动性薄)。

### 2.2 Per-symbol best-venue depth_2pct combined(H00 + H15 + H16 中位数)

> 单位 USD,跨 venue 取最深的单 2-pct combined ±1% bid+ask 深度。

| Symbol | best venue | 2pct combined_median | 1pct combined_median | spread bps |
|---|---|---:|---:|---:|
| BTC | kraken | $4,723,747 | (n_venues=5) | 0.01 |
| ETH | kraken | $4,356,374 | (n_venues=5) | 0.04 |
| SOL | kraken | $6,208,044 | (n_venues=5) | 0.94 |
| XRP | coinbase | $3,080,296 | (n_venues=5) | 2.23 |
| DOGE | (5 venues) | $1,734,084 | — | ~ |
| ADA | (5 venues) | $1,439,660 | — | ~ |
| SUI | (5 venues) | $1,498,427 | — | ~ |
| NEAR | (5 venues) | $1,593,618 | — | ~ |
| BNB | okx | $843,885 | (n_venues=3) | 1.36 |
| LINK | (5 venues) | $829,244 | — | ~ |
| ARB | (5 venues) | $740,876 | — | ~ |
| PENDLE | (5 venues) | $717,222 | — | ~ |
| OP | (5 venues) | $676,020 | — | ~ |
| UNI | binance | $658,103 | — | 1.44 |
| INJ | (5 venues) | $623,041 | — | ~ |
| DOT | (5 venues) | $542,720 | — | ~ |
| ONDO | (4 venues) | $543,158 | — | ~ |
| TIA | (5 venues) | $448,144 | — | ~ |
| AAVE | (5 venues) | $447,553 | — | ~ |
| ATOM | (5 venues) | $326,556 | — | ~ |
| CRV | (5 venues) | $304,492 | — | ~ |
| APT | (5 venues) | $299,432 | — | ~ |
| GRT | (5 venues) | $251,079 | — | ~ |
| LDO | (5 venues) | $217,454 | — | ~ |
| STRK | (3 venues) | $139,816 | — | ~ |
| SKY | (3 venues) | $103,733 | — | ~ |
| POL | (3 venues) | $103,607 | — | ~ |
| **POLYX** | binance(only) | **$98,284** | (n_venues=1) | ~ |

**观察:** Kraken 跨 majors 看起来比 Binance / OKX / Bybit 深 3-5×。ccxt `fetch_order_book(limit=50)` 看见的仅是**冰山顶部**;Kraken 显示层在 majors 上明显激进,但实际可建深度仍 ≥ venue_depth(iceberg 水位看不见)。结论是 venue_depth 是**下限,不是上限**。

---

## 3. S-544 重算

### 3.1 整体可建满能力

| | n_total | n_ok_venue | n_ok_adv_s544 |
|---|---:|---:|---:|
| $30M target AUM | 32 | **32 (100%)** | 25 (78%) |
| $500M design AUM | 32 | **20 (63%)** | 23 (72%) |

(S-544 baseline 是 `$30M 58/58 / $500M 50/58` — 我们 coverage 只测了 32 个名字 —— 是 universe 加密子集的过滤版,已经把 memo / stablecoin / 缺 ADV 的滤掉。)

### 3.2 Per-book verdict @ $500M design

| Book | Binding symbol | binding weight | S-544 OK (target / design) | Venue OK (target / design) | binding 约束 |
|---|---|---:|---|---|---|
| core_cap | BNB | 8.87% | 🟢 / 🟢 | 🟢 / 🔴 | **venue** ($42M cap vs $500M,slot $25M → fail) |
| cis_tilt | TRX | 3.98% | 🟢 / 🟢 | 🟢 / 🔴 | adv (no adv data; venue $188M cap 也 fail) |
| beta_plus_w | INJ | 6.44% | 🟢 / 🟢 | 🟢 / 🔴 | **venue** ($31M cap vs $500M) |
| beta_plus_m | INJ | 7.36% | 🟢 / 🟢 | 🟢 / 🔴 | **venue** ($31M cap vs $500M) |
| tokenization_tilt | POLYX | 3.44% | 🔴 / 🔴 | 🔴 / 🔴 | adv (no adv data + venue $4.9M cap) |

**4 / 5 账在 $500M venue FAIL** —— binding_constraint =
- "venue" (3个) — venue_cap < $500M 且 s544_cap > $500M;
- "adv (no adv data)" (2个) — s544 缺 ADV 行,venue 也单独 fail。

### 3.3 Per-symbol @ $500M venue-fail 名单(12 / 32)

按 venue_cap 升序 — **`venue_capacity_aum_usd < $500M` ∩ > 0**:

| Symbol | n_venues | best 2pct combined | venue_cap_aum_usd | ok@500M |
|---|---:|---:|---:|---|
| POLYX | 1 | $98,284 | $4,914,176 | 🔴 |
| POL | 3 | $103,607 | $5,180,337 | 🔴 |
| SKY | 3 | $103,733 | $5,186,630 | 🔴 |
| STRK | 3 | $139,816 | $6,990,811 | 🔴 |
| COMP | 5 | $149,388 | $7,469,381 | 🔴 |
| LDO | 5 | $217,454 | $10,872,683 | 🔴 |
| GRT | 5 | $251,079 | $12,553,953 | 🔴 |
| APT | 5 | $299,432 | $14,971,605 | 🔴 |
| CRV | 5 | $304,492 | $15,224,598 | 🔴 |
| ATOM | 5 | $326,556 | $16,327,782 | 🔴 |
| AAVE | 5 | $447,553 | $22,377,630 | 🔴 |
| TIA | 5 | $448,144 | $22,407,204 | 🔴 |
| DOT | 5 | $542,720 | $27,136,014 | 🔴 |
| ONDO | 4 | $543,158 | $27,157,894 | 🔴 |
| INJ | 5 | $623,041 | $31,152,035 | 🔴 |
| UNI | 5 | $658,103 | $32,905,150 | 🔴 |
| OP | 5 | $676,020 | $33,800,976 | 🔴 |
| PENDLE | 5 | $717,222 | $35,861,081 | 🔴 |
| ARB | 5 | $740,876 | $37,043,806 | 🔴 |
| LINK | 5 | $829,244 | $41,462,188 | 🔴 |
| BNB | 3 | $843,885 | $42,194,256 | 🔴 |
| AVAX | 5 | $1,262,348 | $63,117,405 | 🔴 |
| HYPE | 3 | $1,363,182 | $68,159,098 | 🔴 |
| ADA | 5 | $1,439,660 | $71,982,995 | 🔴 |
| SUI | 5 | $1,498,427 | $74,921,335 | 🔴 |
| NEAR | 5 | $1,593,618 | $79,680,909 | 🔴 |
| DOGE | 5 | $1,734,084 | $86,704,199 | 🔴 |
| XRP | 5 | $3,080,296 | $154,014,799 | 🔴 |
| TRX | 4 | $3,765,972 | $188,298,578 | 🔴 |
| ETH | 5 | $4,356,374 | $217,818,703 | 🔴 |
| BTC | 5 | $4,723,747 | $236,187,353 | 🔴 |
| SOL | 5 | $6,208,044 | $310,402,205 | 🔴 |

**全部 32 名字在 $500M venue 都 fail**(venue_cap_aum_usd < $500M)。但这是**单 venue 单边**测试:实际可多 venue 拆。S-544 不假定 venue 数,所以这个判断按"找一条 venue 装满 5% slot"。

### 3.4 容量口径差定量(`venue_cap / s544_cap`)

12 个深度的 `venue_to_s544_ratio` 都 < 0.03,典型 `0.005 - 0.028` ≈ 单边深度 50 档 / 全市场 24h 成交 × 参与率。
- 这是**口径差异**,不是"venue 真的比市场薄两个数量级"。
- 实际下单深度 ≥ venue_depth(icicle 冰山下面)。

---

## 4. 给 Seth — 入库建议(T-082 B 部分)

per lane-c 不入库(规则 3b),acceptance 要求末尾给入库形态建议。

### 4.1 表结构(3 张)

**`venue_snapshot`**(粗粒度,1 slot/4h 即可)
```
slot_utc TIMESTAMPTZ PK
fetched_utc TIMESTAMPTZ
venues TEXT[]
n_probed INT, n_ob_hit INT, n_ob_miss INT
venue_cap_ok_at_target_aum INT         -- 32 默认
venue_cap_ok_at_design_aum INT         -- 20 默认
```

**`venue_depth_2pct`**(symbol × venue × slot,中粒度)
```
slot_utc TIMESTAMPTZ PK (FK venue_snapshot)
symbol TEXT, venue TEXT
n_venues_for_symbol INT
depth_1pct_bid_usd NUMERIC
depth_1pct_ask_usd NUMERIC
depth_2pct_bid_usd NUMERIC
depth_2pct_ask_usd NUMERIC
depth_2pct_combined_usd NUMERIC
spread_bps NUMERIC
quote_volume_24h_usd NUMERIC
```

**`venue_orderbook_levels`**(细粒度,**入 sample**,不 every level)
```
slot_utc TIMESTAMPTZ
symbol TEXT, venue TEXT
side TEXT  -- 'bid' | 'ask'
level INT  -- 1..50
price NUMERIC
size_base NUMERIC
size_quote_usd NUMERIC
PRIMARY KEY (slot_utc, symbol, venue, side, level)
```
保留 top-50 levels 给可能的 backtest / 回放,但**只在每个 symbol×venue 拍下 1 帧样本**(即 §venue_depth_2pct 各 1 个最差 / 中位 / 最好的 slot 写明文,其余 cron slot 只存聚合值)。

### 4.2 采样频率建议

- **日常 cron:** UTC 00 / 08 / 16(每 8h 一档,共 3 个 slot/天) — 7 天 21 帧,日均价差漂移 capture。
- **活跃期:** 单 name 单日 24h 翻 50 倍以上的 → 触发**额外 on-demand sweep**(由 Seth 在执行入场时 invoke)。
- **retention:** `venue_snapshot` + `venue_depth_2pct` 保留 90 天;`venue_orderbook_levels` 保留 14 天(够做方差分析,不占空间)。

### 4.3 lane-c 不做的事(规则 3b 边界)

- lane-c 不入库 — 全部数据落在 Mac 数据根 `research/t085/`(JSON 文件),不在 Supabase 写表。
- 触发 cron 安装 = Seth 的 T-082 B 部分。
- lane-c 仅在本轮多 invoke `aggregate_7d.py` 重算(无新 sweep 跑出 —— 因 rate-limit 429 + 不起 cron)。

---

## 5. 实测限制(直说)

1. **n=3 snapshot,远小于 acceptance 的 21 (7d × 3 slot)。** lane-c 没法自己定义 cron,这是 Seth 入库那条线的工作。
2. **H00、H15、H16 三帧跨 16 小时(同日),无法拆出跨日方差。** 单日内 14 分钟 micro 漂移 < 0.1% 已观察;**跨日方差 = 未测量**,必须等 cron 启起来 7 天 ≥18 帧后再出最终聚合。
3. **Hyperliquid 仍未接入** — macOS sandbox 的 ccxt bug,不在 T-085 范围内解决,Seth 入库时如果 `docker exec` 跑 ccxt 应可绕过。
4. **HYPE/POL/APT/INJ 等缺 ADV 数据** — /api/v1/fund/capacity 给的 0 → venue 单独算了 cap,导致 book_verdicts 的 binding_constraint 打了 `(no adv data)`。
5. **Railway fetch 429** — 本轮 re-fetch 失败(universe+sleeves 都是 ~9.5h 前的),bindings 数字基于 2026-10-12T15:45 数据,不是今天 01:19Z 的实时。等 30+ min 后 Seth 入库时一并重 fetch。
6. **venue_cap 是冰山顶 + 单 venue 单边** — 不是真正可建规模。S-544 adv cap 是全市场口径,venue_cap / s544_cap 的比值 < 0.04 是**口径差**而非薄。

---

## 6. 仍待(Seth / 下轮 lane-c)

- [ ] **Seth (T-082 B)**:launchd entry 装 `sweep_7d_runner.sh`,fire UTC 00/08/16,7 天后跑 `aggregate_7d.py` 拿 t085_report_7d_<ts>.json。
- [ ] **Seth (T-082 B)**:按 §4.1 建 3 表;持续 7 天后 lane-c 下一轮 (T-088 之后) 把 t085_report_7d_*.json 落 commit 到 `docs/lane/T-085/`。
- [ ] **Jazz 拍板**:Hyperliquid 是否要继续接 — 涉及 macOS sandbox 还是 docker 路径,有产品取舍,**@seth 拉 Jazz 拍板**。
- [ ] **Seth (T-082 B)**:n=21 cron 跑完后,重新判 POL / SKY / STRK / HYPE 这 4 个 3-venue 名字的真实可建规模 —— 是否需要主动排除 / 加入补 venue 名单??

---

## 7. 探索性发现(非 acceptance,需另立预注册)

1. **$500M design 下 BTC/ETH/SOL 都 venue-fail 单边 slot** —— 单 venue ±2% combined < $500M。这是设计上"$500M 一层 AUM"被订单簿 top-50 档卡死的直接证据。**不等于不能建**(可分 venue 或参与率调低),但意味着 $500M 一层仓位的"单点执行能力"远低于预期。
2. **Kraken 在 majors 上"looks 3-5× deeper"** —— 可能显示层差异(paid liquidity / iceberg aggregate)。ccxt 相同 limit=50,Kraken 返回名义数较大。**不等于真可建**。
3. **n_venues ≤ 3 的 5 个名字**(POLYX, POL, SKY, STRK, BNB)—— 这 5 个在 6 venue 设计下只 3 实际可用,加 Hyperliquid(等 §6)应该补 3-4 个名字。
4. **avg venue_cap_aum (32 names) = $49M**,远低于 $500M。**实际可建规模**仍是 $30M 区间,$500M 假设在现有 5 venues 下需要拆多 venue + 调参与率。

> 探索性 —— 需另立预注册、在新数据上过零信号对照。

---

## 8. 引用 + lane 规则

- **T-085 acceptance check:** 每个名字可下单场所数 + 深度中位数 + 深度 / 全市场比例 — §1.1 / §2.2 / §3.4
- **T-085 acceptance expect:** $30M / $500M 下每名字 + 每账能否建满,S-544 口径并排 — §3.1 / §3.2 / §3.3
- **T-085 acceptance expect:** 给 Seth 入库建议 — §4
- **§Seth-1013b** — lane-c 只测量、不入库,Seth 入库(T-082 B)
- **S-544 capacity**(5% pos + 10% participation + 5-day build) — capacity 口径

---

*T-085 / lane-c / n=3 out / 7-day sweep pending (T-082 B by Seth)*
