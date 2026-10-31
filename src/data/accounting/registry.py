"""v0.2 阶段 1 —— 策略登记表 + 统一口径的成绩单。

**登记表只增不删**(v0.2 原则 P2):每本纸面账本一行,写清它是哪一层、靠什么因、记账是否已走公用内核、
基准是什么。权重可以降到 0,登记永远在。

**成绩单** = 所有账本在同一口径下并排:起点、最新一天、缺了几天、总收益、同期「持有同一面板」的收益、
差值、最大回撤。**哪些账本的记账还没迁到公用内核,成绩单上明说** —— 那一列的数字还是它自己的记账算的。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Book:
    id: str
    layer: str                 # ① ② ③ ④ ⓪ / 事件
    name: str
    cause: str
    table: str
    shape: str                 # 'plain' (mark_date, nav) | 'arms' (d, arm, nav) | 'hl' (d, nav jsonb)
    arm: Optional[str] = None
    accounting: str = "own"    # 'shared_kernel' | 'own'
    benchmark: str = "core"   # 'arm:<名字>' | 'core'(① 本身:10-02 前 core_alpha α=1 回放,之后 core_cap 前向;S-482)
    status: str = "paper"      # paper | dormant | retired_by_design | frozen(S-631,唯一来源 accounting/frozen.py)
    filters: dict = field(default_factory=dict)
    caveat: str = ""
    #: S-481:这几本账在 Redis 状态丢失时曾把 NAV 重置为 1.0(曲线被拼接)。它们的 `daily_return` 是每天按当时持仓
    #: 记的真收益,复利它才是连续的 NAV;表里的 `nav` 列在重置日断开。
    nav_from_returns: bool = False
    #: S-483:`mark_date` 的含义。"close" = 这一行就是市场 d 日的收盘(公用内核的账本:core_cap / β+ / 代币化 / HL);
    #: "valuation_next_day" = 在 d 日 00:05 UTC 的估值点打的标,覆盖的是 d−1 日(beta_core 与按估值点记账的那几本)。
    #: 不对齐的话,同一天比较的是两个不同交易日:beta_core 与 ① 同日相关 0.11,错一天对齐后 0.82。
    stamp: str = "close"


BOOKS: tuple[Book, ...] = (
    # S-473(Jazz 10-03「use 1」):① = 市值加权。S-556(Jazz 10-12「把单币上限 40% 解除」):10-12 收盘起 ① = cap_a1_u
    # (不设上限);在那之前 ① 的记录就是 cap_a1(单币 ≤ 40%)—— load_navs 按日期拼成一条。基准臂 ew_a0 = 同一内核下的等权。
    Book("core_cap", "①", "核心持仓(24 名市值加权,不设单币上限;10-12 前单币 ≤ 40%)", "持有市场吃 beta;FoF 的本体(S-472/S-473/S-556)",
         "core_cap_daily", "arms", arm="cap_a1_u", accounting="shared_kernel", benchmark="arm:ew_a0"),
    # 旧 ①(单币 ≤ 40%)照旧前向记账,留作「解除上限」这个决定本身的对照 —— 不是候选,不进配置。
    Book("core_cap_c40", "①", "旧核心持仓(单币 ≤ 40%,10-12 前的 ①;留作对照)", "解除上限这个决定的前向对照(S-556)",
         "core_cap_daily", "arms", arm="cap_a1", accounting="shared_kernel", benchmark="arm:ew_a0",
         caveat="对照臂:10-12 起 ① 已不设单币上限"),
    # 原 ①。S-473 起改作 ② 候选:等权 = 对二线 / 山寨的风格倾斜,外加波动率目标(③ 的成分)—— 要自己挣到权重。
    Book("beta_core", "②", "等权 + 波动率目标(原 ①,S-473 起为 ② 候选)", "面板内等权 = 风格倾斜;另含 ③ 的波动率目标",
         "beta_core_nav", "plain", filters={"void_reason": "is.null"}, benchmark="core", stamp="valuation_next_day"),
    Book("beta_plus_w", "②", "动量 + 52 周高点倾斜(周频 7 份)", "面板内超配趋势强、接近新高的币(S-428)",
         "beta_plus_daily", "arms", arm="momentum_52w_w", accounting="shared_kernel", benchmark="arm:panel_hold_w"),
    Book("beta_plus_m", "②", "动量 + 52 周高点倾斜(月频)", "同上,月频",
         "beta_plus_daily", "arms", arm="momentum_52w_m", accounting="shared_kernel", benchmark="arm:panel_hold_m"),
    # T-051 / T-052(S-491 / S-493):CIS 的本职 = 面板内倾斜。① 权重 × exp(0.5·z_CIS),单币 ≤ 40%,起点 10-06。
    Book("cis_tilt", "②", "CIS 倾斜(① 内按 CIS 超配,k=0.5)", "CIS 的岗位是 ②:在持有的面板内决定超配谁(§5b)",
         "cis_tilt_daily", "arms", arm="cis_a1", accounting="shared_kernel", benchmark="core"),
    # T-087 / S-556:③ 与组合层换到新 ①(不设单币上限)上 —— 新臂 mult_v2 / pl_v3 自 10-12 收盘起;旧臂照旧记作对照
    Book("multiplier", "③", "推力(① × 0.7–1.3 倍,按状态;底仓 = 不设上限的 ①)", "③ 的岗位是择时调敞口、永不做空(§5b);规则 10-08 预注册,零拟合参数",
         "multiplier_daily", "arms", arm="mult_v2", accounting="shared_kernel", benchmark="core"),
    # S-596(Jazz 10-16):Trader Tom 的仓位管理 —— 只看 ① 自己的价格:盈利上才加(55 日新高、每 +10% 再加 0.1)、破 20 日低撤加仓、
    # 跌破 200 日线且破 20 日低底仓降到 0.7。BTC / ETH 2015–2026 回放:点估计都高于持有、回撤更浅;前向 10-16 起
    Book("tom_overlay", "③", "Tom 仓位管理(① 上只在盈利时加仓、破位撤加仓、跌破长期趋势底仓 0.7;0.7–1.3)",
         "大赢时扩大、错时少伤:加仓只加在已经赚钱的仓位上,撤的只是加上去的部分(S-596)",
         "multiplier_daily", "arms", arm="tom_pd13", accounting="shared_kernel", benchmark="core"),
    # S-631(Jazz 10-20「根据我们的研究重新打分和开跑」):ⓠ 的信号(beta_core_nav_q 的 q_override)改挂 ① cap_a1_u,
    # 在 ③ 的同一个记账函数里单独记 NAV(原表的 nav 抄了底仓、没乘 q);再加一条「只在慢状态向下时才许减仓」的对照臂
    Book("q_overlay", "ⓠ", "ⓠ 相位覆盖(VDB 相位匹配 → 0 / 0.5 / 1 / 1.3 倍;底仓 = 不设上限的 ①)",
         "历史相位相似时调敞口(C2);10-20 起作用在 ① 上并单独记账(S-631)",
         "multiplier_daily", "arms", arm="q_v2", accounting="shared_kernel", benchmark="core"),
    Book("q_slow", "ⓠ", "ⓠ 只在慢状态向下时减仓(majors 在 200 日线上方不许减)",
         "慢状态是唯一稳定改善生存的东西(S-624 / S-627);ⓠ 在上升趋势里减半仓,前向 −3.5pp(S-631)",
         "multiplier_daily", "arms", arm="q_slow", accounting="shared_kernel", benchmark="core"),
    Book("multiplier_v1", "③", "推力 v1(底仓 = 单币 ≤ 40% 的旧 ①;留作对照)", "T-087 换底仓前的同一规则",
         "multiplier_daily", "arms", arm="mult_v1", accounting="shared_kernel", benchmark="core",
         caveat="对照臂:10-12 起 ③ 建在不设上限的 ① 上(mult_v2)"),
    Book("portfolio_layer", "组合层", "组合层 0–1 敞口(可空仓;底仓 = 不设上限的 ①)",
         "组合层可以空仓、策略层不空(DECISIONS 10-08);阈值看过 2023–26 才定,前向才是检验(S-511)",
         "portfolio_layer_daily", "arms", arm="pl_v3", accounting="own", benchmark="core"),
    Book("portfolio_layer_v2", "组合层", "组合层 v2(底仓 = 单币 ≤ 40% 的旧 ①;留作对照)", "T-087 换底仓前的同一规则",
         "portfolio_layer_daily", "arms", arm="pl_v2", accounting="own", benchmark="core",
         caveat="对照臂:10-12 起组合层建在不设上限的 ① 上(pl_v3)"),
    Book("tokenization_tilt", "②", "代币化基础设施 25% 倾斜", "TradFi 上链的通路与发行是长期主题(DECISIONS 09-26)",
         "tokenization_tilt_daily", "arms", arm="tokenization_tilt_25", accounting="shared_kernel",
         benchmark="arm:panel_hold"),
    Book("hl_mech", "①+③", "HL 4 币机械仓位(MECH_tom)", "4 币现货 + 按规则缩放仓位(M-189/M-190)",
         "hl_book_daily", "hl", arm="MECH_tom", benchmark="arm:H0_hold"),
    Book("hl_jev", "①+③", "HL 4 币 Jev 仓位(JEV_tom)", "同上,Jev 参与调整",
         "hl_book_daily", "hl", arm="JEV_tom", benchmark="arm:H0_hold"),
    Book("causal_paper", "④", "因果多空(资金费率)", "资金费率与持仓结构的多空",
         "causal_paper_nav", "plain", nav_from_returns=True, stamp="valuation_next_day"),
    Book("scalable_book", "④", "可扩展多空组合", "多策略多空",
         "scalable_book_nav", "plain", nav_from_returns=True, stamp="valuation_next_day"),
    Book("combined_book", "④", "多空合成", "多空合成",
         "combined_book_nav", "plain", nav_from_returns=True, stamp="valuation_next_day"),
    Book("dingge_paper", "事件", "Dingge 事件", "事件驱动",
         "dingge_paper_nav", "plain", stamp="valuation_next_day"),
    Book("fusion_paper", "④", "Fusion 多空", "多 sleeve 融合",
         "fusion_paper_nav", "plain", filters={"void_reason": "is.null"}, stamp="valuation_next_day",
         caveat="T-026:记录只扣成本、不记价格 —— 数字不可信"),
    Book("two_layer_paper", "—", "两层(核心待换)",
         "R57:V5c 核心多数日子不触发,此时零仓位;换上新核心(Redis 配置)即自动接上。实际净值 0.984–1.021,07-22 起有断档",
         "two_layer_paper_nav", "plain", status="retired_by_design", stamp="valuation_next_day"),
)


# S-631:冻结只在 accounting/frozen.py 登记一处 —— 这里按它改 status,不在上面逐行手改(两处登记迟早不一致)
def _apply_frozen(books: tuple[Book, ...]) -> tuple[Book, ...]:
    from dataclasses import replace

    from src.data.accounting.frozen import FROZEN
    return tuple(replace(b, status="frozen") if b.id in FROZEN else b for b in books)


BOOKS = _apply_frozen(BOOKS)

def _metrics(nav: pd.Series) -> dict[str, Any]:
    nav = nav.dropna().sort_index()
    if len(nav) < 2:
        return {"days": len(nav)}
    full = pd.date_range(nav.index.min(), nav.index.max(), freq="D")
    dd = (nav / nav.cummax() - 1).min()
    return {"start": nav.index.min().date().isoformat(), "last": nav.index.max().date().isoformat(),
            "days": len(nav), "missing_days": int(len(full) - len(nav)),
            "total_return": float(nav.iloc[-1] / nav.iloc[0] - 1), "max_drawdown": float(dd)}


def scorecard_rows(navs: dict[str, pd.Series], bench: dict[str, pd.Series]) -> list[dict]:
    """纯函数:每本账一行。基准在**同一段日期**上算(取账本的首末日)。"""
    out = []
    for b in BOOKS:
        s = navs.get(b.id)
        row: dict[str, Any] = {"id": b.id, "layer": b.layer, "name": b.name, "accounting": b.accounting,
                               "status": b.status, "caveat": b.caveat}
        if s is None or len(s.dropna()) < 2:
            # 「读不到」和「刚起步只有起点一天」是两回事,不能写成同一句(S-474)
            row["note"] = ("没有可用的 NAV" if s is None or s.dropna().empty
                           else f"只有起点一天({s.dropna().index.min().date()}),收益从下一个收盘起算")
            out.append(row)
            continue
        m = _metrics(s)
        row.update(m)
        bs = bench.get(b.id)
        if bs is not None:
            bs = bs.dropna().sort_index()
            a, z = pd.Timestamp(m["start"]), pd.Timestamp(m["last"])
            seg = bs[(bs.index >= a) & (bs.index <= z)]
            # 基准必须覆盖账本的整段:首日相差超过 3 天就不比 —— 第一版这里没查,7 月起的多空账本
            # 被拿去和 9 月起的基准比(S-456)。
            if len(seg) >= 2 and (seg.index[0] - a).days <= 3 and (z - seg.index[-1]).days <= 3:
                row["benchmark_return"] = float(seg.iloc[-1] / seg.iloc[0] - 1)
                row["benchmark_span"] = [seg.index[0].date().isoformat(), seg.index[-1].date().isoformat()]
                row["excess"] = row["total_return"] - row["benchmark_return"]
            else:
                row["note"] = "基准没有覆盖这本账的整段日期,不比"
        out.append(row)
    return out


async def load_navs() -> tuple[dict[str, pd.Series], dict[str, pd.Series]]:
    from src.data.style.header import _read_all
    navs: dict[str, pd.Series] = {}
    bench: dict[str, pd.Series] = {}
    core = await _read_all("beta_core_nav", {"select": "mark_date,nav,benchmark_nav,inception_id",
                                             "void_reason": "is.null", "order": "mark_date.asc"})
    if core:
        last_inc = core[-1]["inception_id"]
        df = pd.DataFrame([r for r in core if r["inception_id"] == last_inc])
        df.index = pd.to_datetime(df["mark_date"])
        navs["beta_core"] = df["nav"].astype(float)
    core_bench = await _core_benchmark()
    cache: dict[str, list] = {}
    for b in BOOKS:
        if b.id == "beta_core":
            bench[b.id] = core_bench
            continue
        if b.table not in cache:
            if b.shape == "plain":
                sel = ("mark_date,nav" + (",inception_id" if b.table == "fusion_paper_nav" else "")
                       + (",daily_return" if b.nav_from_returns else ""))
                cache[b.table] = await _read_all(b.table, {"select": sel, "order": "mark_date.asc", **b.filters})
            elif b.shape == "arms":
                cache[b.table] = await _read_all(b.table, {"select": "d,arm,nav", "order": "d.asc"})
            else:
                cache[b.table] = await _read_all(b.table, {"select": "d,nav", "order": "d.asc"})
        rows = cache[b.table]
        if not rows:
            continue
        if b.shape == "plain":
            if b.table == "fusion_paper_nav":
                inc = rows[-1].get("inception_id")
                rows = [r for r in rows if r.get("inception_id") == inc]
            if b.nav_from_returns:
                rets = pd.Series([float(r.get("daily_return") or 0.0) for r in rows],
                                 index=pd.to_datetime([r["mark_date"] for r in rows]))
                rets = rets[~rets.index.duplicated(keep="last")].sort_index()
                s = (1 + rets).cumprod()
            else:
                s = pd.Series([float(r["nav"]) for r in rows], index=pd.to_datetime([r["mark_date"] for r in rows]))
            navs[b.id] = s[~s.index.duplicated(keep="last")]
            bench[b.id] = core_bench
        elif b.shape == "arms":
            df = pd.DataFrame(rows)
            df["d"] = pd.to_datetime(df["d"])
            pv = df.pivot_table(index="d", columns="arm", values="nav")
            navs[b.id] = pv.get(b.arm)
            bench[b.id] = pv.get(b.benchmark.split(":", 1)[1]) if b.benchmark.startswith("arm:") else core_bench
        else:
            idx = pd.to_datetime([r["d"] for r in rows])
            navs[b.id] = pd.Series([float((r["nav"] or {}).get(b.arm, np.nan)) for r in rows], index=idx)
            bench[b.id] = pd.Series([float((r["nav"] or {}).get(b.benchmark.split(":", 1)[1], np.nan))
                                     for r in rows], index=idx)
    # S-483:按估值点打标的账本,行日期覆盖的是前一天 —— 统一到「市场日」再交给成绩单与 L3
    for b in BOOKS:
        if b.stamp == "valuation_next_day" and navs.get(b.id) is not None:
            navs[b.id] = navs[b.id].copy()
            navs[b.id].index = navs[b.id].index - pd.Timedelta(days=1)
    # S-556:① 在 10-12 收盘换了规则(解除单币上限)—— 账本 core_cap 的 NAV = 旧臂到换规则那天 + 新臂之后,按收益拼接
    if navs.get("core_cap") is not None or navs.get("core_cap_c40") is not None:
        navs["core_cap"] = stitch_core(navs.get("core_cap_c40"), navs.get("core_cap"))
    return navs, bench


def stitch_core(legacy: Optional[pd.Series], current: Optional[pd.Series]) -> Optional[pd.Series]:
    """纯函数。① 的前向 NAV:CORE_SINCE 及以前用旧臂(单币 ≤ 40%),之后用新臂(不设上限)的日收益接上去。"""
    from src.data.signals.core_cap import CORE_SINCE
    parts = []
    if legacy is not None:
        lg = legacy.dropna().sort_index()
        parts.append(lg.pct_change().dropna()[lambda x: x.index <= CORE_SINCE])
        start = lg.index[0] if len(lg) else None
    else:
        start = None
    if current is not None:
        cu = current.dropna().sort_index()
        parts.append(cu.pct_change().dropna()[lambda x: x.index > CORE_SINCE])
        if start is None and len(cu):
            start = cu.index[0]
    if not parts or start is None:
        return None
    rets = pd.concat(parts).sort_index()
    rets = rets[~rets.index.duplicated(keep="first")]
    nav = (1 + rets).cumprod()
    return pd.concat([pd.Series({start: 1.0}), nav]).sort_index()[lambda x: ~x.index.duplicated(keep="first")]


def panel_ew_nav(close: pd.DataFrame) -> pd.Series:
    """① 的面板等权持有(每日再平衡):当天与前一天都有真实收盘的币的平均日收益,复利。缺一整天时不跨缺口。"""
    close = close.sort_index()
    r = close / close.shift(1) - 1
    gap = close.index.to_series().diff() != pd.Timedelta(days=1)
    r[gap.values] = np.nan
    daily = r.mean(axis=1, skipna=True).fillna(0.0)
    return (1 + daily).cumprod()


async def _panel_ew_benchmark() -> Optional[pd.Series]:
    """多空 / 事件账本的基准:持有 ① 的同一个 24 名面板(binance_hist,与 β+ 研究同源)。"""
    from src.data.market.panel_read import read_panel
    from src.research.strategies.causal_positioning import DEFAULT_UNIVERSE
    p = await read_panel(list(DEFAULT_UNIVERSE), start="2026-06-01", source="binance_hist")
    idx = pd.to_datetime(p.days)
    px = pd.DataFrame(p.close, index=idx, columns=p.symbols, dtype=float)
    px = px.mask(pd.DataFrame(p.filled, index=idx, columns=p.symbols))
    px = px.reindex(pd.date_range(idx.min(), idx.max(), freq="D"))
    return panel_ew_nav(px)


async def scorecard() -> list[dict]:
    navs, bench = await load_navs()
    return scorecard_rows(navs, bench)


async def _core_benchmark() -> Optional[pd.Series]:
    """多空 / 事件 / 无内臂账本的基准 = ① 本身(S-480:① 只有一条序列)。"""
    return await core_nav()


#: ① 10-02 之前的历史(Jazz 10-31「换」,S-700):按时点的 `cap_pit24`(逐月前 24 大市值、含死币、2019 起),
#: 不再是 `core_alpha_daily` 的今天 24 名回填(幸存者,7.8 年多报 32%)。那条函数留作研究对照(/api/v1/research/core-alpha)。
HISTORY_ARM = "cap_pit24"
HISTORY_TABLE = "core_variants_daily"


async def core_nav(start: str = "2026-06-01") -> Optional[pd.Series]:
    """① 的逐日 NAV —— 全系统只这一个读法(成绩单基准、L3、T-048 状态层都从这里取)。

    10-02 及以前:`core_variants_daily` 的 `cap_pit24`(S-700:逐月前 24 大市值、含死币、单币 ≤ 40%、每日再平衡,2019-01 起;
    Jazz 10-31 定为历史锚,取代 `core_alpha_daily` 的幸存者回填);
    10-02 → 10-12:`core_cap_daily.cap_a1` 的前向收益;10-12 之后:`cap_a1_u`(不设单币上限,S-556)。按收益拼接成一条 NAV。
    读不到 ⇒ None,成绩单会说「基准没有覆盖」,不悄悄退回等权或旧回放。
    """
    from src.data.signals.core_cap import CORE_ARM, CORE_SINCE, INCEPTION, LEGACY_CORE_ARM, TABLE
    from src.data.style.header import _read_all
    rows = await _read_all(HISTORY_TABLE, {"select": "d,ret", "arm": f"eq.{HISTORY_ARM}", "d": f"gte.{start}", "order": "d.asc"})
    if not isinstance(rows, list) or not rows:
        return None
    rep_ = pd.Series({pd.Timestamp(r["d"]): float(r["ret"]) for r in rows if r.get("ret") is not None}).sort_index()
    rep_ = rep_[rep_.index <= INCEPTION]

    async def _arm(arm: str) -> pd.Series:
        fwd = await _read_all(TABLE, {"select": "d,nav", "arm": f"eq.{arm}", "order": "d.asc"})
        return pd.Series([float(r["nav"]) for r in fwd],
                         index=pd.DatetimeIndex([pd.Timestamp(r["d"]) for r in fwd]), dtype=float).sort_index()

    # S-556:① 的前向 = 旧臂 (INCEPTION, CORE_SINCE] + 新臂(不设单币上限)> CORE_SINCE
    old, new = await _arm(LEGACY_CORE_ARM), await _arm(CORE_ARM)
    seg_old = old.pct_change().dropna()[lambda x: (x.index > INCEPTION) & (x.index <= CORE_SINCE)]
    seg_new = new.pct_change().dropna()[lambda x: x.index > CORE_SINCE]
    rets = pd.concat([rep_, seg_old, seg_new]).sort_index()
    rets = rets[~rets.index.duplicated(keep="first")]
    return (1 + rets).cumprod()
