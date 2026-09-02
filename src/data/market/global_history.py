"""全局市值与 BTC 主导率的**历史轨迹** (S-268).

## 为什么是轨迹不是当前值

`HIGH_DIM_ONTOLOGY.md` §5b-bis 把 ⓪ 层(风格/流动性周期判断)称作
「**我们最该建的能力,不是③层的一个信号变体**」,并且写明它的判据不同 ——
不是「提升 Sharpe」,而是「在崩塌里是否把回撤显著削掉」。

一个只知道**此刻**主导率是 59% 的系统,回答不了 ⓪ 层的任何问题。
拐点是轨迹的性质,不是水平的性质。

而实测 2026-09-01:`/global` 在 `data_layer` 里是 **ephemeral** —— 每次读了给
页面,从不落库。**所以主导率一天历史都没有**,不是因为拿不到。
`/global/market_cap_chart` 是 Analyst 档独有(Basic ✗),我们付着钱没调过。

## 不重建主导率 —— 厂商已经算好了

初版我写成 `dominance = btc_market_cap / total_market_cap`,分子取
`/coins/bitcoin/market_chart`。**preflight 的 S-195 守卫当场拦下**,理由是
`market_chart` 返回的是采样点不是收盘,禁止出现在任何收益/mark 路径。

我第一反应是「我算的是比值不是收益,应该可以豁免」—— **那正是这条守卫
存在的原因**,而且 `_S195_KNOWN` 那份冻结名单明写「只能减」,往里加新条目
是侵蚀不是例外。

想下去发现守卫救了我一个更实的问题:**两条独立采样的序列做比值,
会在分子分母两边各引入一份互不相关的采样噪声** —— 比单条序列更糟,不是更好。

而 `/global` 本来就返回 `market_cap_percentage.btc`,**是厂商自己算的主导率**。
所以正确做法是**每天把它落下来**,而不是用两条序列去重建一个已经存在的数。

    forward   /global 的 market_cap_percentage.btc —— 精确,无重建,无对齐问题
    backfill  /global/market_cap_chart 的总市值轨迹(Analyst 独有)——
              一次调用一个响应,market_cap 与 volume 天然对齐

代价是主导率的历史**从今天开始攒**。那是诚实的代价:
在此之前它一天都没有,而一个重建出来的历史看起来会像真的。

## `build()` 仍然留着,因为对齐这件事本身还会遇到

任何时候要把两条来自不同端点的日频序列拼起来,静默的外连接都会产生一条
**形状对、数值错**的曲线 —— 每隔几天用错一次分母,而结果仍落在看起来正常的
区间里,肉眼查不出来。这是「两个东西合并成一个表示」的时间维版本。
所以内连接 + 报损耗这套留作通用工具。

## 这条序列对 Jazz 那个论点的作用

「TradFi 边际转进加密」如果为真,应该在**主导率的方向**上留下痕迹:
资金先进 BTC(主导率升)还是先进山寨与基础设施(主导率降),是两种不同的流。
**当前值对此完全沉默,轨迹才有答案。**
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Iterable, Optional

CG_BASE = "https://pro-api.coingecko.com/api/v3"

#: 内连接后至少要剩这么多天,否则判 THIN —— 一条 5 个点的「轨迹」不是轨迹。
MIN_ALIGNED_DAYS = 30
#: 对齐损耗超过这个比例即使天数够也要报出来:损耗大说明两个端点的采样在漂,
#: 而漂本身是下一次静默错误的前兆。
MAX_ALIGN_LOSS = 0.20

OK, THIN, MISALIGNED, NO_DATA = "ok", "thin", "misaligned", "no_data"


@dataclass(frozen=True)
class DominancePoint:
    d: str
    btc_mcap: float
    total_mcap: float

    @property
    def dominance(self) -> float:
        return self.btc_mcap / self.total_mcap


@dataclass(frozen=True)
class DominanceSeries:
    """轨迹 + 它是怎么拼出来的。

    `points` 与 `verdict` 分开(S-263/S-266/S-267 同一形状):一条 misaligned
    的序列仍然是序列,调用方有权同时拿到它和它的成色。
    """
    points: list
    verdict: str
    reason: str
    n_btc_days: int = 0
    n_total_days: int = 0
    n_aligned: int = 0

    @property
    def usable(self) -> bool:
        return self.verdict == OK

    @property
    def align_loss(self) -> Optional[float]:
        """内连接丢掉了多少 —— 相对两条序列里较短的那条。"""
        base = min(self.n_btc_days, self.n_total_days)
        return None if not base else 1 - self.n_aligned / base


def _to_daily(pairs: Iterable, *, label: str) -> dict[str, float]:
    """CG 的 `[[ms, value], ...]` → `{YYYY-MM-DD: value}`。

    同一天出现多个点时**保留最后一个**(当日最新),并且这是一个显式选择:
    默认的 dict 覆盖行为恰好也是最后一个,但依赖「恰好」就是下一个静默错误。
    """
    out: dict[str, float] = {}
    for item in pairs or []:
        try:
            ts, val = item[0], item[1]
        except (TypeError, IndexError, KeyError):
            continue
        if val is None:
            continue                      # I1:未测不落成 0
        try:
            d = dt.datetime.utcfromtimestamp(float(ts) / 1000.0).date().isoformat()
            out[d] = float(val)
        except (TypeError, ValueError, OSError, OverflowError):
            continue
    return out


def build(btc_market_caps: Iterable, global_market_caps: Iterable) -> DominanceSeries:
    """两条序列 → 主导率轨迹。**按日期内连接,损耗要报出来。**"""
    btc = _to_daily(btc_market_caps, label="btc")
    tot = _to_daily(global_market_caps, label="global")
    if not btc or not tot:
        return DominanceSeries(
            [], NO_DATA,
            f"btc {len(btc)} 天 / global {len(tot)} 天 —— 至少一条是空的",
            len(btc), len(tot), 0)

    common = sorted(set(btc) & set(tot))
    pts = [DominancePoint(d, btc[d], tot[d]) for d in common
           if tot[d] and tot[d] > 0]

    def _pack(verdict, reason):
        return DominanceSeries(pts, verdict, reason, len(btc), len(tot), len(pts))

    if len(pts) < MIN_ALIGNED_DAYS:
        return _pack(THIN,
                     f"内连接后只剩 {len(pts)} 天(btc {len(btc)} / global {len(tot)}),"
                     f"不足 {MIN_ALIGNED_DAYS} —— 一条这么短的「轨迹」回答不了 ⓪ 层"
                     f"的任何问题,拐点是轨迹的性质")

    loss = 1 - len(pts) / min(len(btc), len(tot))
    if loss > MAX_ALIGN_LOSS:
        return _pack(MISALIGNED,
                     f"对齐损耗 {loss:.1%} > {MAX_ALIGN_LOSS:.0%}:两个端点的采样时刻在漂。"
                     f"**曲线仍会画得很好看** —— 形状对、数值错,肉眼查不出来。"
                     f"先确认两条序列的采样节奏,不要直接用")

    return _pack(OK,
                 f"{len(pts)} 天对齐(btc {len(btc)} / global {len(tot)},"
                 f"损耗 {loss:.1%});主导率 "
                 f"{pts[0].dominance:.1%} → {pts[-1].dominance:.1%}")


def trend(series: DominanceSeries, *, window: int = 30) -> Optional[dict]:
    """主导率在最近 `window` 天的方向。**不可用的序列返回 None,不给一个方向。**

    「资金先进 BTC(主导率升)还是先进山寨/基础设施(主导率降)」是两种不同的流,
    而这正是 Jazz 那个 TradFi→crypto 边际转换论点唯一能在这条序列上留下的痕迹。
    """
    if not series.usable or len(series.points) < window + 1:
        return None
    a, b = series.points[-window - 1], series.points[-1]
    delta = b.dominance - a.dominance
    return {
        "from": a.d, "to": b.d,
        "dominance_start": round(a.dominance, 4),
        "dominance_end": round(b.dominance, 4),
        "delta_pp": round(delta * 100, 2),
        # 方向词是描述,不是持仓建议 —— 规则 #1 的用语在这里不适用(不是资产评级),
        # 但仍然避免任何指示性动词。
        "direction": "toward_btc" if delta > 0.005
                     else ("toward_alt_and_infra" if delta < -0.005 else "flat"),
    }


def dominance_from_global(payload: dict) -> Optional[float]:
    """从 `/global` 的响应里取**厂商自己算的**主导率(0–1)。

    不重建,不推断。取不到就是 None —— 一个缺失的主导率和一个 0% 的主导率
    是两回事(I1),而后者会让任何依赖它的判据全部翻向。
    """
    try:
        pct = ((payload or {}).get("data") or {}).get("market_cap_percentage") or {}
        v = pct.get("btc")
        return None if v is None else float(v) / 100.0
    except (TypeError, ValueError, AttributeError):
        return None


async def fetch_today(*, client=None) -> dict:
    """今天的一个点:总市值 + 厂商算的 BTC 主导率。**一次调用。**

    这是前向序列的采集口 —— 每天落一个点,攒出来的轨迹是精确的。
    """
    import os

    import httpx
    key = os.environ.get("COINGECKO_API_KEY", "")
    if not key:
        raise RuntimeError("COINGECKO_API_KEY 未设置(S-246:仓库不加载 .env)")
    own = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        r = await client.get(f"{CG_BASE}/global",
                             headers={"x-cg-pro-api-key": key})
        r.raise_for_status()
        j = r.json() or {}
        data = (j.get("data") or {})
        total = (data.get("total_market_cap") or {}).get("usd")
        return {
            "d": dt.date.today().isoformat(),
            "total_market_cap_usd": None if total is None else float(total),
            "btc_dominance": dominance_from_global(j),
            "source": "coingecko_pro:/global",
            # 主导率是厂商算的,不是我们重建的 —— 这个标记让下游能区分
            # 「精确值」与任何将来可能出现的重建值(S-195 的教训)。
            "dominance_is_vendor_computed": True,
        }
    finally:
        if own:
            await client.aclose()


async def fetch_total_mcap_history(days: int = 365, *, client=None) -> dict:
    """总市值 + 成交量的历史轨迹。**Analyst 档独有**(`/global/market_cap_chart`)。

    一次调用一个响应,`market_cap` 与 `volume` 两个数组天然同步 ——
    **没有跨端点对齐问题**,这也是它比重建主导率更可靠的原因。
    """
    import os

    import httpx
    key = os.environ.get("COINGECKO_API_KEY", "")
    if not key:
        raise RuntimeError("COINGECKO_API_KEY 未设置(S-246:仓库不加载 .env)")
    own = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        r = await client.get(f"{CG_BASE}/global/market_cap_chart",
                             headers={"x-cg-pro-api-key": key},
                             params={"days": days})
        r.raise_for_status()
        chart = (r.json() or {}).get("market_cap_chart") or {}
        mcap = _to_daily(chart.get("market_cap"), label="total_mcap")
        vol = _to_daily(chart.get("volume"), label="total_volume")
        return {"n_days": len(mcap), "market_cap": mcap, "volume": vol,
                "source": "coingecko_pro:/global/market_cap_chart"}
    finally:
        if own:
            await client.aclose()
