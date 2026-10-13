# T-085 — REPORT:现货场所 × 名字覆盖 + 订单簿深度(n=3 snapshot,2026-10-13)

**Lane:** C
**Status:** 🟡 partial — 3/21 snapshots 在 2026-10-12 一日内(H00,H15 legacy,H16);完整 7d cron 在 2026-10-13 → 10-19 每 UTC 00/08/16 各 fire 一次后跑 aggregate_7d.py 即出最终聚合。
**Owner:** lane-c
**Source data:** `/Volumes/CometCloudAI/cometcloud-local/research/t085/`
**Card:** `tasks/T-085.json`

---

## 0. TL;DR

| 量 | $30M target | $500M design | 注 |
|---|---|---|---|
| **Venue depth cap**(可下单场所全选) | 32 / 32 OK (100%) | 20 / 32 OK (63%) | 单边最大订单簿 ±2% USD |
| **S-544 adv cap**(全市场报告成交额口径) | 25 / 32 OK (78%) | 23 / 32 OK (72%) | 来自 /api/v1/fund/capacity |
| 5 本账 binding | binding = S-544 adv 缺数据 5 个 (HYPE / POL / APT / INJ / ONDO),POLYX 在 tokenization_tilt 全 fail | 4 / 5 binding = venue (BNB / TRX / INJ twice / POLYX 全 fail) | venue_cap / s544_cap ratio 0.005 — 0.028 |

核心定性结论:在 S-544 口径上,$30M target 完全可建;$500M design 时,**场所深度成了 binding constraint 而不是市场 ADV**。这是新增信息 — 之前 T-082 阶段只有 ADV 估算。

---

## 1. 范围与覆盖

- **Names:** 33(union of /api/v1/cis/universe 加密子集 + 5 books binding 持仓)
- **Venues tried:** 6(Binance / OKX / Coinbase / Bybit / Kraken / Hyperliquid)
- **Venues active:** 5(Hyperliquid 跳过 — ccxt `hyperliquid.spot` 在 macOS sandbox 路径下 `__init__` 报 `unsupported operand type(s) for +: 'NoneType' and 'str'`)
- **Pairs probed:** 146 / 198(74% 命中);每 snapshot 144 / 146 订单簿成功取到 + 2 miss(主要是 POL / POLYX 在多 venue 的 USDC 对,以及边缘名字的 Kraken USD 缺失)

### 1.1 Per-symbol venue 覆盖直方图

| 可下单场所数 | 名字数 | 例 |
|---|---|---|
| 5 venue | 24 | BTC, ETH, SOL, BNB, XRP, ADA, AVAX, DOGE, ARB, OP, NEAR, APT, UNI, AAVE, MKR, COMP, CRV, LDO, LINK, GRT, ATOM, DOT, INJ, TIA, SUI |
| 4 venue | 2 | (Coinbase 没有 USD 对的) |
| 3 venue | 5 | HYPE, ONDO, PENDLE, STRK, POL, SKY |
| 1 venue | 1 | POLYX(只在 Binance 有 USDT 单边深度) |

---

## 2. 测量(实测,n=3 snapshot)

### 2.1 snapshot 元信息

| File | Slot UTC | n_ob_hit / n_probed | source |
|---|---|---|---|
| t085_sweep_20261012_H00.json | 2026-10-12T00:00:00Z | 144 / 146 | sweep_7d.py |
| t085_depth_20261012_1546.json | 2026-10-12T15:46:00Z (synthesized H15) | 144 / 146 | legacy(v1) |
| t085_sweep_20261012_H16.json | 2026-10-12T16:00:00Z | 144 / 146 | sweep_7d.py |

**采样漂移:** H15 (legacy) 与 H16 (sweep) 中间相隔 14 分钟,2-of-2 symbol×venue 中位数深度差异 < 0.1%(印证单日内 micro 漂移极小)。**跨日方差靠后续 18 个 snapshot 才能测**,目前 n=3 不能下结论。

### 2.2 Spread bps 5 场所中位数(spot majors)

BTC/ETH/SOL/BNB/XRP/ADA/AVAX/DOGE/USDT:0.4 — 4 bps(正常 venue 间窄点差)。

L2 / DeFi(ARB, OP, APT, ATOM, TIA, SUI …):5 — 10 bps(价差更宽,流动性薄)。

---

## 3. S-544 重算

### 3.1 整体可建满能力

| | n_total | n_ok_venue | n_ok_adv_s544 |
|---|---|---|---|
| $30M target AUM | 32 | 32 (100%) | 25 (78%) |
| $500M design AUM | 32 | 20 (63%) | 23 (72%) |

(S-544 baseline 是 `$30M 58/58 / $500M 50/58` — 我们 coverage 只有 32,所以看起来 v2 在数量上"少",但**已覆盖 CIS universe 的全部主流名字**,只是滤掉了非主流 TRC-20 / meme / stablecoin 等。)

### 3.2 Per-book verdict @ $500M

| Book | Binding symbol | S-544 ok | Venue ok | venue/s544 ratio | binding constraint |
|---|---|---|---|---|---|
| core_cap | BNB | ✅ | ❌ | 0.0045 | venue(深 84 万 USD vs S-544 假定的 93 亿 cap) |
| cis_tilt | TRX | ✅ | ❌ | (no adv data) | S-544 adv 缺数据 / venue 也卡 |
| beta_plus_w | INJ | ✅ | ❌ | 0.027 | venue |
| beta_plus_m | INJ | ✅ | ❌ | 0.027 | venue |
| tokenization_tilt | POLYX | ❌ | ❌ | (no adv data) | 两侧都 fail,S-544 + venue 一致拒绝 |

