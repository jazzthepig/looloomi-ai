# MINIMAX_SYNC.md — Mac Mini ↔ Railway 接口契约

> **Last updated**: 2026-03-23 by Seth/Austin
> **目的**: 消除 Mac Mini (Minimax) 和 Railway (Seth/Austin) 之间的重复修改和覆盖问题。
> Minimax 改 Mac Mini 代码前请先看这份文档。Railway 改接口前也必须同步更新此文件。

---

## 1. 架构边界（谁改什么）

```
┌─────────────────────────────┐     ┌──────────────────────────────┐
│  Mac Mini (Minimax 管)       │     │  Railway (Seth/Austin 管)     │
│                             │     │                              │
│  cis_v4_engine.py           │     │  src/api/routers/cis.py      │
│  cis_scheduler.py           │     │  src/data/cis/cis_provider.py│
│  cis_push.py                │     │  src/data/market/data_layer.py│
│  data_fetcher.py            │     │  dashboard/src/components/*  │
│  config.py                  │     │  src/api/store.py            │
│                             │     │                              │
│  输出 → POST /internal/     │────→│  接收 → Redis → 前端          │
│         cis-scores          │     │                              │
└─────────────────────────────┘     └──────────────────────────────┘
```

**硬规则：**
- Minimax **只改** `/Volumes/CometCloudAI/cometcloud-local/` 下的文件
- Seth/Austin **只改** `looloomi-ai/src/` 和 `looloomi-ai/dashboard/` 下的文件
- **Shadow/ 是只读镜像**，Seth/Austin 用来参考 Mac Mini 代码，不会 commit
- **接口变更**（POST body schema、字段名、枚举值）需要双方确认后才改
- 本文档是接口的 single source of truth

---

## 2. POST /internal/cis-scores 接口契约

### 请求格式

```
POST https://web-production-0cdf76.up.railway.app/internal/cis-scores
Header: X-Internal-Token: <INTERNAL_TOKEN>
Content-Type: application/json
```

### Payload Schema (v4.1)

```jsonc
{
  "universe": [
    {
      // ── 必填字段 ──
      "symbol":      "BTC",                    // ticker, 大写
      "name":        "Bitcoin",                 // 资产全名 (不能省略!)
      "asset_class": "L1",                      // 细分类，见下方枚举
      "cis_score":   72.5,                      // 0-100 连续分
      "grade":       "B+",                      // 统一 grading，见 §3
      "signal":      "OUTPERFORM",              // 合规 signal，见 §4

      // ── 推荐字段 (有则显示，无则 Railway 补) ──
      "f":           68.0,                      // Fundamental pillar
      "m":           75.0,                      // Momentum pillar
      "r":           60.0,                      // On-chain Risk pillar (注意: key 是 "r" 不是 "o")
      "s":           70.0,                      // Sentiment pillar
      "a":           80.0,                      // Alpha pillar
      "data_tier":   1,                         // 1 = Mac Mini full engine
      "confidence":  0.85,                      // 0-1, 数据完整度

      // ── 可选字段 ──
      "las":         65.2,                      // Liquidity-Adjusted Score
      "percentile_rank": 82,                    // 百分位 (metadata only, 不决定 grade)
      "change_30d":  12.5,                      // 30d 涨跌幅
      "recommended_weight": 0.08,               // 建议配置权重
      "class_rank":  1,                         // 类内排名
      "global_rank": 5,                         // 全局排名
      "macro_regime": "RISK_ON"                 // 宏观 regime
    }
    // ... more assets
  ],
  "timestamp": 1711234567                       // Unix seconds (不是毫秒!)
}
```

### ⚠️ 关键字段变更 (v4.0 → v4.1)

