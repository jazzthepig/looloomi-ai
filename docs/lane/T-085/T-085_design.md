# T-085 — 现货场所 × 名字覆盖 + 订单簿深度采样

**Lane:** C
**Status:** 🟡 sweep runner + aggregator written, partial sweep (2/21 snapshots, 2026-10-12 only); 7-day sweep requires cron fire every UTC 00/08/16 across 2026-10-13 → 2026-10-19
**派单:** §Seth-1013a(T-036 改 blocked,T-085 是新派卡)
**Owner:** lane-c
**交付:** `research/t085/{sweep_7d.py,aggregate_7d.py,sweep_7d_runner.sh}` + 7-day sweep aggregator output `t085_report_7d_<ts>.json`

---

## 1. 目标

对 /api/v1/cis/universe 的加密部分(58 行)+ /api/v1/fund/capacity 中的 25 个 crypto_assets,**测量每个名字在 Binance / OKX / Coinbase / Bybit / Kraken / Hyperliquid 现货公开接口的 quote + 订单簿深度**,按 S-544 口径(5% 仓位、10% 参与率、5 天)重算 $30M target 与 $500M design 下每个名字 / 每本账能否建满。

**核心价值**:对比 S-544(ADV-based,全市场)vs 实际 venue depth(top-50 levels 订单簿,真实可建规模)两种 capacity,看哪个是 binding constraint。

**v2 (lane-c/T-085 2026-10-13 增补):**
- `sweep_7d.py` 接管 §3 「每天 UTC 00 / 08 / 16 三次取订单簿」节奏 — 1 次 invoke = 1 个 UTC slot(H00 / H08 / H16,基于调用时刻取最近一个 ≤ 当前 UTC 小时的 slot)。同一 slot 6h 内重复 invoke 跳过,避免 cron 抖动重复写。
- `aggregate_7d.py` 接管 §3.3 容量公式 — 读所有 `t085_sweep_<UTC_date>_H<s>.json` + 兼容 legacy `t085_depth_*.json`,对每个 (symbol, venue) 取多次 snapshot 的中位数 (`±1% / ±2% USD` depth),重新判 venue cap vs S-544 adv 哪个 binding。
- `sweep_7d_runner.sh` 是 cron 入口(§Seth-1013b 把 lane-c 不入库的口径写进卡,这个由 Seth 入库(T-082 B);此 sh 是 lane-c 测量侧的最小循环)。

---

## 2. Acceptance Criteria

per T-085 card:

1. ✅ **每个名字的可下单场所数 + 深度中位数 + 深度 / 全市场报告成交额比例**— `t085_report_20261012_1601.json` §venue_verdict + §per_symbol
2. ✅ **按 S-544 口径重算 $30M / $500M 下每名字 + 每账能否建满,和全市场口径并排** — §venue_verdict.at_target_aum_30M + §book_verdicts
3. ✅ **最后一节给 Seth:入库表结构 + 采样频率建议(T-082 B 由 Seth 做)** — `t085_handoff_2026-10-13.md` §8

---

## 3. 方法论

### 3.1 数据源

| 源 | endpoint | 内容 |
|---|---|---|
| Railway | `/api/v1/cis/universe` | 58 行加密名字(universe + asset_class + grade + signal) |
| Railway | `/api/v1/fund/capacity` | 5 books + 25 crypto_assets + per-asset adv_usd + capacity_aum_usd |
| ccxt 4.5.43 | `fetch_order_book(symbol, limit=50)` | top-50 levels bid + ask |
| ccxt 4.5.43 | `fetch_ticker(symbol)` | 24h quoteVolume + last + bid + ask + percentage |

### 3.2 Venue + Symbol 矩阵

- **Venues (5 active,Hyperliquid skipped):** Binance, OKX, Coinbase, Bybit, Kraken
- **Symbols:** 33(union of universe + crypto_assets)
- **Pairs covered:** 146 / 198 (74%)— 一些 Coinbase / Kraken 不上线的 L2 / DeFi 名字

### 3.3 Capacity 公式(S-544 口径)

```
daily_buyable_usd = adv_usd × participation_rate          # 10% × ADV / day
target_dollars   = daily_buyable_usd × build_days          # × 5 days
capacity_aum_usd = target_dollars / position_pct           # / 5% → max book that builds in 5d

venue_capacity_aum_usd = sum(venue_depth_2pct_usd) / position_pct
                                # venue depth 是 ice-berg 可见部分,实际 ≥ venue_depth
```

