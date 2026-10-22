"""CIS v2 内核(台账 S-668;Jazz 10-22「拆两层、只扩传统资产不加币、影子并行过了再切」)。

## 两层

- **分数**:只留慢、难伪造、两段数据里都为正的维度 —— 规模、稳定、供给纪律,加密另加 v1 的 F / O 支柱。
  组内百分位、能算的维度**等权**(至少 2 维),**不拟合任何权重**。0–100。
- **状态**(本文件不算,见 S-669):趋势 / 动量 / 拥挤 / 市场情绪 —— 只描述,不进分数。

为什么:v1 的综合分基本就是动量(S-383),2025-26 年信号是反的(S-523),在山寨里挑币与随机分不开(S-630);
质量(大 + 稳,S-587 / S-589)与不稀释(S-664 留出段 IC +0.119)才是在两段数据里都站得住的。

## 组

- `crypto`:CIS 的 25 个加密名字(不加币)。
- `equity`:公司 —— CIS 现有美股 + World50 候选池里美股挂牌 / 美元 ADR(股数 = 市值 ÷ 收盘)。
- 宏观 ETF(债、商品、外汇、地产、新兴、SPY / QQQ / XLF):**v2 不打分**,只给状态层;影子期内对外仍是 v1。

这是唯一的一份定义:研究脚本(T-169 / T-170)与影子写入端都 import 这里,不各写一版。全部纯函数,没有 I/O。
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Iterable, Optional, Sequence

CODE_REF = "cis-v2.0"
GROUPS = ("crypto", "equity")
MIN_DIMS = 2
CRYPTO_WINDOW_DAYS = 90               # 稳定(日收益 σ)与供给纪律(流通量增长)的窗口
EQUITY_VOL_WEEKS = 26                 # 个股稳定:过去 26 周周收益 σ
EQUITY_SUPPLY_WEEKS = 52              # 个股供给纪律:股数 52 周增长
DIMS = {"crypto": ("size", "stability", "supply", "f", "o"), "equity": ("size", "stability", "supply")}


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _d(x: Any) -> dt.date:
    return x if isinstance(x, dt.date) and not isinstance(x, dt.datetime) else dt.date.fromisoformat(str(x)[:10])


# ── 维度(原始值;方向统一为「越大越好」)─────────────────────────────────────────────────────────────
def log_returns(closes: Sequence[float]) -> list[float]:
    out = []
    for a, b in zip(closes, closes[1:]):
        a, b = _f(a), _f(b)
        if a and b and a > 0 and b > 0:
            out.append(math.log(b / a))
    return out


def stdev(xs: Sequence[float]) -> Optional[float]:
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _at_or_before(series: Sequence[tuple], day: dt.date) -> Optional[tuple]:
    """series 按日期升序;取日期 ≤ day 的最后一行。"""
    best = None
    for row in series:
        if _d(row[0]) <= day:
            best = row
        else:
            break
    return best


def crypto_inputs(rows: Iterable[tuple], asof: Any) -> dict[str, Optional[float]]:
    """rows = [(d, price, mcap)](asset_mcap_daily,升序,只用 ≤ asof 的)。
    规模 = log 市值;稳定 = −σ(窗口内日对数收益);供给纪律 = −(流通量窗口增长),流通量 = 市值 ÷ 价格。"""
    a = _d(asof)
    rs = sorted(((_d(d), _f(p), _f(m)) for d, p, m in rows if _d(d) <= a), key=lambda r: r[0])
    out: dict[str, Optional[float]] = {"size": None, "stability": None, "supply": None}
    if not rs or rs[-1][0] < a - dt.timedelta(days=3):
        return out                                                   # 当天附近没有价 ⇒ 不打分
    last = rs[-1]
    if last[2] and last[2] > 0:
        out["size"] = math.log(last[2])
    start = a - dt.timedelta(days=CRYPTO_WINDOW_DAYS)
    win = [r for r in rs if r[0] > start and r[1]]
    if len(win) >= int(CRYPTO_WINDOW_DAYS * 0.8):
        s = stdev(log_returns([r[1] for r in win]))
        out["stability"] = -s if s is not None else None
    then = _at_or_before(rs, start)
    if then and then[0] >= start - dt.timedelta(days=7) and then[1] and then[2] and last[1] and last[2]:
        c0, c1 = then[2] / then[1], last[2] / last[1]
        if c0 > 0:
            out["supply"] = -(c1 / c0 - 1.0)
    return out


def equity_inputs(rows: Iterable[tuple], asof: Any) -> dict[str, Optional[float]]:
    """rows = [(week_d, mcap_usd, close)](周频,升序,只用 ≤ asof 的;close 与 mcap 同一周)。
    规模 = log 市值;稳定 = −σ(过去 26 周周对数收益);供给纪律 = −(股数 52 周增长),股数 = 市值 ÷ 收盘。"""
    a = _d(asof)
    rs = sorted(((_d(d), _f(m), _f(c)) for d, m, c in rows if _d(d) <= a), key=lambda r: r[0])
    out: dict[str, Optional[float]] = {"size": None, "stability": None, "supply": None}
    if not rs or rs[-1][0] < a - dt.timedelta(days=10):
        return out
    last = rs[-1]
    if last[1] and last[1] > 0:
        out["size"] = math.log(last[1])
    closes = [r[2] for r in rs[-(EQUITY_VOL_WEEKS + 1):] if r[2]]
    if len(closes) >= EQUITY_VOL_WEEKS * 0.8:
        s = stdev(log_returns(closes))
        out["stability"] = -s if s is not None else None
    then = _at_or_before(rs, a - dt.timedelta(weeks=EQUITY_SUPPLY_WEEKS))
    if then and then[0] >= a - dt.timedelta(weeks=EQUITY_SUPPLY_WEEKS + 2) and then[1] and then[2] and last[1] and last[2]:
        s0, s1 = then[1] / then[2], last[1] / last[2]
        if s0 > 0:
            out["supply"] = -(s1 / s0 - 1.0)
    return out


# ── 合成 ─────────────────────────────────────────────────────────────────────────────────────────────
def pct_rank(values: dict[str, Optional[float]]) -> dict[str, float]:
    """组内百分位 0–1(并列取平均秩);缺值不参加。只有一个名字 ⇒ 0.5。"""
    xs = sorted(((v, k) for k, v in values.items() if v is not None), key=lambda t: t[0])
    n = len(xs)
    if n == 0:
        return {}
    if n == 1:
        return {xs[0][1]: 0.5}
    out: dict[str, float] = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and xs[j + 1][0] == xs[i][0]:
            j += 1
        r = (i + j) / 2.0
        for k in range(i, j + 1):
            out[xs[k][1]] = r / (n - 1)
        i = j + 1
    return out


def score_group(group: str, raw: dict[str, dict[str, Optional[float]]]) -> dict[str, dict[str, Any]]:
    """raw = {名字: {维度: 原始值}}(越大越好;F / O 直接给 v1 支柱分)→ {名字: {score 0–100 或 None, n_dims, ranks}}。
    能算的维度等权;不足 MIN_DIMS 维 ⇒ score = None(写明,不硬凑)。"""
    if group not in DIMS:
        raise ValueError(f"v2 只给 {GROUPS} 打分,收到 {group!r}")
    ranks = {dim: pct_rank({k: (v or {}).get(dim) for k, v in raw.items()}) for dim in DIMS[group]}
    out: dict[str, dict[str, Any]] = {}
    for name in raw:
        got = {dim: ranks[dim][name] for dim in DIMS[group] if name in ranks[dim]}
        ok = len(got) >= MIN_DIMS
        out[name] = {"score": round(100.0 * sum(got.values()) / len(got), 2) if ok else None,
                     "n_dims": len(got), "ranks": {k: round(v, 4) for k, v in got.items()},
                     "missing": [d for d in DIMS[group] if d not in got], "code_ref": CODE_REF}
    return out