`venue / s544 ratio ≈ 0.005 — 0.028` 看起来 venue 比 S-544 小两个数量级 — **这不是"场所真的那么薄",而是 venue_cap 与 s544_cap 的口径不同**:
- `venue_cap = max_venue_depth_2pct × 5d × 1/position_pct × 1 (one_side_only)` = 单边 ice-berg 可见部分
- `s544_cap = adv × participation × build_days / position_pct` = **整个市场 ADV**(多场所聚合)
- 中间比例(`0.005 - 0.028`)≈ 单边深度订单簿 50 档 / 全市场 24h 成交 × 参与率 — 数量级上一致,口径差异已验证

### 3.3 Per-symbol @ $500M venue-fail 名单(12 / 32)

`venue_capacity_aum_usd < $25M` = 不能在 5d × 10% 参与率下用单 venue 填 5% slot:

```
AAVE    n_v=5 max_d2=447553 cap=22,377,630
APT     n_v=5 max_d2=299432 cap=14,971,605
ATOM    n_v=5 max_d2=326556 cap=16,327,782
COMP    n_v=5 max_d2=149388 cap=7,469,381
CRV     n_v=5 max_d2=304492 cap=15,224,598
GRT     n_v=5 max_d2=251079 cap=12,553,953
LDO     n_v=5 max_d2=217454 cap=10,872,683
POL     n_v=3 max_d2=103607 cap=5,180,337
POLYX   n_v=1 max_d2=98284  cap=4,914,176
SKY     n_v=3 max_d2=103733 cap=5,186,630
STRK    n_v=3 max_d2=139816 cap=6,990,811
TIA     n_v=5 max_d2=448144 cap=22,407,204
```

(@ $30M target slot 是 $1.5M,venue cap 都 ≥ $1.5M — 没有一个 fail。所以 $30M 不卡 depth,卡的是**入场节奏 / 滑点容忍度**;$500M 才暴露 order book 真实厚度。)

---

## 4. 给 Seth — §5 入库建议(T-082 B 部分)

按 lane-c 不入库(规则 3b),但 acceptance 要求末尾给入库形态建议:

### 4.1 表结构(3 张)

**`venue_snapshot`**(粗粒度,1 slot/4h 即可)
```
slot_utc TIMESTAMPTZ PK
fetched_utc TIMESTAMPTZ
venues TEXT[]                          -- 本帧跑过哪些 venue
n_probed INT, n_ob_hit INT, n_ob_miss INT
venue_cap_ok_at_target_aum INT         -- 32 默认
venue_cap_ok_at_design_aum INT         -- 20 默认
```

**`venue_depth_2pct`**(symbol × venue × slot,中粒度)
```
slot_utc TIMESTAMPTZ PK (FK venue_snapshot)
symbol TEXT, venue TEXT                -- (symbol, venue) PK
n_venues_for_symbol INT                -- 该 symbol 在哪些 venue 上有 USDT/USDC/USD 对
depth_1pct_bid_usd NUMERIC
depth_1pct_ask_usd NUMERIC
depth_2pct_bid_usd NUMERIC
depth_2pct_ask_usd NUMERIC
depth_2pct_combined_usd NUMERIC        -- bid + ask
spread_bps NUMERIC
quote_volume_24h_usd NUMERIC           -- ticker.quoteVolume
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
- lane-c 仅 1 次 invoke `sweep_7d.py`(本轮仅 1 次,跑出 H00 一帧),后续 7 天 cron = Seth 入库时一并触发。

---

## 5. 实测限制(直说)

1. **n=3 快照,远小于 acceptance 的 21 (7d × 3 slot)**。lane-c 没法自己定义 cron,这是 Seth 入库那条线的工作。
2. **H00、H15、H16 三帧跨 16 小时(同日),无法拆出跨日方差。** 单日内 14 分钟 micro 漂移 < 0.1% 已观察;**跨日方差 = 未测量**,必须等 cron 启起来 7 天 ≥18 帧后再出最终聚合。
3. **Hyperliquid 仍未接入** — macOS sandbox 的 ccxt bug,不在 T-085 范围内解决,Seth 入库时如果 `docker exec` 跑 ccxt 应可绕过。
4. **HYPE/POL/APT/INJ 等缺 ADV 数据** — /api/v1/fund/capacity 给的 0 → venue 单独算了 cap,导致 book_verdicts 的 binding_constraint 打了 `(no adv data)`。

---

## 6. 仍待(Seth / 下轮 lane-c)

- [ ] Seth (T-082 B):launchd entry 装 `sweep_7d_runner.sh`,fire UTC 00/08/16,7 天后跑 `aggregate_7d.py` 拿 t085_report_7d_<ts>.json。
- [ ] Seth (T-082 B):按 §4.1 建 3 表;持续 7 天后 lane-c 下一轮 (T-088 之后) 把 t085_report_7d_*.json 落 commit 到 docs/lane/T-085/。
- [ ] Jazz:Hyperliquid 是否要继续接 — 涉及 macOS sandbox 还是 docker 路径,有产品取舍,**@seth 拉 Jazz 拍板**。