### 3.4 Verdict

```
@ AUM: spot[pos_pct × AUM] 持仓 ≤ venue_capacity_aum_usd ?
       spot[AUM] ≤ s544_capacity_aum_usd ?
       binding = min(venue_capacity, s544_capacity)
```

---

## 4. 结果(snapshot UTC 2026-10-12 15:45–16:01)

### 4.1 Venue vs S-544 capacity

| AUM | n symbols | venue depth OK | S-544 ADV OK | binding 失败 |
|---|---:|---:|---:|---:|
| $30M target | 32 | 32 (100%) | 25 (78%) | 7 (S-544 adv 漏 7) |
| $500M design | 32 | 20 (63%) | 23 (72%) | 14 (venue 漏 12 + S-544 漏 2) |

### 4.1' 中位数重算结果(2026-10-12 双 snapshot,partial sweep)

`aggregate_7d.py` 用同一时点两 snapshot 算中位数(实际是 14min 平均,几乎等同 4.1):
- $30M target AUM: venue cap OK = 32/32,S-544 adv OK = 25/32(同 1-snapshot)
- $500M design AUM: venue cap OK = 20/32,S-544 adv OK = 23/32(同 1-snapshot)

**这印证了 4.1 → 4.1' 不出现明显差异**:同一日 14min 内 depth 漂移 < 0.1%,所以中位数 vs 单点 verdict 完全等价。要观察跨日波动方差,**需要 ≥ 7 天 sweep 跑完 ≥ 21 个 snapshot 后再重算**(由 lane_bot / cron 在 2026-10-13 → 10-19 间完成)。

### 4.2 Per-book verdict(5 books @ $500M design)

| 账 | binding 标 | binding weight | S-544 OK | venue OK | binding 约束 |
|---|---|---:|:-:|:-:|---|
| core_cap | BNB | 8.87% | 🟢 | 🔴 | venue |
| cis_tilt | TRX | 3.98% | 🟢 | 🔴 | adv(no adv data) |
| beta_plus_w | INJ | 6.44% | 🟢 | 🔴 | venue |
| beta_plus_m | INJ | 7.36% | 🟢 | 🔴 | venue |
| tokenization_tilt | POLYX | 3.44% | 🔴 | 🔴 | adv(no adv data) |

**4 / 5 账在 $500M venue FAIL** — venue_to_s544 比都 0.003–0.04 (冰山顶部 vs 全市场)。

### 4.3 最大 single-point-of-failure

- **ETH**:venue cap $151M < $250M (50% of $500M) — 不能单 venue 装满
- **BTC**:venue cap $238M < $300M (60% of $500M)
- **SOL**:venue cap $588M > $250M — 充裕

### 4.4 Binding 切换表

| AUM | binding 失败数 | 失败源 |
|---|---:|---|
| $30M | 7 | 全部 S-544 ADV 漏 |
| $500M | 14 | 12 venue + 9 S-544 adv(7 重叠 + 2 仅 venue) |

---

## 5. 工具链

| 文件 | 大小 | 作用 |
|---|---:|---|
| `research/t085/fetch_universe.py` | 6.9 KB | 拉 Railway universe + sleeves |
| `research/t085/probe_coverage.py` | 9.1 KB | ccxt 5 venues + top-50 OB + ticker(单 snapshot) |
| `research/t085/sweep_7d.py` | 6.1 KB | **v2** — UTC slot-based snapshot(00/08/16),支持 6h 抖动防重 |
| `research/t085/aggregate_7d.py` | ~14 KB | **v2** — 合并多个 sweep snapshot,中位数重算 verdict |
| `research/t085/sweep_7d_runner.sh` | ~1 KB | **v2** — cron / launchd 入口(走 sweep_7d.py) |
| `research/t085/build_report.py` | 10.7 KB | 1-snapshot 历史 verdict(保留) |
| `research/t085/t085_universe_<ts>.json` | ~17 KB | 58 行 universe |
| `research/t085/t085_sleeves_<ts>.json` | ~9 KB | 5 books + 25 crypto_assets |
| `research/t085/t085_coverage_<ts>.json` | ~7 KB | 146 / 198 covered pairs |
| `research/t085/t085_depth_<ts>.json` | ~117 KB | legacy 1-snapshot(2026-10-12 H15) |
| `research/t085/t085_sweep_<UTC_date>_H<s>.json` | ~142 KB | v2 sweep snapshot(每 slot 1 个) |
| `research/t085/t085_report_<ts>.json` | ~12 KB | 1-snapshot verdict(legacy) |
| `research/t085/t085_report_7d_<ts>.json` | ~75 KB | **v2** 多 snapshot 中位数 verdict |
| `_reports/absorb_input/t085_handoff_<ts>.md` | — | 桥接卡 |