| v4.0 字段 | v4.1 字段 | 说明 |
|-----------|-----------|------|
| `cis_grade` | `grade` | 字段名改了 |
| `pillar_scores: {F: 68, M: 75, ...}` | `f: 68, m: 75, r: 60, s: 70, a: 80` | 从 nested dict 改为 flat keys |
| `pillar_scores.O` | `r` | On-chain pillar key 从 "O" 改为 "r" (Risk-adjusted) |
| `asset_class: "Crypto"` | `asset_class: "L1"` / `"DeFi"` / etc. | 需要细分类，不能全部写 "Crypto" |
| 无 | `data_tier: 1` | 新增，Mac Mini 固定传 1 |
| 无 | `confidence` | 新增，数据完整度 0-1 |
| 无 | `las` | 新增，可选 |

---

## 3. 统一 Grading Thresholds (v4.1)

**Mac Mini 和 Railway 必须使用完全相同的阈值。**

```python
# v4.1 统一阈值 — 两边一致
GRADE_THRESHOLDS = [
    (85, "A+"),   # was 90 in v4.0
    (75, "A"),    # was 80
    (65, "B+"),   # was 70
    (55, "B"),    # was 60
    (45, "C+"),   # was 50
    (35, "C"),    # was 40
    (25, "D"),    # same
    (0,  "F"),    # same
]
```

**Minimax TODO**: 更新 `cis_v4_engine.py` 的 `GRADE_THRESHOLDS`:
```python
# 旧代码:
GRADE_THRESHOLDS = [
    (90, "A+"), (80, "A"), (70, "B+"), (60, "B"),
    (50, "C+"), (40, "C"), (25, "D"), (0, "F")
]

# 改为:
GRADE_THRESHOLDS = [
    (85, "A+"), (75, "A"), (65, "B+"), (55, "B"),
    (45, "C+"), (35, "C"), (25, "D"), (0, "F")
]
```

---

## 4. 合规信号枚举 (CRITICAL)

**我们没有投顾牌照（投资顾问 license），所有面向用户的信号 MUST 使用持仓定位语言。**

```python
# ✅ 合规 — 使用这些
SIGNAL_MAP = {
    "STRONG OUTPERFORM": (85, 100),   # 原 "STRONG OVERWEIGHT"
    "OUTPERFORM":        (65, 85),    # 原 "OVERWEIGHT"
    "NEUTRAL":           (45, 65),    # 不变
    "UNDERPERFORM":      (35, 45),    # 新增
    "UNDERWEIGHT":       (0,  35),    # 原 "AVOID" → 改名
}

# ❌ 禁止 — 永远不要出现
# BUY, SELL, STRONG BUY, STRONG SELL
# ACCUMULATE, REDUCE, AVOID
# STRONG OVERWEIGHT, OVERWEIGHT (已改名)
```

**Minimax TODO**: 更新 `cis_v4_engine.py` 的 `SIGNAL_THRESHOLDS`:
```python
# 旧代码:
SIGNAL_THRESHOLDS = [
    (80, "STRONG OVERWEIGHT", 0.15),
    (65, "OVERWEIGHT", 0.10),
    (50, "NEUTRAL", 0.05),
    (35, "UNDERWEIGHT", 0.02),
    (0, "AVOID", 0.00)
]

# 改为:
SIGNAL_THRESHOLDS = [
    (85, "STRONG OUTPERFORM", 0.15),
    (65, "OUTPERFORM", 0.10),
    (45, "NEUTRAL", 0.05),
    (35, "UNDERPERFORM", 0.02),
    (0,  "UNDERWEIGHT", 0.00)
]
```

---

## 5. Asset Class 枚举

Mac Mini 输出的 `asset_class` 必须使用以下值（不是 generic "Crypto"）：

| asset_class | 示例资产 |
|------------|---------|
| `L1` | BTC, ETH, SOL, ADA, AVAX, DOT, SUI, APT, NEAR, ATOM |
| `L2` | ARB, OP, POL, MANTLE |
| `DeFi` | UNI, AAVE, LDO, CRV, COMP, PENDLE, SUSHI |
| `RWA` | ONDO, MKR, POLYX |
| `Infrastructure` | LINK, TIA, ENA, INJ, FIL, ICP, STX, RUNE, VET |
| `Memecoin` | DOGE, PEPE, WIF, BONK |
| `Gaming` | SAND, MANA, AXS |
| `AI` | NEAR, ICP, VIRTUAL |
| `US Equity` | SPY, QQQ, AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA |
| `US Bond` | TLT, IEF, SHY, HYG, LQD |
| `Commodity` | GLD, SLV, USO, UNG, DBC |

