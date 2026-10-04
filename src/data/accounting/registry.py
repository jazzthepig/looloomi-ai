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
    benchmark: str = "panel_ew"   # 'arm:<名字>' | 'panel_ew'(① 的 24 名面板等权持有,binance_hist)
    status: str = "paper"      # paper | dormant | retired_by_design
    filters: dict = field(default_factory=dict)
    caveat: str = ""


BOOKS: tuple[Book, ...] = (
    # S-473(Jazz 10-03「use 1」):① = 市值加权、单币 ≤ 40%。基准臂 ew_a0 = 同一内核下的等权,记着 α 这个决定本身的前向证据。
    Book("core_cap", "①", "核心持仓(24 名市值加权,单币 ≤ 40%)", "持有市场吃 beta;FoF 的本体(S-472/S-473)",
         "core_cap_daily", "arms", arm="cap_a1", accounting="shared_kernel", benchmark="arm:ew_a0"),
    # 原 ①。S-473 起改作 ② 候选:等权 = 对二线 / 山寨的风格倾斜,外加波动率目标(③ 的成分)—— 要自己挣到权重。
    Book("beta_core", "②", "等权 + 波动率目标(原 ①,S-473 起为 ② 候选)", "面板内等权 = 风格倾斜;另含 ③ 的波动率目标",
         "beta_core_nav", "plain", filters={"void_reason": "is.null"}, benchmark="own_benchmark_nav"),
    Book("beta_plus_w", "②", "动量 + 52 周高点倾斜(周频 7 份)", "面板内超配趋势强、接近新高的币(S-428)",
         "beta_plus_daily", "arms", arm="momentum_52w_w", accounting="shared_kernel", benchmark="arm:panel_hold_w"),
    Book("beta_plus_m", "②", "动量 + 52 周高点倾斜(月频)", "同上,月频",
         "beta_plus_daily", "arms", arm="momentum_52w_m", accounting="shared_kernel", benchmark="arm:panel_hold_m"),
    Book("tokenization_tilt", "②", "代币化基础设施 25% 倾斜", "TradFi 上链的通路与发行是长期主题(DECISIONS 09-26)",
         "tokenization_tilt_daily", "arms", arm="tokenization_tilt_25", accounting="shared_kernel",
         benchmark="arm:panel_hold"),
    Book("hl_mech", "①+③", "HL 4 币机械仓位(MECH_tom)", "4 币现货 + 按规则缩放仓位(M-189/M-190)",
         "hl_book_daily", "hl", arm="MECH_tom", benchmark="arm:H0_hold"),
    Book("hl_jev", "①+③", "HL 4 币 Jev 仓位(JEV_tom)", "同上,Jev 参与调整",
         "hl_book_daily", "hl", arm="JEV_tom", benchmark="arm:H0_hold"),
    Book("causal_paper", "④", "因果多空(资金费率)", "资金费率与持仓结构的多空",
         "causal_paper_nav", "plain"),
    Book("scalable_book", "④", "可扩展多空组合", "多策略多空",
         "scalable_book_nav", "plain"),
    Book("combined_book", "④", "多空合成", "多空合成",
         "combined_book_nav", "plain"),
    Book("dingge_paper", "事件", "Dingge 事件", "事件驱动",
         "dingge_paper_nav", "plain"),
    Book("fusion_paper", "④", "Fusion 多空", "多 sleeve 融合",
         "fusion_paper_nav", "plain", filters={"void_reason": "is.null"},
         caveat="T-026:记录只扣成本、不记价格 —— 数字不可信"),
    Book("two_layer_paper", "—", "两层(已按设计退役)", "R57:V5c 核心退役,持仓为 0",
         "two_layer_paper_nav", "plain", status="retired_by_design"),
)


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
    core_bench = None
    if core:
        last_inc = core[-1]["inception_id"]
        df = pd.DataFrame([r for r in core if r["inception_id"] == last_inc])
        df.index = pd.to_datetime(df["mark_date"])
        navs["beta_core"] = df["nav"].astype(float)
        core_bench = df["benchmark_nav"].astype(float)
    panel_ew = await _panel_ew_benchmark()
    cache: dict[str, list] = {}
    for b in BOOKS:
        if b.id == "beta_core":
            bench[b.id] = core_bench
            continue
        if b.table not in cache:
            if b.shape == "plain":
                sel = "mark_date,nav" + (",inception_id" if b.table == "fusion_paper_nav" else "")
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
            s = pd.Series([float(r["nav"]) for r in rows], index=pd.to_datetime([r["mark_date"] for r in rows]))
            navs[b.id] = s[~s.index.duplicated(keep="last")]
            bench[b.id] = panel_ew
        elif b.shape == "arms":
            df = pd.DataFrame(rows)
            df["d"] = pd.to_datetime(df["d"])
            pv = df.pivot_table(index="d", columns="arm", values="nav")
            navs[b.id] = pv.get(b.arm)
            bench[b.id] = pv.get(b.benchmark.split(":", 1)[1]) if b.benchmark.startswith("arm:") else panel_ew
        else:
            idx = pd.to_datetime([r["d"] for r in rows])
            navs[b.id] = pd.Series([float((r["nav"] or {}).get(b.arm, np.nan)) for r in rows], index=idx)
            bench[b.id] = pd.Series([float((r["nav"] or {}).get(b.benchmark.split(":", 1)[1], np.nan))
                                     for r in rows], index=idx)
    return navs, bench


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