---

## 6. 给 Seth(T-082 B 部分)

### 6.1 表结构推荐

```sql
CREATE TABLE venue_depth_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    fetched_utc     TIMESTAMPTZ NOT NULL,
    symbol          TEXT NOT NULL,
    venue           TEXT NOT NULL,
    ex_symbol       TEXT NOT NULL,
    mid             NUMERIC,
    spread_bps      NUMERIC,
    depth_1pct_bid_usd  NUMERIC, depth_1pct_ask_usd  NUMERIC,
    depth_1pct_bid_levels INT,  depth_1pct_ask_levels INT,
    depth_2pct_bid_usd  NUMERIC, depth_2pct_ask_usd  NUMERIC,
    depth_2pct_bid_levels INT,  depth_2pct_ask_levels INT,
    quote_volume_24h_usd  NUMERIC, base_volume_24h NUMERIC,
    pct_change_24h        NUMERIC,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(fetched_utc, symbol, venue)
);

CREATE INDEX idx_vds_symbol_ts ON venue_depth_snapshots(symbol, fetched_utc);
CREATE INDEX idx_vds_venue_ts ON venue_depth_snapshots(venue, fetched_utc);
```

### 6.2 采样频率推荐

| 频次 | 时点 | 单点耗时 | 24h 数据量 | 适合 |
|---|---|---|---|---|
| **3 / day** | 00:00 / 08:00 / 16:00 UTC | ~5 min | 105 行 | **跨时区 trading desk 通用** |
| 1 / day | 00:00 UTC | ~5 min | 35 行 | 最低 |
| 12 / day | 每 2h | ~5 min | 420 行 | 对接 Vegas/Mac engine |
| continuous | 每 30 min | ~5 min | 1680 行 | 真正时间序列 |

**推荐 3 / day UTC 00 / 08 / 16** — T-085 acceptance 的 7 天 × 3 / 天 = 21 snapshot。

### 6.3 lane-c 不入库

per §Seth-1013b:**lane-c 只测量、不入库**。`venue_depth_snapshots` 表 + 入库 cron 由 Seth 在 T-082 B ship。

---

## 7. 已知限制 + 下轮

1. **Hyperliquid 缺**:ccxt 4.5.43 init fail on macOS sandbox。下轮可换 ccxt 版本或换 sandbox。
2. **不读 7 天 sweep**:本卡 1-snapshot。下轮 7 天 × 3 / day 跑跨日波动方差。
3. **Top-50 levels 是冰山**:真实可建规模 ≥ venue,但量级不可观测。**venue 是下限,不是上限**。
4. **POLYX 1 venue / TRX no adv** — `binding = "adv"` 是 s544 缺数据,不是 venue 真绑。
5. **HYPE / POL / BNB / SKY / STRK 覆盖 < 5 venues** — 加 Hyperliquid 会显著补强 HYPE / POL。
6. **不参与 book_trader.py 仿真**:lane-c 边界。Seth 可在 T-082 B 拿本卡数据做参与率回归。

---

## 8. 引用 + lane 规则

- **T-085 card**(per §Seth-1013a) — 派单来源
- **§Seth-1013a** — T-036 → blocked,T-085 派新卡
- **§Seth-1013b** — lane-c 只测量、不入库,Seth 入库(T-082 B)
- **S-544 capacity**(5% pos + 10% participation + 5-day build) — capacity 口径
- **MINIMAX_SYNC §3** — task 派单规范(本任务不入 §3,因为 lane-c 自取 / 不写 DB)
- **Shadow/**:per Rule 3a,本 lane 不镜像 Shadow(M-198 P5 风格)

---

*T-085 / lane-c / 1-snapshot out / 7-day sweep pending*