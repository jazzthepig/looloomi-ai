# Mac Mini ↔ Railway CIS 接口同步
**Last Updated:** 2026-03-24
**Status:** 5 个不兼容项需修复

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
