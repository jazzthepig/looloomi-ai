# Mac Mini ↔ Railway CIS 接口同步
**Last Updated:** 2026-03-28
**Status:** ✅ 5 个原始不兼容项已修复 (2026-03-24) · ⚠️ 4 个 v4.1 新增字段待 Minimax 补充 (2026-03-28)

---

## 背景

Railway 前端 (CISLeaderboard.jsx, CISWidget.jsx) 已按 Railway API schema 绑定。Mac Mini 推送的 CIS scores 存在 5 个不兼容，导致前端读不到数据或显示错误。

---

## 5 个不兼容项

### 1. `cis_grade` → `grade`
**问题：** 前端读取 `grade` 字段，但 Mac Mini 输出 `cis_grade`
**影响：** 前端不显示等级

```python
# 当前 (错误)
{"symbol": "BTC", "cis_grade": "A+", ...}

# 应改为
{"symbol": "BTC", "grade": "A+", ...}
```

---

### 2. `pillar_scores: {F:68, M:75, O:60, S:70, A:80}` → `f:68, m:75, r:60, s:70, a:80`
**问题：** 前端用 flat keys (`f`, `m`, `r`, `s`, `a`)，Mac Mini 输出 nested dict
**影响：** 前端无法显示 5 pillar 分数

```python
# 当前 (错误)
{"symbol": "BTC", "pillar_scores": {"F": 68, "M": 75, "O": 60, "S": 70, "A": 80}, ...}

# 应改为
{"symbol": "BTC", "f": 68, "m": 75, "r": 60, "s": 70, "a": 80, ...}
```

---

### 3. `GRADE_THRESHOLDS` A+ ≥ 90 → A+ ≥ 85
**问题：** Railway 用 A+ ≥ 85，Mac Mini 用 A+ ≥ 90，同一 BTC 会出两个不同等级
**影响：** 前端显示 A+，但 Railway 同一时间同一资产显示 A

```python
# 当前 (错误)
def get_grade(score):
    if score >= 90: return "A+"
    if score >= 80: return "A"
    ...

# 应改为 (与 Railway 一致)
def get_grade(score):
    if score >= 85: return "A+"
    if score >= 75: return "A"
    if score >= 65: return "B+"
    if score >= 55: return "B"
    if score >= 45: return "C+"
    if score >= 35: return "C"
    if score >= 25: return "D"
    return "F"
```

---

### 4. `"STRONG OVERWEIGHT"` / `"AVOID"` → `"STRONG OUTPERFORM"` / `"UNDERWEIGHT"`
**问题：** 前端用合规语言，Mac Mini 用投资银行黑话
**影响：** 合规红线，前端不显示信号

```python
# 当前 (错误)
"STRONG OVERWEIGHT"  # 投行术语
"UNDERWEIGHT"
"AVOID"

# 应改为 (合规语言)
"STRONG OUTPERFORM"
"OUTPERFORM"
"UNDERPERFORM"
"WATCH"
"AVOID"
```

**完整信号映射：**
```python
GRADE_TO_SIGNAL = {
    "A+": "STRONG OUTPERFORM",
    "A":  "OUTPERFORM",
    "B+": "OUTPERFORM",
    "B":  "HOLD",
    "C+": "WATCH",
    "C":  "WATCH",
    "D":  "UNDERPERFORM",
    "F":  "AVOID",
}
```

---

### 5. `asset_class: "Crypto"` → 细分类 `"L1"` / `"DeFi"` / `"RWA"` / `"L2"` 等
**问题：** 前端按 `asset_class` 过滤（Crypto / L1 / L2 / DeFi / RWA / Commodity），Mac Mini 输出 `"Crypto"` 太笼统
**影响：** 前端过滤失效，资产归类错误

```python
# 当前 (错误)
{"symbol": "ETH", "asset_class": "Crypto", ...}

# 应改为
{"symbol": "ETH", "asset_class": "L1", ...}
{"symbol": "AAVE", "asset_class": "DeFi", ...}
{"symbol": "ONDO", "asset_class": "RWA", ...}
{"symbol": "ARB", "asset_class": "L2", ...}
```

