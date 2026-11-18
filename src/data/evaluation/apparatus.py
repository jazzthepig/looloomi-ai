"""验证装置(T-097)—— 研究卡的零分布、盈亏与 A/B 比较,只许用这里的函数。

## 为什么

「验证装置就是产品」(ARCHITECTURE)。到 10-14 为止它是每张卡各写一遍的脚本,那一天坏了 5 次:
打乱是空操作两次(dict 打乱不改变 key → value 的绑定,零分布 = 实际值,所有分位都是同一个数)、
空头盈亏写成 p_entry / p_exit − 1 两张卡(对跌幅是凸的:100 → 50 记 +100%,价格趋零记成无穷大)、
上市前入场取到最新收盘一张卡、领先统计量退化一张卡。这里每个函数都有把那次 bug 复现出来的测试。

## A/B(Jazz 10-14「ab test 测试模拟」)

两条臂在同一组日期上的日收益 → 逐日对数差 d_t = ln(1 + r_B) − ln(1 + r_A)。
- 总差 = Σ d_t(对数单位;expm1 之后就是「B 相对 A 多 / 少的倍数」)。
- 不确定性用平稳块自助法(Politis–Romano,平均块长默认 20 天):加密日收益的波动聚集与自相关会让
  逐日独立的自助法把置信区间算窄,A/A 测试里假阳性率会超标;块自助法在 A/A 测试里守住名义水平。
- p(B ≤ A)= 自助分布里总差 ≤ 0 的比例(单侧)。
- **最小可检出效应 MDE** = (z₁₋α + z_power) × 自助标准误,换算成每年。观测到的差小于 MDE 时标「功效不足」:
  这时「和随机分不开」不等于「没有效果」,只说明这段历史不够长,看不出来。

A/B 只回答「B 的总收益是否高于 A」。择时规则还要过「同平均仓位恒定持有」与随机择时的对照(DECISIONS 10-08),
那是 `null_distribution` + `block_permute` 的事,A/B 不替代它。
"""
from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any, Callable, Optional, Sequence

import numpy as np


class NoOpNull(RuntimeError):
    """零分布与实际值重合 —— 打乱没有打乱任何东西(10-14 的 T-090 / T-093 初版)。"""


# ── 盈亏 ────────────────────────────────────────────────────────────────────

def _price(p: Any) -> Optional[float]:
    try:
        x = float(p)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x > 0 else None


def long_return(p_entry: Any, p_exit: Any) -> Optional[float]:
    """多头:p_exit / p_entry − 1。任一价缺 / 非正 ⇒ None(不可算,不是 0)。"""
    a, b = _price(p_entry), _price(p_exit)
    return None if a is None or b is None else b / a - 1.0


def short_return(p_entry: Any, p_exit: Any) -> Optional[float]:
    """空头(不加杠杆、按入场名义):1 − p_exit / p_entry。100 → 50 = +0.5,100 → 200 = −1.0,上限 +1。"""
    a, b = _price(p_entry), _price(p_exit)
    return None if a is None or b is None else 1.0 - b / a


def price_on_or_after(dates: Sequence[str], closes: Sequence[Any], d: str, max_gap_days: int = 3) -> Optional[float]:
    """d 当天或之后 max_gap_days 天内的第一个有效收盘;该名那时还没有价格 ⇒ None。

    10-14:`find_idx` 在名字还没上市时返回 −1,下游用 closes[-1](最新收盘)当入场价。

    **进场价也用它,不要自己写下标**(11-17 T-386 的 B 道脚本进场自己写了一行,踩了 10-14 那个坑):
    自己按 `d` 取下标,遇到名字还没上市就是 −1 ⇒ 拿最新收盘当进场价,收益会凭空多出一大截。"""
    from datetime import date
    target = date.fromisoformat(str(d)[:10])
    for di, c in zip(dates, closes):
        dd = date.fromisoformat(str(di)[:10])
        if dd < target:
            continue
        if (dd - target).days > max_gap_days:
            return None
        p = _price(c)
        if p is not None:
            return p
    return None


# ── 零分布 ──────────────────────────────────────────────────────────────────

