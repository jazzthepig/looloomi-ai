"""大类资产要跟指数/现货,不跟 ETF —— **ETF 是产品** (S-275).

## Jazz 的纠正(2026-09-02)

> 「我们要跟踪大类资产价格,**要找对资产的指数先,etf 是产品**,
> 所以你现在的逻辑不对的,价格也不会对。」

对的,而且这作废了 S-274 报出的分位数(见该条 ERRATUM)。

## 我错在哪:把「价格」和「被剥掉收益的价格」当成同一种东西

`ohlcv_daily` 的 TradFi 面板 **14 个 symbol 全是 ETF**,没有一个指数、
一个现货、一个收益率序列。而 ETF 的**收盘价**与它所代表的资产之间隔着:

    ① 分配泄漏   TLT 按月付息 —— 票息**是债券回报的主体**,而它不在价格里
    ② 展期损益   USO 是期货 ETF,contango 时年化拖累可达 −30%
    ③ carry      FXY 持日元近零息 vs 美元有息,利差被剥掉
    ④ 费率       GLD ~0.40%/年
    ⑤ 恒定久期   TLT 每月滚动,**从不代表同一个工具两次**

又是当天那个形状:**两个不同的状态塌进一个表示**(S-206→S-274)。
`close` 这一列同时承载「资产的价格」和「资产的价格减去它的收益流」,
而下游没有任何字段能把它们分开。

## 但「ETF 不能用」是个太粗的结论 —— 泄漏是可量化的

4%/年的票息在 **1 个月**上是 0.33%(可忽略),在 **7 年**上是 30%(致命)。
所以正确的约束不是二元的能/不能,而是:

> **这个代理最多能撑多长的窗口。**

`max_horizon_days()` 把泄漏率换算成一个天数。于是现有面板不是垃圾 ——
它在短窗口上可用、长窗口上不可用,**而代码会说出是哪一个**。

实测后果:GLD 支持约 5 年的比较,**TLT 只支持约半年**。
而 S-274 用的是 7 年和 11 年 —— 在窗口这个维度上差了一个数量级。

## 第二条,也是更根本的:不同大类的「价格」不是同一种量

    收益率  DGS10        一个水平(%)
    汇率    USDJPY       一个比率
    指数    GSPC         一个水平(点)
    信用    HY OAS       一个差(bp)

**`DGS10 / XAU` 这个比值没有意义。** 所以每个序列声明自己的 `unit`,
而 `can_ratio()` **拒绝跨不兼容单位形成比价**。

分位数则对所有单位都成立 —— 那正是 Jazz 要的那样东西,
且它不需要两个序列可比。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# ── 单位类型:决定哪些运算合法 ─────────────────────────────────────────────
LEVEL = "level"        # 指数点位、现货价 —— 可比价、可算收益率
RATE = "rate_pct"      # 收益率、通胀预期 —— **不可比价**,只能看水平与变化
SPREAD = "spread_bp"   # 信用利差 —— 同上
FX = "fx_rate"         # 汇率,本身已是比价 —— 可与 LEVEL 换算,不可再相除

#: 只有这些单位之间做比价才有意义。
RATIOABLE = {LEVEL, FX}

# ── 回报口径 ───────────────────────────────────────────────────────────────
TOTAL_RETURN = "total_return"     # 含收益再投资 —— 长窗口唯一正确的口径
PRICE_RETURN = "price_return"     # 剥掉收益 —— **有泄漏**
SPOT = "spot"                     # 现货价/汇率,无收益概念
YIELD = "yield"                   # 本身就是收益率

#: 可接受的累计失真。超过它,这个代理在该窗口上不可用。
#: 取 2%:小于大多数跨资产结论的效应量,**大于它就会改变结论的方向**。
TOLERANCE = 0.02

TRADING_DAYS_YR = 252

#: `leak_bps_yr` 全是**手估的量级**,不是测出来的。所以两个估计值之差
#: **不可能比估计本身更精确** —— 而 `abs(400-400)=0 → 上限 3968 年`
#: 正是这种假精确:两个 400 是我凑出来的,不是量出来的。
#:
#: 差值因此有下界。取 50bp:大约是这些估计各自的量级不确定性。
#: **一个「相消」的比价仍然有窗口上限,只是很长。**
LEAK_ESTIMATE_UNCERTAINTY_BPS = 50


@dataclass(frozen=True)
class Series:
    """一个可跟踪的序列 —— **它是资产本身,还是一个有泄漏的代理。**"""
    key: str
    asset: str                     # 大类资产(规范名)
    unit: str
    convention: str
    #: 年化收益泄漏(基点)。`0` = 无泄漏;**`None` = 未量化**,
    #: 而未量化不等于没有 —— 它意味着这个序列**还不能用于任何跨期比较**。
    leak_bps_yr: Optional[int]
    source: str
    is_proxy: bool
    note: str = ""

    @property
    def max_horizon_days(self) -> Optional[int]:
        """在 `TOLERANCE` 之内,这个序列最多能撑多长的窗口(交易日)。

        `None` = 泄漏未量化 ⇒ **任何窗口都不该用**,而不是「随便用」。
        """
        if self.leak_bps_yr is None:
            return None
        if self.leak_bps_yr <= 0:
            return 10 ** 6                       # 无泄漏,不设限
        yrs = TOLERANCE / (self.leak_bps_yr / 10_000.0)
        return max(1, int(yrs * TRADING_DAYS_YR))

    def usable_over(self, days: int) -> bool:
        h = self.max_horizon_days
        return h is not None and days <= h


#: **权威对象** —— 每个大类应该跟的东西。EODHD 后缀已标注;
#: 我们现有代码**每一处都硬编码 `.US`**,从没用过 `.INDX/.FOREX/.GBOND/.COMM`。
CANONICAL: dict[str, Series] = {
    "gold": Series("XAUUSD.FOREX", "gold", LEVEL, SPOT, 0,
                   "eodhd:.FOREX", False, "伦敦金现货 —— 无费率无分配"),
    "silver": Series("XAGUSD.FOREX", "silver", LEVEL, SPOT, 0,
                     "eodhd:.FOREX", False),
    "ust_10y": Series("US10Y.GBOND", "ust_10y", RATE, YIELD, 0,
                      "eodhd:.GBOND", False,
                      "**收益率不是价格** —— 不可与任何 LEVEL 做比价"),
    "ust_30y": Series("US30Y.GBOND", "ust_30y", RATE, YIELD, 0,
                      "eodhd:.GBOND", False),
    "ust_2y": Series("US2Y.GBOND", "ust_2y", RATE, YIELD, 0,
                     "eodhd:.GBOND", False),
    "jgb_10y": Series("JP10Y.GBOND", "jgb_10y", RATE, YIELD, 0,
                      "eodhd:.GBOND", False,
                      "日债收益率 —— 套息交易的一条腿,S-273 缺的就是它"),
    "usdjpy": Series("USDJPY.FOREX", "usdjpy", FX, SPOT, 0,
                     "eodhd:.FOREX", False,
                     "**S-273 说的那个层面就在这里** —— 不是 FXY"),
    "us_equity": Series("GSPC.INDX", "us_equity", LEVEL, PRICE_RETURN, 130,
                        "eodhd:.INDX", False,
                        "价格指数,分红不在内(~1.3%/年)。总回报版是 SP500TR.INDX"),
    "us_equity_tr": Series("SP500TR.INDX", "us_equity", LEVEL, TOTAL_RETURN, 0,
                           "eodhd:.INDX", False, "长窗口用这个"),
    "wti": Series("CL.COMM", "wti", LEVEL, SPOT, 0, "eodhd:.COMM", False,
                  "近月现货 —— **不是 USO**,后者有展期损益"),
    "brent": Series("BRENT.COMM", "brent", LEVEL, SPOT, 0, "eodhd:.COMM", False),
    "vix": Series("VIX.INDX", "vix", LEVEL, SPOT, 0, "eodhd:.INDX", False),
}

#: **我们今天实际持有的东西** —— 全是产品,不是资产。
#: `leak_bps_yr` 是各自结构性泄漏的量级估计(费率 + 分配 + carry + 展期)。
#: 这张表存在的唯一目的:让「我们用的是代理」这件事**在代码里可读**,
#: 而不是靠人记得。
HELD_PROXIES: dict[str, Series] = {
    "GLD": Series("GLD", "gold", LEVEL, PRICE_RETURN, 40, "yfinance/eodhd", True,
                  "仅费率 —— 现有面板里最干净的一个"),
    "SLV": Series("SLV", "silver", LEVEL, PRICE_RETURN, 50, "yfinance/eodhd", True),
    "SPY": Series("SPY", "us_equity", LEVEL, PRICE_RETURN, 130, "yfinance/eodhd",
                  True, "分红泄漏"),
    "EEM": Series("EEM", "em_equity", LEVEL, PRICE_RETURN, 250, "yfinance/eodhd",
                  True),
    "TLT": Series("TLT", "ust_long", LEVEL, PRICE_RETURN, 400, "yfinance/eodhd",
                  True, "**票息是债券回报的主体,而它不在价格里**;且恒定久期滚动"),
    "IEF": Series("IEF", "ust_7_10y", LEVEL, PRICE_RETURN, 350, "yfinance/eodhd",
                  True),
    "SHY": Series("SHY", "ust_1_3y", LEVEL, PRICE_RETURN, 400, "yfinance/eodhd",
                  True),
    "LQD": Series("LQD", "ig_credit", LEVEL, PRICE_RETURN, 450, "yfinance/eodhd",
                  True),
    "HYG": Series("HYG", "hy_credit", LEVEL, PRICE_RETURN, 600, "yfinance/eodhd",
                  True, "高收益票息 —— 泄漏仅次于 USO"),
    "TIP": Series("TIP", "us_tips", LEVEL, PRICE_RETURN, 350, "yfinance/eodhd",
                  True),
    "VNQ": Series("VNQ", "us_reit", LEVEL, PRICE_RETURN, 400, "yfinance/eodhd",
                  True),
    "FXY": Series("FXY", "usdjpy", LEVEL, PRICE_RETURN, 400, "yfinance/eodhd",
                  True, "carry 被剥掉 —— 2022–24 美日利差高达 5%/年"),
    "UUP": Series("UUP", "usd_index", LEVEL, PRICE_RETURN, 100, "yfinance/eodhd",
                  True),
    "USO": Series("USO", "wti", LEVEL, PRICE_RETURN, 3000, "yfinance/eodhd", True,
                  "**期货展期** —— contango 时年化可达 −30%,与油价长期脱钩。"
                  "这个代理在任何有意义的窗口上都不可用"),
}


def ratio_leak_bps(a: Series, b: Series) -> Optional[int]:
    """比价 A/B 自身的年化失真 = **两者泄漏之差**。

    ⚠️ 这个函数是跑完第一版才补的。第一版 `can_ratio` 只比对 `convention`,
    于是 `GLD/TLT` 判 True —— 两者都是 `PRICE_RETURN`,**而泄漏是 40 vs 400,
    差十倍**。一个标签装着两个差异巨大的状态,正是本模块开头批评的那个形状,
    我在写守卫时又犯了一次。

    差额而非绝对值的理由:同向同量的泄漏在比值里**相消**。
    两个都漏 400bp 的债券 ETF 相比,比值是干净的;GLD 比 TLT 不是。
    """
    if a.leak_bps_yr is None or b.leak_bps_yr is None:
        return None
    raw = abs(a.leak_bps_yr - b.leak_bps_yr)
    # 两边都申报 0(现货/总回报,**结构上**无泄漏)才允许 0;
    # 否则差值不能声称比估计本身更精确。
    if a.leak_bps_yr == 0 and b.leak_bps_yr == 0:
        return 0
    return max(raw, LEAK_ESTIMATE_UNCERTAINTY_BPS)


def ratio_max_horizon_days(a: Series, b: Series) -> Optional[int]:
    """比价能撑多长的窗口。**由泄漏之差决定,不由任一边决定。**"""
    d = ratio_leak_bps(a, b)
    if d is None:
        return None
    if d <= 0:
        return 10 ** 6
    return max(1, int((TOLERANCE / (d / 10_000.0)) * TRADING_DAYS_YR))


def can_ratio(a: Series, b: Series, *, window_days: Optional[int] = None) -> tuple:
    """两个序列能否做比价 → `(bool, 原因)`。

    **这是本模块的守卫。** 拒绝有四类:
      ① 单位不兼容 —— `US10Y / XAU` 没有意义
      ② 两个都是汇率 —— 再相除是交叉汇率,要显式建模
      ③ 口径不一致 —— 一个含收益、一个剥掉
      ④ **泄漏之差在给定窗口上超过容差** —— 口径相同也救不了
         (给了 `window_days` 才检查;不给则只报上限)
    """
    if a.unit not in RATIOABLE or b.unit not in RATIOABLE:
        bad = a if a.unit not in RATIOABLE else b
        return False, (f"{bad.key} 的单位是 {bad.unit} —— **收益率/利差不是价格,"
                       f"不能做比价**。它可以看水平和分位,不能做分母或分子")
    if a.unit == FX and b.unit == FX:
        return False, "两个都是汇率(本身已是比价)—— 再相除得到的是交叉汇率,请显式建模"
    if a.convention != b.convention:
        return False, (f"口径不一致:{a.key}={a.convention} vs {b.key}={b.convention}。"
                       f"**比值会把两者收益流的差额算成价格变化**")

    d, h = ratio_leak_bps(a, b), ratio_max_horizon_days(a, b)
    if d is None:
        return False, (f"{a.key} 或 {b.key} 的泄漏未量化 —— "
                       f"**未量化不等于没有**,在量化之前不可用于跨期比较")
    if window_days is not None and h is not None and window_days > h:
        return False, (f"口径一致但**泄漏之差 {d}bp/年**({a.key} {a.leak_bps_yr} vs "
                       f"{b.key} {b.leak_bps_yr}):这个比价最多撑 {h} 个交易日"
                       f"({h / TRADING_DAYS_YR:.2f} 年),而要求的是 {window_days} 天。"
                       f"**同一个 convention 标签装着差十倍的泄漏**")
    return True, (f"单位与口径一致;泄漏之差 {d}bp/年 ⇒ 该比价最多撑 "
                  f"{'不设限' if h and h > 10 ** 5 else str(h) + ' 个交易日'}")


def horizon_verdict(series_list, window_days: int) -> dict:
    """一组序列在给定窗口上是否可用。**回答的是「这个窗口」,不是「能不能用」。**"""
    rows = []
    for s in series_list:
        h = s.max_horizon_days
        rows.append({
            "key": s.key, "asset": s.asset, "is_proxy": s.is_proxy,
            "leak_bps_yr": s.leak_bps_yr,
            "max_horizon_days": None if h is None or h > 10 ** 5 else h,
            "ok": s.usable_over(window_days),
        })
    bad = [r for r in rows if not r["ok"]]
    worst = min((r for r in rows if r["max_horizon_days"]),
                key=lambda r: r["max_horizon_days"], default=None)
    return {
        "window_days": window_days,
        "n": len(rows), "n_blocking": len(bad),
        "blocking": [r["key"] for r in bad],
        "binding_constraint": worst["key"] if worst else None,
        "rows": rows,
        "reason": (
            f"{len(bad)}/{len(rows)} 个序列在 {window_days} 个交易日的窗口上"
            f"泄漏超过 {TOLERANCE:.0%} 容差:{[r['key'] for r in bad]}。"
            f"**窗口由泄漏最大的那个决定**"
            f"({worst['key']} 只撑得住 {worst['max_horizon_days']} 天)"
            if bad else
            f"{len(rows)} 个序列在 {window_days} 天窗口上泄漏均在容差内"),
    }


def gap_report() -> dict:
    """我们持有什么 vs 应该持有什么。**这张表是采购单。**"""
    have_canon = set()
    missing = {k: v for k, v in CANONICAL.items() if k not in have_canon}
    return {
        "n_canonical": len(CANONICAL),
        "n_held_canonical": 0,
        "n_held_proxies": len(HELD_PROXIES),
        "missing_suffixes": sorted({v.source for v in missing.values()}),
        "worst_proxies": sorted(
            ({"key": k, "leak_bps_yr": v.leak_bps_yr,
              "max_horizon_days": v.max_horizon_days}
             for k, v in HELD_PROXIES.items()),
            key=lambda r: -(r["leak_bps_yr"] or 0))[:5],
        "reason": (
            f"TradFi 面板 {len(HELD_PROXIES)} 个 symbol **全部是 ETF 产品**,"
            f"规范对象 0 个。现有代码每一处都硬编码 `.US`,"
            f"从未用过 .INDX/.FOREX/.GBOND/.COMM —— "
            f"**缺口是后缀,不是数据源**(EODHD 已付费)"),
    }