**标准分类：**
| asset_class | 说明 |
|-------------|------|
| `L1` | Layer 1 区块链 (ETH, SOL, BNB, AVAX...) |
| `L2` | Layer 2 扩展 (ARB, OP, POL, MATIC...) |
| `DeFi` | 去中心化金融协议 (AAVE, UNI, CRV...) |
| `RWA` | 真实世界资产 (ONDO, BLUR...) |
| `Crypto` | 仅 BTC |

---

## to_dict() 改造模板

在 `cis_v4_engine.py` 的 `AssetScore` class 添加：

```python
def to_dict(self) -> dict:
    """输出与 Railway 前端兼容的 dict。"""
    return {
        # 基础字段
        "symbol": self.symbol,
        "name": self.name,
        "grade": self.grade,                    # ← 原来是 cis_grade
        "signal": self.signal,
        "asset_class": self.asset_class,        # ← 原来是 "Crypto"，需细分类

        # 5 pillar flat keys
        "f": self.pillar_scores.get("F", 0),
        "m": self.pillar_scores.get("M", 0),
        "r": self.pillar_scores.get("O", 0),   # ← 原来是 O，不是 r
        "s": self.pillar_scores.get("S", 0),
        "a": self.pillar_scores.get("A", 0),

        # 分数
        "total": self.total_score,
        "confidence": self.confidence,

        # 市场数据
        "price": self.price,
        "change_24h": self.change_24h,
        "market_cap": self.market_cap,
        "volume_24h": self.volume_24h,
        "tvl": self.tvl,

        # 可选
        "rank": getattr(self, "rank", 0),
        "class_rank": getattr(self, "class_rank", 0),
    }
```

---

## 验证命令

在 Mac Mini 上运行：

```bash
cd /Volumes/CometCloudAI/cometcloud-local

# 1. 验证字段名
python3 -c "
from cis_v4_engine import AssetScore
# 模拟输出
test = AssetScore(symbol='BTC', ...)
d = test.to_dict()
assert 'grade' in d, 'ERROR: missing grade'
assert 'f' in d, 'ERROR: missing f pillar'
assert 'r' in d, 'ERROR: missing r pillar'
assert d['grade'] == 'A+', f\"ERROR: grade={d['grade']} expected A+\"
assert d['signal'] == 'STRONG OUTPERFORM', f\"ERROR: signal={d['signal']}\"
print('✓ 字段验证通过')
"

# 2. 验证 grade threshold
python3 -c "
from cis_v4_engine import get_grade
assert get_grade(85) == 'A+', 'ERROR: 85 should be A+'
assert get_grade(75) == 'A',  'ERROR: 75 should be A'
assert get_grade(90) == 'A+', 'ERROR: 90 should be A+'
print('✓ Grade thresholds 验证通过')
"

# 3. 验证信号
python3 -c "
from cis_v4_engine import get_grade, GRADE_TO_SIGNAL
for score, expected_signal in [(95,'STRONG OUTPERFORM'),(85,'STRONG OUTPERFORM'),(75,'OUTPERFORM'),(55,'HOLD')]:
    g = get_grade(score)
    s = GRADE_TO_SIGNAL.get(g, '')
    assert s == expected_signal, f'ERROR: score={score} grade={g} signal={s}'
print('✓ 信号映射验证通过')
"

# 4. push 并验证 Railway
python3 cis_push.py --dry-run
```

---

## v4.1 新增字段 (2026-03-28) — Minimax 待补充

CIS v4.1 在 Railway 端已上线以下字段。Mac Mini 推送的 payload 如果缺这些字段，merge 时会退回到 Railway T2 的计算值，精度下降。

### 1. `cis_score` 字段名统一

**现状：** Mac Mini 推的字段可能是 `total` 或 `score`
**要求：** 改成 `cis_score`（Railway 主键，merge 逻辑优先读这个）

```python
# to_dict() 改动
return {
    "cis_score": round(self.total_score, 2),  # ← 原来是 "total" 或 "score"
    ...
}
```