def block_permute(seq: Sequence[Any], block: int, rng: np.random.Generator) -> np.ndarray:
    """把序列切成长 `block` 的连续块(最后一块可以短),打乱块的顺序。保留块内结构与元素的多重集合。"""
    arr = np.asarray(seq, dtype=object if not np.issubdtype(np.asarray(seq).dtype, np.number) else None)
    if block < 1:
        raise ValueError("block must be ≥ 1")
    blocks = [arr[i:i + block] for i in range(0, len(arr), block)]
    order = rng.permutation(len(blocks))
    return np.concatenate([blocks[i] for i in order]) if blocks else arr.copy()


def shuffle_within(values: Sequence[Any], groups: Sequence[Any], rng: np.random.Generator) -> np.ndarray:
    """在同一组(例如同一周)内部打乱值的归属,组与组之间不混。"""
    vals = np.asarray(values, dtype=object)
    grp = np.asarray(groups, dtype=object)
    out = vals.copy()
    for g in dict.fromkeys(grp.tolist()):
        idx = np.flatnonzero(grp == g)
        out[idx] = vals[rng.permutation(idx)]
    return out


def random_dates_like(events: Sequence[tuple[Any, str]], eligible: dict[Any, Sequence[str]], rng: np.random.Generator,
                      stratum: Callable[[str], Any] = lambda d: str(d)[:4]) -> list[tuple[Any, Optional[str]]]:
    """事件研究的随机日期对照(11-05,lane-b T-242 要的):每个事件 (键, 日期) 换成**同一个键**、**同一层**(默认同一年)里
    随机抽的一个合格日期。eligible = {键: 该键可用的日期};同层没有合格日期 ⇒ 退到该键全部合格日期;键没有任何合格日期 ⇒ None
    (调用方必须把 None 当缺失,不能当 0)。只抽样,不算收益 —— 收益仍用 long_return / short_return。"""
    pools: dict[Any, dict[Any, list[str]]] = {}
    out: list[tuple[Any, Optional[str]]] = []
    for key, d in events:
        ds = [str(x)[:10] for x in (eligible.get(key) or [])]
        if not ds:
            out.append((key, None))
            continue
        by = pools.setdefault(key, {})
        if not by:
            for x in ds:
                by.setdefault(stratum(x), []).append(x)
        pool = by.get(stratum(str(d)[:10])) or ds
        out.append((key, pool[int(rng.integers(0, len(pool)))]))
    return out


def null_distribution(fn: Callable[[np.random.Generator], float], n: int, seed: int,
                      actual: Optional[float] = None) -> np.ndarray:
    """调用 fn(rng) n 次得到零分布。零分布没有方差,或 ≥ 99% 的抽样等于实际值 ⇒ NoOpNull。"""
    rng = np.random.default_rng(seed)
    null = np.array([float(fn(rng)) for _ in range(n)], dtype=float)
    finite = null[np.isfinite(null)]
    if finite.size == 0:
        raise NoOpNull("零分布全是 NaN / inf")
    # 浮点噪声也算没有方差(T-171:块置换不改变均值,零分布跨度 5e-19 就过了 `== 0` 这道检查,p 值成了求和顺序的噪声)
    if np.ptp(finite) <= 1e-12 * max(1.0, float(np.abs(finite).max())):
        raise NoOpNull(f"零分布没有方差(全部 ≈ {finite[0]!r},跨度 {np.ptp(finite):.1e})—— 打乱没有改变任何东西")
    if actual is not None and math.isfinite(actual):
        same = np.isclose(finite, actual, rtol=0.0, atol=1e-12).mean()
        if same >= 0.99:
            raise NoOpNull(f"{same:.0%} 的零分布抽样等于实际值 —— 打乱没有改变任何东西")
    return null