**注意**: Railway 有 fallback 映射，如果 Mac Mini 传 "Crypto" 也能 resolve。但建议直接传正确的细分类。

---

## 6. `to_dict()` 改造模板

Minimax 可以在 `cis_v4_engine.py` 的 `to_dict()` 方法中做如下修改以兼容 v4.1:

```python
def to_dict(self) -> Dict:
    return {
        "symbol": self.symbol,
        "name": self.name,
        "asset_class": self.asset_class,      # 用细分类，不要 "Crypto"
        "cis_score": self.cis_score,
        "grade": self.cis_grade,               # key 从 "cis_grade" 改为 "grade"
        "signal": self.signal,                 # 用合规枚举
        "data_tier": 1,                        # Mac Mini = T1

        # Flat pillar scores (v4.1 格式)
        "f": self.pillar_scores.get("F", 0),
        "m": self.pillar_scores.get("M", 0),
        "r": self.pillar_scores.get("O", 0),   # O pillar → "r" key
        "s": self.pillar_scores.get("S", 0),
        "a": self.pillar_scores.get("A", 0),

        # Optional enrichment
        "confidence": self._calculate_confidence(),
        "percentile_rank": self.cross_asset_percentile,
        "recommended_weight": self.recommended_weight,
        "class_rank": self.class_rank,
        "global_rank": self.global_rank,
        "macro_regime": self.macro_regime,
    }
```

---

## 7. Railway 合并策略

Railway 的 CIS universe endpoint (`/api/v1/cis/universe`) 现在执行 **merge** 而不是 **replace**：

```
Mac Mini T1 (19 assets, via Redis)  ──┐
                                      ├──→ Merged Universe (65+ assets)
Railway T2 (65+ assets, calculated) ──┘
```

- Mac Mini 资产标记 `data_tier: 1` (绿色 badge)
- Railway-only 资产标记 `data_tier: 2` (黄色 badge)
- Mac Mini 分数优先覆盖 Railway 分数
- Railway 提供 Mac Mini 没有的资产（如 ONDO, POLYX 等）

**这意味着即使 Mac Mini 只覆盖 19 个资产，前端也会显示完整的 65+ 资产。**

---

## 8. Minimax 操作清单

### 立即需要做 (P0):
1. `git pull origin main` 更新本地 repo（Jazz push 后）
2. 更新 `cis_v4_engine.py`:
   - `GRADE_THRESHOLDS` → v4.1 阈值（§3）
   - `SIGNAL_THRESHOLDS` → 合规枚举（§4）
   - `to_dict()` → v4.1 schema（§6）
3. 验证 `cis_push.py` POST 后 Railway 正确接收
4. 启动 Freqtrade dry run

### 改完后验证:
```bash
# 在 Mac Mini 上跑一次 scoring
python cis_scheduler.py --once

# 检查输出文件
python -c "
import json
with open('_data/cis_scores_latest.json') as f:
    data = json.load(f)
for s in data['scores'][:3]:
    print(s.get('symbol'), s.get('grade'), s.get('signal'), s.get('asset_class'))
    # 期望: BTC B+ OUTPERFORM L1
    # 不应该: BTC A OVERWEIGHT Crypto
"

# Push 到 Railway
python cis_push.py --dry-run  # 先看
python cis_push.py            # 再推
```

---

## 9. 变更协议

**任何一方**修改以下内容前，必须先更新本文档并通知对方：

1. POST body 的字段名或新增字段
2. Grade/Signal 枚举值
3. pillar key 名
4. asset_class 枚举
5. timestamp 格式

修改流程：
1. 在本文档中标注变更
2. 通知对方（Jazz 中转或直接 commit message 注明）
3. 双方各自更新代码
4. 验证 push → receive → display 链路

---

*Last synced: 2026-03-23. Next review: 每次 schema 变更时。*