> Railway merge 代码：`la.get("cis_score") or la.get("score", ...)` — `score` 仍可作 fallback，但统一成 `cis_score` 更干净。

---

### 2. `las` — Liquidity-Adjusted Score

**现状：** Mac Mini 不推 `las`，前端收到 T1 资产时 LAS 列显示 Railway T2 估算值
**要求：** Mac Mini 计算并推送 `las`

Railway 计算公式（作参考，Minimax 可用 Binance 数据做更精准版本）：

```python
def compute_las(cis_score: float, price: float, volume_24h: float,
                market_cap: float, confidence: float) -> float:
    # Liquidity multiplier: 0.5~1.0 based on volume/mcap ratio
    vol_ratio = volume_24h / market_cap if market_cap > 0 else 0
    if vol_ratio >= 0.10:      liquidity_mult = 1.0
    elif vol_ratio >= 0.05:    liquidity_mult = 0.90
    elif vol_ratio >= 0.02:    liquidity_mult = 0.80
    elif vol_ratio >= 0.005:   liquidity_mult = 0.70
    else:                      liquidity_mult = 0.50

    # Spread penalty: use Binance order book or estimate from volume
    spread_penalty = 1.0  # 1.0 = tight spread; lower for illiquid

    las = cis_score * liquidity_mult * spread_penalty * confidence
    return max(0, round(las, 2))
```

推送字段：
```python
"las": compute_las(cis_score, price, volume_24h, market_cap, confidence)
```

---

### 3. `confidence` — 数据质量置信度

**现状：** Mac Mini 不推 `confidence`，前端 AssetRadar 的置信度小圆点对 T1 资产显示 Railway T2 估算值（通常偏低）
**要求：** Mac Mini 推送 `confidence`，范围 0.0 ~ 1.0

```python
# 建议逻辑（Minimax 自行调整）
def compute_confidence(has_orderbook: bool, has_tvl: bool,
                       has_binance_klines: bool) -> float:
    score = 0.60  # base
    if has_orderbook:      score += 0.15  # Binance order book data
    if has_tvl:            score += 0.15  # DeFiLlama TVL (DeFi assets)
    if has_binance_klines: score += 0.10  # full OHLCV history
    return min(1.0, round(score, 2))

# 推送字段
"confidence": compute_confidence(...)
```

---

### 4. `change_30d` — 30 日价格变化 %

**现状：** Mac Mini 不推 `change_30d`，CISWidget 和 CISLeaderboard 的 30D 列对 T1 资产显示 Railway 的 CoinGecko 数据
**要求：** Mac Mini 推送 `change_30d`（Binance klines 计算，精度更高）

```python
# 推送字段（百分比，如 +12.5 表示涨 12.5%）
"change_30d": round(((current_price - price_30d_ago) / price_30d_ago) * 100, 2)
```

---

### 完整 to_dict() 模板（v4.1 更新版）

```python
def to_dict(self) -> dict:
    return {
        # 核心字段
        "symbol":      self.symbol,
        "name":        self.name,
        "grade":       self.grade,           # A+/A/B+/B/C+/C/D/F (unified thresholds)
        "signal":      self.signal,          # STRONG OUTPERFORM/OUTPERFORM/NEUTRAL/UNDERPERFORM/UNDERWEIGHT
        "asset_class": self.asset_class,     # L1/L2/DeFi/RWA/Infrastructure/Memecoin/TradFi/Commodity

        # ← v4.1 改: cis_score (不是 total/score)
        "cis_score":   round(self.total_score, 2),

        # 5 pillars flat keys
        "f": round(self.pillar_scores.get("F", 0), 2),
        "m": round(self.pillar_scores.get("M", 0), 2),
        "r": round(self.pillar_scores.get("O", 0), 2),  # On-chain pillar key = "r"
        "s": round(self.pillar_scores.get("S", 0), 2),
        "a": round(self.pillar_scores.get("A", 0), 2),

        # ← v4.1 新增
        "las":        compute_las(...),     # Liquidity-Adjusted Score
        "confidence": compute_confidence(...),  # 0.0 ~ 1.0
        "change_30d": round(ch30d, 2),      # % 30d price change

        # 市场数据
        "price":      self.price,
        "change_24h": self.change_24h,
        "market_cap": self.market_cap,
        "volume_24h": self.volume_24h,
        "tvl":        self.tvl,

        # 扩展（Mac Mini only，前端暂未使用但保留）
        "recommended_weight": getattr(self, "recommended_weight", None),
        "class_rank":         getattr(self, "class_rank", 0),
        "global_rank":        getattr(self, "global_rank", 0),
        "macro_regime":       getattr(self, "macro_regime", None),
    }
```

