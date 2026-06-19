# Minimax Task Prompt — 2026-03-28

> Jazz: 直接把以下内容发给 Minimax 作为新 session 的起始 prompt。

---

你好 Minimax。以下是当前状态和今天的任务。

## 上次任务确认完成

以下已完成，无需重做：
- `cis_grade` → `grade` 字段改名 ✓
- Flat pillar keys（`f`/`m`/`r`/`s`/`a`）✓
- Grade thresholds 统一（A+≥85，A≥75，B+≥65，B≥55，C+≥45，C≥35，D≥25，F<25）✓
- 合规信号语言（STRONG OUTPERFORM / OUTPERFORM / NEUTRAL / UNDERPERFORM / UNDERWEIGHT）✓
- `asset_class` 细分类（L1 / L2 / DeFi / RWA / Infrastructure / Memecoin）✓
- 4项小修（asyncio.sleep / HTTPException / IntelligencePage dead code / cis_scheduler skip）✓

---

## 今天的任务

### 任务 1 — `to_dict()` 补充 4 个 v4.1 字段

Railway 前端现在展示 `las`（Liquidity-Adjusted Score）、`confidence` 置信度点、`change_30d` 30日涨跌。
Mac Mini 不推这些字段时，T1 资产显示的是 Railway T2 的估算值，精度低。

在 `cis_v4_engine.py` 的 `to_dict()` 里补充以下字段：

```python
def to_dict(self) -> dict:
    return {
        # ← 原来可能是 "total" 或 "score"，改成 "cis_score"
        "cis_score": round(self.total_score, 2),

        # ← 新增：LAS (Liquidity-Adjusted Score)
        # Railway 公式参考（你可以用 Binance 数据做更精准版本）：
        # vol_ratio = volume_24h / market_cap
        # if vol_ratio >= 0.10: liq_mult = 1.0
        # elif vol_ratio >= 0.05: liq_mult = 0.90
        # elif vol_ratio >= 0.02: liq_mult = 0.80
        # elif vol_ratio >= 0.005: liq_mult = 0.70
        # else: liq_mult = 0.50
        # las = round(cis_score * liq_mult * confidence, 2)
        "las": self.compute_las(),

        # ← 新增：confidence 0.0~1.0，基于数据完整性
        # 建议：base 0.60 + 0.15 if has_orderbook + 0.15 if has_tvl + 0.10 if has_klines
        "confidence": round(self.confidence, 2),

        # ← 新增：30日价格变化 %（Binance klines 计算，比 CG 精准）
        "change_30d": round(self.change_30d, 2),

        # 其余字段保持不变
        "symbol":      self.symbol,
        "name":        self.name,
        "grade":       self.grade,
        "signal":      self.signal,
        "asset_class": self.asset_class,
        "f": round(self.pillar_scores.get("F", 0), 2),
        "m": round(self.pillar_scores.get("M", 0), 2),
        "r": round(self.pillar_scores.get("O", 0), 2),  # O pillar → key "r"
        "s": round(self.pillar_scores.get("S", 0), 2),
        "a": round(self.pillar_scores.get("A", 0), 2),
        "price":      self.price,
        "change_24h": self.change_24h,
        "market_cap": self.market_cap,
        "volume_24h": self.volume_24h,
        "tvl":        self.tvl,
        "recommended_weight": getattr(self, "recommended_weight", None),
        "class_rank":  getattr(self, "class_rank", 0),
        "global_rank": getattr(self, "global_rank", 0),
        "macro_regime": getattr(self, "macro_regime", None),
    }
```

---

### 任务 2 — 信号映射修正

旧映射里 `"HOLD"` 和 `"WATCH"` 不在合规信号集里，前端 SignalFeed 有严格匹配会直接丢弃。
改成：

```python
GRADE_TO_SIGNAL = {
    "A+": "STRONG OUTPERFORM",
    "A":  "OUTPERFORM",
    "B+": "OUTPERFORM",
    "B":  "NEUTRAL",          # ← 原来是 HOLD
    "C+": "NEUTRAL",          # ← 原来是 WATCH
    "C":  "UNDERPERFORM",     # ← 原来是 WATCH
    "D":  "UNDERPERFORM",
    "F":  "UNDERWEIGHT",      # ← 原来是 AVOID
}
```

---

### 任务 3 — WebSocket pong 响应

Railway WS 服务现在会每 30 秒发一个心跳包：

```json
{"type": "ping", "ts": 1743123456.789}
```

`cis_push.py` 或 `cis_scheduler.py` 里的 WS 客户端收到这个需要回：

```json
{"type": "pong"}
```

否则 30 秒后 Railway 会强制断连（code 1001），触发重连。

检查 `cis_push.py` 里的 WS 接收循环，加上：
```python
msg = await ws.recv()
data = json.loads(msg)
if data.get("type") == "ping":
    await ws.send(json.dumps({"type": "pong"}))
```

---

### 任务 4 — Freqtrade dry run 启动

```bash
cd /Volumes/CometCloudAI/looloomi-ai
git pull origin main

cd /Volumes/CometCloudAI/freqtrade
bash scripts/start_dry_run.sh
```

dry run 跑起来后，确认 FreqUI 在 http://localhost:8080 可以访问，CIS cache writer 在写入 `/Volumes/CometCloudAI/freqtrade/cis_cache/`。

---

### 验证命令

```bash
# 验证 v4.1 字段
python3 -c "
from cis_v4_engine import CISEngine
e = CISEngine()
result = e.score_asset('BTC')
d = result.to_dict()
assert 'cis_score' in d, 'FAIL: cis_score missing'
assert 'las' in d, 'FAIL: las missing'
assert 'confidence' in d, 'FAIL: confidence missing'
assert 'change_30d' in d, 'FAIL: change_30d missing'
assert d['signal'] in ('STRONG OUTPERFORM','OUTPERFORM','NEUTRAL','UNDERPERFORM','UNDERWEIGHT'), f\"FAIL: {d['signal']}\"
print(f\"✓ BTC: score={d['cis_score']} grade={d['grade']} las={d['las']} conf={d['confidence']}\")
"

# dry run后验证
curl http://localhost:8080/api/v1/status
ls /Volumes/CometCloudAI/freqtrade/cis_cache/
```

---

完成后同步 Shadow 目录（不要 git add Shadow/，Jazz 会 commit）。

**MINIMAX_SYNC.md 已更新，完整字段规范在：**
`/Volumes/CometCloudAI/looloomi-ai/docs/MINIMAX_SYNC.md`