def circular_shift(seq: Sequence[Any], rng: np.random.Generator, block: int = 1, min_shift: int = 0) -> np.ndarray:
    """整条序列循环平移一个随机偏移(偏移是 `block` 的整数倍,不为 0)。保留全部自相关,只拆开它与另一条序列的对齐。

    11-09 S-793:预注册写了「循环块置换」,盲复算读出两种实现 —— 这个(整体循环平移,p 0.014)与
    `block_permute`(块序随机置换,p 0.075)。两者是不同的零假设:预注册必须写函数名,不写描述。

    `min_shift`(11-17 T-388):偏移(按元素数)必须落在 [min_shift, n − min_shift) 内。循环平移里,
    偏移接近 0 或接近 n 就是「几乎没平移」—— 拿它当零分布等于把原序列又摆回原位。S-864 / S-866 的
    「平移 ≥ 180 天」就是这个意思,两边各自在脚本里手写了一遍,apparatus 里原来没有对应函数。
    `min_shift = 0` 时与 11-09 的旧版**逐位相同**(同一个 rng、同一个下标):旧测试不改即过。"""
    arr = np.asarray(seq, dtype=object if not np.issubdtype(np.asarray(seq).dtype, np.number) else None)
    if block < 1:
        raise ValueError("block must be ≥ 1")
    if min_shift < 0:
        raise ValueError("min_shift must be ≥ 0")
    n = len(arr)
    k = n // block
    if k < 2:
        raise ValueError("序列太短:至少要两个块才能平移")
    if min_shift == 0:
        lo, hi = 1, k                        # 旧版逐位相同:偏移 ∈ {block, 2block, …, (k−1)block}
    else:
        lo = max(1, -(-min_shift // block))            # ceil(min_shift / block):偏移 ≥ min_shift
        hi = -(-(n - min_shift) // block)              # ceil((n − min_shift) / block):偏移 < n − min_shift
        if hi <= lo:
            raise ValueError(f"min_shift={min_shift} 太大:序列只有 {n} 个元素,平移空间不够")
    return np.roll(arr, block * int(rng.integers(lo, hi)))


def percentile_of(actual: Optional[float], null: Sequence[float]) -> Optional[float]:
    """实际值在零分布里的中秩分位:(严格小于的个数 + 相等个数 / 2)/ n。空零分布或实际值不可算 ⇒ None。

    ⚠️ 这是**分位**,不是 p 值(T-313 指出):「实际值偏大才算显著」时 p 不是它,是 `p_upper`。"""
    if actual is None or not math.isfinite(actual):
        return None
    arr = np.asarray(null, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return None
    return float(((arr < actual).sum() + 0.5 * (arr == actual).sum()) / arr.size)


def _p_tail(actual: Optional[float], null: Sequence[float], upper: bool) -> Optional[float]:
    if actual is None or not math.isfinite(actual):
        return None
    arr = np.asarray(null, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return None
    hits = (arr >= actual).sum() if upper else (arr <= actual).sum()
    return float((1 + hits) / (1 + arr.size))


def p_upper(actual: Optional[float], null: Sequence[float]) -> Optional[float]:
    """单侧 p(实际值偏大才算显著):(1 + 零分布 ≥ 实际值的个数)/(1 + n)。加 1 让 p 永远不为 0 —— 1,000 次抽样最小 ≈ 0.001。"""
    return _p_tail(actual, null, upper=True)


def p_lower(actual: Optional[float], null: Sequence[float]) -> Optional[float]:
    """单侧 p(实际值偏小才算显著):(1 + 零分布 ≤ 实际值的个数)/(1 + n)。"""
    return _p_tail(actual, null, upper=False)


def p_two_sided_tail(actual: Optional[float], null: Sequence[float]) -> Optional[float]:
    """双侧 p(两倍较小的单尾):min(1, 2 × min(p_lower(actual, null), p_upper(actual, null)))。

    这是 **S-866 B 道盲复算独立选的那一种**:单尾用本模块的 `p_lower` / `p_upper`(带 +1 修正,
    单侧最小 1/(1+n)),小的那个乘 2、封顶 1。台账登记的 BTC 0.082 就是这么算出来的
    (`docs/research/s866_blind_cells.py` 里的 `min(1.0, 2.0 * min(pu, pl))` —— 同一个零分布上,
    原始占比会给出 0.081,差 0.001)。

    与 `p_two_sided_deviation` 是**两个不同的算法**:偏态零分布上两者会差到一倍(S-866:BTC 那一格
    0.149 对 0.082,正好落在 0.10 的两边)⇒ 预注册必须写函数名,不能只写「双侧 p」(S-793 同一条教训的第二次)。"""
    pl = p_lower(actual, null)
    pu = p_upper(actual, null)
    if pl is None or pu is None:
        return None
    return min(1.0, 2.0 * min(pl, pu))


def p_two_sided_deviation(actual: Optional[float], null: Sequence[float]) -> Optional[float]:
    """双侧 p(离均值的距离):零分布里**离其均值不比实际值近**的占比
    = #{null : |null − mean(null)| ≥ |actual − mean(null)|} / n。

    这是 **S-864 登记的那一种**(台账里的 0.149)。研究脚本 `docs/research/s864_same_cell.py` 里
    它也叫 `p_two_sided` —— 同一个名字在两条道上指的是两个不同的算法,这正是这张卡要治的病。

    与 `p_two_sided_tail` 是两个不同的算法 —— 偏态零分布上两者会差到一倍(S-866:BTC 那一格
    0.149 对 0.082,落在 0.10 的两边)⇒ 预注册必须写函数名(S-793 同一条教训的第二次)。"""
    if actual is None or not math.isfinite(actual):
        return None
    arr = np.asarray(null, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return None
    mu = arr.mean()
    return float((np.abs(arr - mu) >= abs(actual - mu)).mean())


# ── 快照指纹 ──────────────────────────────────────────────────────────────────

def _canon(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        x = float(v)
        return None if not math.isfinite(x) else format(x, ".12g")
    if isinstance(v, (list, tuple, np.ndarray)):
        return [_canon(x) for x in list(v)]
    return str(v)


def content_fingerprint(rows: Sequence[dict], fields: Sequence[str]) -> dict[str, Any]:
    """数据的**内容**指纹:只取 `fields`、浮点统一成 12 位有效数字、NaN / inf / None 一律记 null、按内容排序后 sha256。

    11-09(C 道复核 T-312):S-791 的指纹哈希的是缓存**文件字节** —— 同一份数据换一次抓取(行序、浮点尾数、JSON 空格)
    就是新 id,两份逻辑相同的缓存给出了 `b43df6f8…` 与 `bf52601c…`。前向记录要与历史基率「同一快照」,比的必须是内容。
    返回 {n, fields, sha256};结果 JSON 里原样写出。"""
    import hashlib
    import json as _json
    keys = list(fields)
    lines = sorted(_json.dumps([_canon(r.get(k)) for k in keys], ensure_ascii=False, separators=(",", ":")) for r in rows)
    h = hashlib.sha256()
    h.update(_json.dumps(keys, ensure_ascii=False).encode("utf-8"))
    for ln in lines:
        h.update(b"\n")
        h.update(ln.encode("utf-8"))
    return {"n": len(lines), "fields": keys, "sha256": h.hexdigest()}


# ── 走法(T-409,台账 S-882)────────────────────────────────────────────────────────
# 「到某时刻之前碰没碰到某价位、先碰哪边、两边最大走了多远」—— 交易对话里每天在说的概率都是这一类。
# 11-15 那张「周末大跌之后两边都被扫」的表,常态被读成了形态:不带条件的周末本来就 95% 至少碰一边。
# 所以这里的制表函数**强制带对照组**,少了就报错。bars = 按时间升序的 (t, open, high, low, close);t 可比较即可。

def touched_before(bars: Sequence[tuple], level: float, side: str, until: Any = None) -> bool:
    """side = "up":最高价 ≥ level;"down":最低价 ≤ level。只看 t < until 的 bar(until = None ⇒ 全部)。"""
    if side not in ("up", "down"):
        raise ValueError("side 要是 up / down")
    for b in bars:
        if until is not None and b[0] >= until:
            break
        if (b[2] >= level) if side == "up" else (b[3] <= level):
            return True
    return False


def first_touch(bars: Sequence[tuple], upper: float, lower: float, until: Any = None) -> Optional[str]:
    """先碰到哪一边:"up" / "down" / None(都没碰到)。同一根 bar 两边都碰到 ⇒ "both"(日内顺序看不见,不猜)。"""
    if not upper > lower:
        raise ValueError("upper 要大于 lower")
    for b in bars:
        if until is not None and b[0] >= until:
            break
        u, d = b[2] >= upper, b[3] <= lower
        if u and d:
            return "both"
        if u:
            return "up"
        if d:
            return "down"
    return None


def max_excursions(bars: Sequence[tuple], p0: float, until: Any = None) -> tuple[Optional[float], Optional[float]]:
    """相对 p0 的最大上冲与最大下探(比例;下探为负)。没有 bar ⇒ (None, None)。"""
    if not p0 or p0 <= 0:
        raise ValueError("p0 要为正")
    hi = lo = None
    for b in bars:
        if until is not None and b[0] >= until:
            break
        hi = b[2] if hi is None else max(hi, b[2])
        lo = b[3] if lo is None else min(lo, b[3])
    return (None, None) if hi is None else (hi / p0 - 1, lo / p0 - 1)


def base_rate_table(samples: Sequence[dict], outcomes: dict[str, Callable[[dict], Optional[bool]]],
                    condition: Callable[[dict], bool], controls: dict[str, Callable[[dict], bool]]) -> dict[str, Any]:
    """一张基率表:条件组 + 「全部样本」+ 每个对照组,每组报每个结局为真的比例。

    `controls` 至少要有一个只满足一半条件的组(S-882:只满足「跌幅大」的那一组与全条件组一样会走出大波动 ——
    没有这一组,就会把波动聚集读成形态);「全部样本」由这里自动加,不用传。结局函数返回 None = 这个样本判不了,不计入分母。"""
    if not controls:
        raise ValueError("base_rate_table 必须带至少一个半条件对照组(S-882)—— 只有条件组与全样本,常态会被读成形态")
    groups = {"condition": [s for s in samples if condition(s)], "all": list(samples)}
    for name, f in controls.items():
        if name in groups:
            raise ValueError(f"对照组名 {name!r} 与保留名冲突")
        groups[name] = [s for s in samples if f(s)]
    out: dict[str, Any] = {}
    for g, rows in groups.items():
        rec: dict[str, Any] = {"n": len(rows)}
        for o, fn in outcomes.items():
            vals = [v for v in (fn(r) for r in rows) if v is not None]
            rec[o] = {"n": len(vals), "rate": (round(sum(bool(v) for v in vals) / len(vals), 4) if vals else None)}
        out[g] = rec
    return out


# ── 打分与切分 ────────────────────────────────────────────────────────────────

def brier(p: Sequence[float], y: Sequence[float]) -> Optional[float]:
    """概率预测的 Brier 分数(越小越好);长度不同或空 ⇒ None。"""
    pp, yy = np.asarray(p, dtype=float), np.asarray(y, dtype=float)
    if pp.size == 0 or pp.size != yy.size:
        return None
    if np.any((pp < 0) | (pp > 1)) or not np.all(np.isin(yy, (0.0, 1.0))):
        raise ValueError("p ∈ [0, 1],y ∈ {0, 1}")
    return float(np.mean((pp - yy) ** 2))


def windows(dates: Sequence[str], cuts: Sequence[str]) -> list[tuple[str, np.ndarray]]:
    """按切点把日期分段:cuts = ['2023-01-01', '2025-01-01'] ⇒ [起, 2025-01-01) 与 [2025-01-01, 止]。"""
    d = np.asarray([str(x)[:10] for x in dates])
    edges = [str(c)[:10] for c in cuts]
    out = []
    for i, lo in enumerate(edges):
        hi = edges[i + 1] if i + 1 < len(edges) else None
        mask = (d >= lo) & ((d < hi) if hi else True)
        label = f"{lo} → {hi}" if hi else f"{lo} →"
        out.append((label, mask))
    return out


# ── A/B ─────────────────────────────────────────────────────────────────────

def stationary_bootstrap_index(n: int, mean_block: float, n_boot: int, rng: np.random.Generator) -> np.ndarray:
    """Politis–Romano 平稳块自助法的下标矩阵(n_boot × n)。mean_block = 1 退化为逐日独立重抽。"""
    if n < 1:
        raise ValueError("n must be ≥ 1")
    p = 1.0 / max(float(mean_block), 1.0)
    idx = np.empty((n_boot, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, n_boot)
    for t in range(1, n):
        new = rng.random(n_boot) < p
        idx[:, t] = np.where(new, rng.integers(0, n, n_boot), (idx[:, t - 1] + 1) % n)
    return idx


def ab_test(ret_a: Sequence[float], ret_b: Sequence[float], *, mean_block: float = 20.0, n_boot: int = 2000,
            seed: int = 0, alpha: float = 0.05, power: float = 0.80, days_per_year: float = 365.0) -> dict[str, Any]:
    """同一组日期上两条臂的日收益 → B 相对 A 的总差、块自助置信区间、单侧 p、MDE 与结论。

    任一侧当天不可算(NaN)⇒ 那一天两边都不计。"""
    a = np.asarray(ret_a, dtype=float)
    b = np.asarray(ret_b, dtype=float)
    if a.shape != b.shape:
        raise ValueError("ret_a 与 ret_b 必须是同一组日期")
    ok = np.isfinite(a) & np.isfinite(b) & (a > -1) & (b > -1)
    a, b = a[ok], b[ok]
    n = int(a.size)
    if n < 2 * mean_block:
        return {"n_days": n, "verdict": "不可算", "why": f"只有 {n} 天,少于两个平均块长"}
    d = np.log1p(b) - np.log1p(a)
    total = float(d.sum())
    rng = np.random.default_rng(seed)
    idx = stationary_bootstrap_index(n, mean_block, n_boot, rng)
    boot = d[idx].sum(axis=1)
    se = float(boot.std(ddof=1))
    lo, hi = np.quantile(boot, [alpha / 2, 1 - alpha / 2])
    p_b_le_a = float((boot <= 0).mean())
    p_b_ge_a = float((boot >= 0).mean())
    z = NormalDist().inv_cdf
    mde_total = (z(1 - alpha) + z(power)) * se
    years = n / days_per_year
    if p_b_le_a < alpha:
        verdict = "B > A"
    elif p_b_ge_a < alpha:
        verdict = "B < A"
    else:
        verdict = "分不开"
    return {
        "n_days": n,
        "years": round(years, 2),
        "cum_a": float(np.expm1(np.log1p(a).sum())),
        "cum_b": float(np.expm1(np.log1p(b).sum())),
        "log_diff_total": total,
        "ratio_b_over_a": float(np.exp(total)),
        "ci95_log_diff": (float(lo), float(hi)),
        "p_b_le_a": p_b_le_a,
        "p_b_ge_a": p_b_ge_a,
        "se_log_diff": se,
        "mde_log_diff_total": float(mde_total),
        "mde_log_diff_per_year": float(mde_total / years) if years > 0 else None,
        "underpowered": abs(total) < mde_total,
        "verdict": verdict,
        "mean_block": mean_block,
        "n_boot": n_boot,
    }


def newey_west_t(x: Sequence[float], lags: int = 5) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """均值的 Newey–West t(Bartlett 权重 1 − l/(L+1),方差除以 n)。→ (t, 均值, 标准误);少于 lags + 2 个有限值 ⇒ (None, None, None)。

    11-07:S-774 / T-265 的各卡在自己的脚本里各写了一份(同一写法);挪到这里,之后的卡只用这一份。
    重叠的目标(30 天窗口、周频)必须用 NW;滞后按重叠长度定(周频 30 天 ⇒ 5)。"""
    a = np.asarray([v for v in x if v is not None and np.isfinite(v)], dtype=float)
    n = len(a)
    if n < lags + 2:
        return None, None, None
    d = a - a.mean()
    var = float(d @ d) / n
    for lag in range(1, lags + 1):
        var += 2.0 * (1.0 - lag / (lags + 1.0)) * float(d[lag:] @ d[:-lag]) / n
    se = float(np.sqrt(max(var, 1e-24) / n))
    return float(a.mean() / se), float(a.mean()), se