---

### 信号映射 v4.1（合规版，修正 HOLD/WATCH → NEUTRAL）

⚠️ 旧版 MINIMAX_SYNC.md 的映射包含 `"HOLD"` 和 `"WATCH"`，这两个不在合规信号集里。前端 SignalFeed 有严格的 HORIZON_STYLES 匹配，未知信号直接不渲染。

```python
GRADE_TO_SIGNAL = {
    "A+": "STRONG OUTPERFORM",
    "A":  "OUTPERFORM",
    "B+": "OUTPERFORM",
    "B":  "NEUTRAL",          # ← 原来是 "HOLD"，改为 NEUTRAL
    "C+": "NEUTRAL",          # ← 原来是 "WATCH"，改为 NEUTRAL
    "C":  "UNDERPERFORM",     # ← 原来是 "WATCH"，改为 UNDERPERFORM
    "D":  "UNDERPERFORM",
    "F":  "UNDERWEIGHT",      # ← 原来是 "AVOID"，改为 UNDERWEIGHT
}
```

---

### 验证命令（v4.1 更新版）

```bash
cd /Volumes/CometCloudAI/cometcloud-local

python3 -c "
from cis_v4_engine import AssetScore
# 用真实数据跑一个资产
from data_fetcher import fetch_asset_data
data = fetch_asset_data('BTC')
score = AssetScore.from_data(data)
d = score.to_dict()

# v4.1 字段检查
assert 'cis_score' in d, 'FAIL: missing cis_score'
assert 'las' in d,       'FAIL: missing las'
assert 'confidence' in d, 'FAIL: missing confidence'
assert 'change_30d' in d, 'FAIL: missing change_30d'
assert d['signal'] in ('STRONG OUTPERFORM','OUTPERFORM','NEUTRAL','UNDERPERFORM','UNDERWEIGHT'), \
    f\"FAIL: invalid signal {d['signal']}\"
assert d['grade'] in ('A+','A','B+','B','C+','C','D','F'), f\"FAIL: invalid grade {d['grade']}\"
print(f\"✓ BTC: score={d['cis_score']} grade={d['grade']} las={d['las']} conf={d['confidence']}\")
"

# push dry run
python3 cis_push.py --dry-run
```

---

## 协作规则

### CLAUDE.md 已写入：

```
### Mac Mini 代码协作规则
- Mac Mini 端代码在 `/Volumes/CometCloudAI/cometcloud-local/`
- Shadow/ 是 Mac Mini 的镜像，**只读不提交**
- 接口 schema 变更：先更新本文档，再改代码
- Seth/Austin：只修改 src/ + dashboard/
- Minimax：只修改 /Volumes/CometCloudAI/cometcloud-local/
```

### 工作流：

1. **接口变更** → 更新 `MINIMAX_SYNC.md` → Minimax 改 Mac Mini 代码
2. **Mac Mini push** → `cis_push.py` → Railway `/internal/cis-scores`
3. **Shadow 更新** → Minimax 在 Mac Mini 改完后同步到 Shadow 目录
4. **任何时候** → 不要 `git add Shadow/`

---

## 联系

- **Minimax**: Mac Mini 代码 (`/Volumes/CometCloudAI/cometcloud-local/`)
- **Seth/Austin**: Railway 代码 (`src/`, `dashboard/`)

有任何问题先更新本文档再动手。
