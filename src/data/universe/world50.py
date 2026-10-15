"""World50 —— 候选池与编制规则的纯函数(T-098 / S-577 / S-578)。

## Jazz 10-14 定的

- 全球前 50 大**可在链上持有**的资产(公司、贵金属、原生加密),参照 Nasdaq-100 的规则化做法;
  目标是险资 / 捐赠基金能买的权益组合,**不对标 BTC 与加密**。
- **不按市值加权**:等权为底 × 有界的增长 / 动量分(MSCI 动量指数的打分,倾斜限制在 0.25–4 倍);
  **不写显式上限** —— 50 个成分、2% 为底时,单一权重天然 ≤ 约 8%(S-578 实测:纯按动量比例、不设上限会在某些月份 100% 押一个资产)。
- **基准 = 等权**(衡量用);产品 = 等权 × 分数(卖的)。产品对基准的超额才是要证明的东西。

## 这里有什么

- `CANDIDATES`:候选池 v0 —— 2026-10-14 的全球前 100 大资产快照(companiesmarketcap.com,去掉 ETF)
  + 2015–2024 曾是全球龙头、今天掉出去的公司(防幸存者偏差)+ 五个主要加密资产。
  **链上形式(`onchain`)还没量**:None = 未知,不是「没有」。资格判断要等 T-098 的映射表。
- `momentum_values` / `momentum_scores`:MSCI 式动量分(6 / 12 个月、跳过最近一个月、除以波动、z 分、截 ±3、1+z 或 1/(1−z))。
- `tilt_weights`:等权 × 分数,归一。
- `select_members`:按排名选 50,带缓冲区(前 40 直接进;已在指数里的排名 ≤ 60 保留;不足 50 按排名补)。
- **增长分还没有**:只对公司有定义(营收 / 盈利增速),要 T-098 的基本面历史;贵金属与加密只用动量。

市值排名的输入(自由流通市值、贵金属的可投资存量)在 T-098 第二部分;这里只放规则。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np


@dataclass(frozen=True)
class Candidate:
    key: str            # ohlcv_daily 的 symbol
    name: str
    cls: str            # "equity" | "metal" | "crypto"
    price_source: str   # "eodhd" | "binance_hist"
    code: str           # EODHD 代码(含交易所后缀)或加密的 binance_hist 符号
    region: str
    onchain: Optional[str] = None   # None = 未测量(T-098 的映射表填)
    note: str = ""


def _eq(key: str, name: str, code: str, region: str, note: str = "") -> Candidate:
    return Candidate(key, name, "equity", "eodhd", code, region, None, note)


METALS = (
    Candidate("XAUUSD", "Gold", "metal", "eodhd", "XAUUSD.FOREX", "global"),
    Candidate("XAGUSD", "Silver", "metal", "eodhd", "XAGUSD.FOREX", "global"),
    Candidate("XPTUSD", "Platinum", "metal", "eodhd", "XPTUSD.FOREX", "global"),
)

CRYPTO = tuple(Candidate(s, n, "crypto", "binance_hist", s, "global")
               for s, n in (("BTC", "Bitcoin"), ("ETH", "Ethereum"), ("XRP", "XRP"), ("BNB", "BNB"), ("SOL", "Solana")))

_US = [
    ("NVDA", "NVIDIA"), ("AAPL", "Apple"), ("GOOGL", "Alphabet"), ("MSFT", "Microsoft"), ("AMZN", "Amazon"),
    ("META", "Meta Platforms"), ("AVGO", "Broadcom"), ("TSLA", "Tesla"), ("BRK-B", "Berkshire Hathaway"),
    ("MU", "Micron"), ("LLY", "Eli Lilly"), ("AMD", "AMD"), ("WMT", "Walmart"), ("JPM", "JPMorgan Chase"),
    ("V", "Visa"), ("XOM", "Exxon Mobil"), ("JNJ", "Johnson & Johnson"), ("INTC", "Intel"), ("MA", "Mastercard"),
    ("PLTR", "Palantir"), ("ABBV", "AbbVie"), ("CSCO", "Cisco"), ("ORCL", "Oracle"), ("CVX", "Chevron"),
    ("COST", "Costco"), ("KO", "Coca-Cola"), ("BAC", "Bank of America"), ("LRCX", "Lam Research"), ("DELL", "Dell"),
    ("AMAT", "Applied Materials"), ("PG", "Procter & Gamble"), ("MRK", "Merck"), ("CAT", "Caterpillar"),
    ("UNH", "UnitedHealth"), ("PANW", "Palo Alto Networks"), ("GE", "General Electric"), ("PM", "Philip Morris"),
    ("NFLX", "Netflix"), ("MS", "Morgan Stanley"), ("HD", "Home Depot"), ("CRWD", "CrowdStrike"), ("GEV", "GE Vernova"),
    ("GS", "Goldman Sachs"), ("TXN", "Texas Instruments"), ("ANET", "Arista Networks"), ("WFC", "Wells Fargo"),
    ("RTX", "RTX"), ("TMO", "Thermo Fisher"), ("MRVL", "Marvell"), ("KLAC", "KLA"), ("AMGN", "Amgen"),
    ("IBM", "IBM"), ("C", "Citigroup"),
]
# 美国上市的存托凭证 / 外国公司
_US_LISTED_FOREIGN = [
    ("TSM", "TSMC", "TW"), ("ASML", "ASML", "NL"), ("BABA", "Alibaba", "CN"), ("NVS", "Novartis", "CH"),
    ("ARM", "Arm Holdings", "GB"), ("RY", "Royal Bank of Canada", "CA"), ("SAP", "SAP", "DE"),
    ("MUFG", "Mitsubishi UFJ", "JP"), ("AZN", "AstraZeneca", "GB"), ("SHOP", "Shopify", "CA"), ("LIN", "Linde", "GB"),
    ("TM", "Toyota", "JP"), ("BHP", "BHP Group", "AU"), ("HSBC", "HSBC", "GB"), ("SHEL", "Shell", "GB"),
    ("TCEHY", "Tencent", "CN"),
]
# 没有美国存托凭证的本地上市(链上大概率买不到 —— 资格由 T-098 的映射决定,先放进池子才能量)
_LOCAL = [
    ("2222.SR", "Saudi Aramco", "SA"), ("005930.KO", "Samsung Electronics", "KR"), ("000660.KO", "SK Hynix", "KR"),
    ("688825.SHG", "CXMT", "CN"), ("601939.SHG", "China Construction Bank", "CN"),
    ("601288.SHG", "Agricultural Bank of China", "CN"), ("1398.HK", "ICBC", "CN"), ("601988.SHG", "Bank of China", "CN"),
    ("ROG.SW", "Roche", "CH"), ("NESN.SW", "Nestlé", "CH"), ("600519.SHG", "Kweichow Moutai", "CN"),
    ("0857.HK", "PetroChina", "CN"), ("SIE.XETRA", "Siemens", "DE"), ("OR.PA", "L'Oréal", "FR"),
    ("MC.PA", "LVMH", "FR"), ("2454.TW", "MediaTek", "TW"), ("0941.HK", "China Mobile", "CN"),
]
# 2015–2024 曾是全球龙头、今天不在前 100 的(按时点选成分时必须在池子里,否则回放有幸存者偏差)
_FORMER = [
    ("NVO", "Novo Nordisk", "DK", "US"), ("PFE", "Pfizer", "US", "US"), ("VZ", "Verizon", "US", "US"),
    ("T", "AT&T", "US", "US"), ("DIS", "Disney", "US", "US"), ("ADBE", "Adobe", "US", "US"),
    ("CRM", "Salesforce", "US", "US"), ("CMCSA", "Comcast", "US", "US"), ("PEP", "PepsiCo", "US", "US"),
    ("ABT", "Abbott", "US", "US"), ("RIO", "Rio Tinto", "GB", "US"), ("TTE", "TotalEnergies", "FR", "US"),
    ("601318.SHG", "Ping An", "CN", ""),
]

EQUITIES = tuple(
    [_eq(t, n, f"{t}.US", "US") for t, n in _US]
    + [_eq(t, n, f"{t}.US", r, "美国上市") for t, n, r in _US_LISTED_FOREIGN]
    + [_eq(t, n, t, r, "本地上市,无美国存托凭证") for t, n, r in _LOCAL]
    + [_eq(t, n, f"{t}.US" if ex == "US" else t, r, "曾经的龙头(防幸存者偏差)") for t, n, r, ex in _FORMER]
)

CANDIDATES: tuple[Candidate, ...] = METALS + CRYPTO + EQUITIES

#: 对照组(T-099):不是成分,只取复权价做比较 —— 全球股票 ACWI、Nasdaq-100(QQQ)、标普 500、美国综合债(AGG,60/40 的债那一腿)。
BENCHMARKS: tuple[Candidate, ...] = tuple(
    Candidate(t, n, "benchmark", "eodhd", f"{t}.US", "global", None, "对照组,不是成分")
    for t, n in (("ACWI", "iShares MSCI ACWI"), ("QQQ", "Invesco QQQ (Nasdaq-100)"),
                 ("SPY", "SPDR S&P 500"), ("AGG", "iShares Core US Aggregate Bond")))
SNAPSHOT = "companiesmarketcap.com Top assets by market cap, 2026-10-14(去掉 ETF);另加曾经的龙头与五个加密资产"


def eodhd_candidates() -> list[Candidate]:
    return [c for c in CANDIDATES if c.price_source == "eodhd"]


# ── 动量分(MSCI 式) ─────────────────────────────────────────────────────────

def momentum_values(month_end_closes: Sequence[float]) -> tuple[Optional[float], Optional[float]]:
    """一个资产的风险调整动量:(6 个月, 12 个月)。

    输入 = 月末收盘,旧 → 新,最后一个是**再平衡前一个月**的月末(跳过最近一个月由调用方保证:
    传入的序列截到 T−1)。动量 = P(T−1) / P(T−7) − 1 与 P(T−1) / P(T−13) − 1,各除以月收益的年化波动
    (最多 36 个月、至少 6 个月)。不到 7 个月末 ⇒ (None, None);不到 13 个 ⇒ 12 个月那一项是 None(MSCI 同样只用 6 个月)。
    不可算是 None,不是 0。(MSCI 用 3 年周收益的波动、减本地无风险利率;这里用月收益、不减无风险 —— 跨资产时同一个口径。)"""
    p = [float(x) for x in month_end_closes if x is not None and math.isfinite(float(x)) and float(x) > 0]
    if len(p) < 7:
        return None, None
    r = np.diff(np.log(p))[-36:]
    vol = float(np.std(r, ddof=1) * math.sqrt(12)) if len(r) >= 6 else float("nan")
    if not vol > 0:
        return None, None
    m6 = (p[-1] / p[-7] - 1) / vol
    m12 = (p[-1] / p[-13] - 1) / vol if len(p) >= 13 else None
    return m6, m12


def _z(values: dict[str, float]) -> dict[str, float]:
    a = np.array(list(values.values()), dtype=float)
    if len(a) < 2 or not np.std(a, ddof=1) > 0:
        return {k: 0.0 for k in values}
    m, sd = a.mean(), a.std(ddof=1)
    return {k: (v - m) / sd for k, v in values.items()}


def momentum_scores(values: dict[str, tuple[Optional[float], Optional[float]]]) -> dict[str, float]:
    """横截面打分:6 / 12 个月各取 z → 0.5 / 0.5 合成(缺 12 个月就只用 6 个月)→ 再标准化 → 截 ±3 →
    z > 0 时 1 + z,z < 0 时 1 / (1 − z)。分数落在 [0.25, 4]。没有 6 个月动量的资产不出分(不在结果里)。"""
    ok = {k: v for k, v in values.items() if v[0] is not None}
    if not ok:
        return {}
    z6 = _z({k: v[0] for k, v in ok.items()})
    have12 = {k: v[1] for k, v in ok.items() if v[1] is not None}
    z12 = _z(have12) if len(have12) >= 2 else {}
    comb = {k: (0.5 * z6[k] + 0.5 * z12[k]) if k in z12 else z6[k] for k in ok}
    zc = _z(comb)
    out = {}
    for k, z in zc.items():
        z = max(-3.0, min(3.0, z))
        out[k] = 1.0 + z if z > 0 else 1.0 / (1.0 - z)
    return out


def tilt_weights(members: Sequence[str], scores: dict[str, float]) -> dict[str, float]:
    """等权为底 × 分数,归一。成分没有分数 ⇒ ValueError(资格规则应该先把它挡在外面,不在这里补 1)。"""
    missing = [m for m in members if m not in scores]
    if missing:
        raise ValueError(f"这些成分没有分数,不能定权重:{missing[:5]}")
    raw = {m: scores[m] for m in members}
    tot = sum(raw.values())
    return {m: v / tot for m, v in raw.items()}


def equal_weights(members: Sequence[str]) -> dict[str, float]:
    """基准:等权。"""
    n = len(members)
    return {m: 1.0 / n for m in members} if n else {}


# ── 选成分(带缓冲区) ─────────────────────────────────────────────────────────

def select_members(ranked: Sequence[str], previous: Sequence[str] = (), n: int = 50,
                   add_rank: int = 40, retain_rank: int = 60) -> list[str]:
    """`ranked` = 合格资产按排序口径从大到小。规则(参照 Nasdaq-100 的缓冲做法):
    排名 ≤ add_rank 的直接进;已在指数里、排名 ≤ retain_rank 的保留;合计超过 n 就从排名最低的「保留者」里去掉;
    不足 n 就按排名补。返回按排名排序的成分。"""
    if not (0 < add_rank <= n <= retain_rank):
        raise ValueError("要求 0 < add_rank ≤ n ≤ retain_rank")
    rank = {k: i + 1 for i, k in enumerate(ranked)}
    prev = set(previous)
    chosen = [k for k in ranked if rank[k] <= add_rank]
    kept = [k for k in ranked if k in prev and add_rank < rank[k] <= retain_rank]
    members = chosen + kept
    if len(members) > n:
        members = chosen + kept[: n - len(chosen)]
    for k in ranked:
        if len(members) >= n:
            break
        if k not in members:
            members.append(k)
    return sorted(members, key=lambda k: rank[k])
