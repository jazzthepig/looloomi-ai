"""`market_state_vectors` 的全量重算写者 —— 单源、定盘、一次标准化 (S-245).

## 为什么这张表此前没有写者,而它有 582 行

实测 2026-08-27:仓库里**没有任何代码写 `market_state_vectors`**。
`scripts/build_l1_observations.py` 写的是本地 sqlite,而且要读 `Shadow/` ——
规则 #2 说 Shadow 不是权威,而且它在 Railway 上根本不存在。那 582 行来自仓库
之外的 Mac 侧工具。**几何基底是这套系统里唯一一张没有可复现写者的表。**

## 而那 582 行是拼出来的 —— 三个指纹,全部实测

**① 97.6% 的天数混了价源。** `price_sources` 列自己记着:

    binance_hist+coingecko+eodhd+yfinance   229 天
    binance_hist+coingecko                  330 天
    单一源                                    23 天   ← 582 天里只有 23 天

`yfinance` 出现在 229 天里(`single_source.py` 记它「63 天不更新,已死」),
`coingecko` 出现在 568 天里(S-195:market_chart 采样点塌缩成日期,不是收盘)。

**② 这些源彼此不一致,而且差得很大。** 2025-01 之后 `ohlcv_daily` 里
**17,876 个 symbol-day 有 ≥2 个源**,涉及 59 个标的:

    平均价差   190.6 bps
    最大价差 5,505.8 bps
    差 >100bps 的       7,848 天

**③ 缺陷的入口是一行没有 source 过滤的查询。**
`scripts/build_l1_observations.py::fetch_panel()` 从 `ohlcv_daily` 里
`select symbol,trade_date,close,volume`,**没有 `source` 条件**,然后

    out[row["symbol"]][row["trade_date"][:10]] = (float(cl), ...)

按 `trade_date.asc` 分页写进 dict —— **同一天同一标的,后到的源静默覆盖先到的。**
哪个源"赢"取决于分页顺序,而两个源对同一天的读数平均差 190bps。
于是 `vol_mkt` / `vol_of_vol` / `downside_ratio` 量到的是**换源时的跳变**,
不是市场的二阶矩。S-106 的原话:**两种 bar 约定之间的拼接会被读成市场结构。**

`spread_kinds` 列里甚至已经写着 `definition_mismatch: 24` —— **写者当时就知道
24 个标的的源定义不一致,然后照写。** 记录了,没有拒绝。这和今天的 S-244
是同一个形状:**记下来 ≠ 被执行。**

## ④ 面板成员在动,而横截面维不知道

`live = [s for s in panel if d in closes[s]]` —— 每天现算"谁有价"。
实测 `n_symbols` 在 **25 → 75** 之间摆动。`breadth_200ma` / `corr_mean` /
`disp_return` 是横截面统计量,**在不同成员集上算出来的值不可跨日比较**:
「广度下降」和「面板少了 30 个标的」被压成同一个数。

所以这个写者**定盘**:先选出在整段窗口里覆盖率达标的标的,固定成员,
再逐日计算。`n_symbols` 因此是常数,而它变成常数这件事本身就是可验的。

## 设计:四条,每条对应一个已实测的缺陷

1. **单源。** 服务端 `source=eq.binance_hist`,拿回来再 `assert_single_source()`
   断言一次(S-230)。`binance_hist` 是唯一同时满足「可信」「深」的源:
   2017-08-17 → 2026-08-20,262 个标的,386,201 行。
2. **定盘。** `PanelSpec` 记下入选标的、被剔除的标的**和原因**,随结果一起走。
3. **一次标准化。** z-score 跨全史,一个 `zscore_pass` 戳(S-232)。增量写在
   数学上不可能 —— 新的一天会改变每一个历史 z 值。
4. **写前设地板。** 标的不足 / 天数不足 → **返回 degraded,不写**(S-220)。
   拒绝要比结果更有信息,所以 `RecomputeResult` 带着原因走。

## 未接线的三维,不算缺失 (S-231)

`fng` / `oi_mcap` / `stable_supply_chg` **在 Supabase 里没有任何表**
(2026-08-27 实测全库 81 张表)。它们不是"今天没测到",是"没有源"。
把它们算进 `source_completeness` 的分母,这个指标的上限就永远是 19/22,
而**一个永远达不到的上限会让所有人学会忽略这个数**。
所以 `market_state.UNWIRED_DIMS` 把它们从分母里摘出来,并且这个名单
只能减 —— 接线之后必须删掉那一行。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

from src.data.market.single_source import (
    CrossSourceError, SeriesSource, assert_single_source)
from src.data.vector.market_state import (
    DIMS, StateVector, build_rows_for_upsert, breadth_above_ma, downside_ratio,
    herfindahl, mean, mean_pairwise_corr, pct_change, realized_vol, skew,
    stdev, trend_phase, zscore_columns)

log = logging.getLogger("market_state_writer")

#: 唯一可用于面板的价源。深度 2017-08-17→2026-08-20,262 标的,386k 行。
#:
#: ⚠️ 这里【不能】做回退。「哪个源有这天的价就用哪个」正是造出那 582 行的逻辑,
#: 而它必然在窗口中间跨源。宁可少几天,不可跨源 (S-230)。
PANEL_SOURCE = "binance_hist"

#: 200 日均线需要 200 天热身,再留 40 天给趋势年龄的连续计数。
WARMUP_DAYS = 240

#: 入选标的必须在窗口里覆盖到这个比例的交易日。低于它的标的会把横截面统计
#: 拖成"谁今天有数据"的函数,而那正是 n_symbols 25→75 摆动的来源。
MIN_COVERAGE = 0.90

#: 写前地板。低于任一条 → degraded,不写。
MIN_SYMBOLS = 20
MIN_DAYS = 400

#: 默认起点 = 2022-01-01。**这不是拍脑袋,是地板逼出来的。**
#:
#: 我最初写的默认值是 `2018-06-01`(模块 docstring 说"三个周期才够")。
#: 用 `MIN_SYMBOLS` 一挡,实测立刻给出了深度与宽度的取舍表
#: (单源 binance_hist,覆盖率门槛 90%,2026-08-27):
#:
#:     起点        天数     达标标的
#:     2018-06     3,003        8    ← 低于地板,写者会【拒绝】
#:     2022-01     1,693      127
#:     2024-01       963      194
#:
#: **回到 2018 就只剩 8 个标的**,而 8 个标的上的 breadth / corr / dispersion
#: 不是环境读数。所以取 2022-01:1,693 天(2022 熊 / 2023-24 修复 /
#: 2025-26 回撤,三个环境),127 个标的 —— 相对现表的 582 天 / 25-75 摆动,
#: 深度 ×2.9,宽度定盘在 ×1.7。
#:
#: 这条注释本身是地板的产出物:没有它,我会静默地选 2018 并得到一张 8 个
#: 标的的表,而它长得和一张好表一模一样。
DEFAULT_START = "2022-01-01"

#: 一次拉取的分页大小(PostgREST 上限保守取值)。
PAGE = 10_000


@dataclass(frozen=True)
class PanelSpec:
    """定盘的结果:入选是谁、剔除了谁、为什么 —— 随结果一起走,不留在作者脑子里。"""

    source: str
    symbols: tuple[str, ...]
    first_day: str
    last_day: str
    n_days: int
    excluded: dict[str, str] = field(default_factory=dict)

    @property
    def n_symbols(self) -> int:
        return len(self.symbols)

    def as_payload(self) -> dict[str, Any]:
        # 剔除原因按类别聚合 —— 一份 200 行的名单没人读,而"3 个标的因为
        # 覆盖率不足被剔除"是一句能用的话。
        by_reason: dict[str, int] = {}
        for why in self.excluded.values():
            by_reason[why.split(":")[0]] = by_reason.get(why.split(":")[0], 0) + 1
        return {
            "price_source": self.source,
            "n_symbols": self.n_symbols,
            "coverage": f"{self.first_day}..{self.last_day}",
            "n_days": self.n_days,
            "excluded": by_reason,
        }


@dataclass(frozen=True)
class RecomputeResult:
    """一次重算的结果 = 值 + 它的可信域。

    `ok=False` 的两种情形必须分开:**拒绝**(地板没过,没写,系统是健康的)
    与**失败**(写出错了)。S-220 记的就是把这两者压成一个 `status` 的代价。
    """

    ok: bool
    refused: bool
    rows: int
    zscore_pass: Optional[str]
    panel: Optional[PanelSpec]
    reason: str = ""

    def as_payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            # 拒绝不叫 ok,也不叫 error —— 它叫 degraded,并且带着原因。
            "status": "ok" if self.ok else ("degraded" if self.refused else "error"),
            "rows_written": self.rows,
            "zscore_pass": self.zscore_pass,
        }
        if self.panel:
            out["panel"] = self.panel.as_payload()
        if not self.ok:
            out["reason"] = self.reason or "unknown"
        return out


# ── 取数 ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SbRead:
    """一次读的结果 + **它为什么没成**。

    ⚠️ 第一版 `_sb_get` 返回 `Optional[list]`,于是四个不同的原因塌成同一个 None:

        凭证没设 · 断路器打开 · HTTP 4xx(RLS/角色/查询写错) · 传输失败

    实测 2026-08-27,Jazz 在 Mac 上跑 dry-run 拿到的是
    「Supabase 读不到,offset=0,已取 0 行」—— 这句话**对排查毫无帮助**,
    因为四个原因里每一个都长这样。而最可能的那个(裸 `python3 -c` 没有导出
    `.env`,`os.getenv` 读到空)本来一句话就能说清。

    这是今天第十次「两个状态压进一个表示」,而且是我一小时前刚写的代码。
    一个说得出"我为什么读不到"的读,比一个 None 有用得多。
    """

    rows: Optional[list[dict]]
    reason: str = "ok"

    @property
    def ok(self) -> bool:
        return self.rows is not None


def env_presence() -> dict[str, bool]:
    """哪些凭证变量【存在】—— 只报存在性,永远不报值。"""
    return {k: bool(os.getenv(k)) for k in
            ("SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_SERVICE_KEY")}


async def _sb_get(path: str, params: dict[str, str]) -> SbRead:
    """一次 PostgREST 读。**读不到 ≠ 读到空** (S-180),而且要说出是哪一种。"""
    from src.api.store import _supabase_request_with_retry, supabase_breaker_state

    base = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_KEY") or ""
    if not base or not key:
        missing = [k for k, v in env_presence().items() if not v]
        return SbRead(None, (
            f"凭证不在进程环境里(缺 {', '.join(missing)})。"
            f"注意:这个仓库【没有任何代码加载 .env】—— Railway 上是真的环境变量,"
            f"而裸跑 `python3 -c` 时 os.getenv 读到空。"
            f"跑之前先 `set -a; source .env; set +a`。"))

    brk = supabase_breaker_state()
    if brk.get("open"):
        return SbRead(None, f"Supabase 断路器打开({brk}) —— 后端在降级,不是查询写错了")

    resp = await _supabase_request_with_retry(
        "GET", f"{base}/rest/v1/{path}",
        params=params,
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
    )
    if resp is None:
        # store 层对超时/重试耗尽返回 None,并且已经记了日志。
        return SbRead(None, "传输失败或重试耗尽(超时/网络)—— 不是 0 行,也不是权限")
    if resp.status_code >= 300:
        # 4xx 是后端在说"你的请求不对":RLS 拒绝、表不存在、查询语法错。
        # 把 body 的前 200 字带上 —— PostgREST 的错误信息本身就是诊断。
        return SbRead(None, f"HTTP {resp.status_code}: {resp.text[:200]}")
    return SbRead(resp.json())


async def fetch_panel(start: str, *, source: str = PANEL_SOURCE
                      ) -> tuple[dict[str, dict[str, tuple[float, float]]], SeriesSource]:
    """`{symbol: {day: (close, volume)}}`,**单源**,含热身期。

    热身期在 `start` 之前拉取:一个从 start 当天开始算的 200 日均线不是
    200 日均线,是一个更短的均值穿着同一个名字 —— 它会静默地污染每次构建
    最初 200 行的 trend_phase。

    过滤在服务端做(`source=eq.…`),拿回来再断言一次。两道都要:
    服务端过滤省流量,客户端断言防的是**过滤条件哪天被人改掉而没人发现**。
    """
    warm = (date.fromisoformat(start) - timedelta(days=WARMUP_DAYS)).isoformat()
    panel: dict[str, dict[str, tuple[float, float]]] = {}
    seen: list[dict[str, Any]] = []
    offset = 0

    while True:
        read = await _sb_get("ohlcv_daily", {
            "select": "symbol,trade_date,close,volume,source",
            "source": f"eq.{source}",
            "trade_date": f"gte.{warm}",
            "order": "trade_date.asc",
            "limit": str(PAGE), "offset": str(offset),
        })
        if not read.ok:
            # 原因原样往上传。把它压回一句"读不到"就等于没查过 —— 这一句
            # 正是 2026-08-27 dry-run 给出的、对排查毫无帮助的那一句。
            raise CrossSourceError(
                f"panel fetch 在 offset={offset} 读不到(已取 {len(panel)} 个标的)。"
                f"**读不到 ≠ 0 行** (S-180)。原因:{read.reason}")
        batch = read.rows or []
        for row in batch:
            cl = row.get("close")
            if cl is None:
                continue
            d = str(row.get("trade_date") or "")[:10]
            if not d:
                continue
            panel.setdefault(row["symbol"], {})[d] = (float(cl), float(row.get("volume") or 0))
        # 只留断言需要的字段,不把 386k 行整份留在内存里。
        seen.extend({"source": r.get("source"), "trade_date": r.get("trade_date"),
                     "symbol": r.get("symbol")} for r in batch[:200])
        if len(batch) < PAGE:
            break
        offset += PAGE

    # 客户端断言:若过滤条件被改坏,这里抛异常,而不是静默地拼出一条曲线。
    src = assert_single_source(seen, job="market_state panel", source_key="source")
    return panel, src


def pin_panel(panel: dict[str, dict[str, tuple[float, float]]], start: str,
              *, source: str, min_coverage: float = MIN_COVERAGE) -> PanelSpec:
    """定盘:选出覆盖率达标的标的,并记下每一个被剔除的原因。

    横截面统计量(breadth / corr / dispersion)只有在**同一组成员**上才可跨日
    比较。旧写者每天现算成员,于是 `n_symbols` 在 25→75 之间摆动,而
    「广度下降」与「面板少了 30 个标的」被压成同一个数。
    """
    days = sorted({d for ser in panel.values() for d in ser if d >= start})
    if not days:
        return PanelSpec(source, (), "?", "?", 0, {"__all__": "no_days: 窗口内没有任何交易日"})

    need = len(days) * min_coverage
    keep: list[str] = []
    excluded: dict[str, str] = {}
    for sym, ser in panel.items():
        n = sum(1 for d in days if d in ser)
        if n >= need:
            keep.append(sym)
        else:
            excluded[sym] = (f"coverage: {n}/{len(days)} 天 "
                             f"({n / len(days):.1%} < {min_coverage:.0%})")
    return PanelSpec(source, tuple(sorted(keep)), days[0], days[-1], len(days), excluded)


# ── 计算 ──────────────────────────────────────────────────────────────────────

def _returns(closes: dict[str, float], upto: str, n: int) -> list[float]:
    ds = [d for d in sorted(closes) if d <= upto][-(n + 1):]
    c = [closes[d] for d in ds]
    return [c[i] / c[i - 1] - 1 for i in range(1, len(c)) if c[i - 1]]


def compute_vectors(panel: dict[str, dict[str, tuple[float, float]]],
                    spec: PanelSpec, *, vol_window: int = 30,
                    ma_window: int = 200) -> list[StateVector]:
    """逐日算面板维与价格维。**价格只进二阶矩与相位,永不进方向。**

    这条不是风格偏好:`market_state.py` 的模块 docstring 记着 Shadow 的
    vector_mine Round 6 用 5 个价格衍生维聚出 8 个簇,而它自己的笔记写着
    「8 个簇都是 HIGH_VOL + RISK_ON + HIGH_DISP」—— 一个环境的八个切片,
    因为输入是同一条价格序列的八种看法。
    """
    closes = {s: {d: v[0] for d, v in panel[s].items()} for s in spec.symbols if s in panel}
    vols = {s: {d: v[1] for d, v in panel[s].items()} for s in spec.symbols if s in panel}
    days = [d for d in sorted({d for ser in closes.values() for d in ser})
            if spec.first_day <= d <= spec.last_day]

    btc = "BTC" if "BTC" in closes else None
    out: list[StateVector] = []
    vol_hist: list[float] = []

    for d in days:
        live = [s for s in spec.symbols if s in closes and d in closes[s]]
        if len(live) < MIN_SYMBOLS:
            # 成员不足的一天不产出向量。写一个"测到了但很稀"的向量,
            # 和写一个正确的向量,在下游长得一模一样。
            continue

        rets = {s: _returns(closes[s], d, vol_window) for s in live}
        day_ret = [r[-1] for r in rets.values() if r]

        v: dict[str, Optional[float]] = {}

        # 风险偏好 —— 横截面结构
        if btc and btc in rets and rets[btc]:
            alts = [r[-1] for s, r in rets.items() if s != btc and r]
            am = mean(alts)
            v["alt_btc_spread"] = None if am is None else am - rets[btc][-1]
        v["breadth_200ma"] = breadth_above_ma(
            {s: [closes[s][x] for x in sorted(closes[s]) if x <= d] for s in live}, ma_window)
        v["disp_return"] = stdev(day_ret)
        v["corr_mean"] = mean_pairwise_corr({s: rets[s] for s in live if rets[s]})

        # 流动性
        vol_today = [vols[s].get(d) for s in live]
        vt = [x for x in vol_today if x]
        if vt:
            hist = []
            for s in live:
                ds = [x for x in sorted(vols[s]) if x <= d][-vol_window:]
                hist.append(sum(vols[s][x] for x in ds) / len(ds) if ds else 0.0)
            tot_now, tot_hist = sum(vt), sum(hist)
            v["volume_trend"] = (tot_now / tot_hist - 1.0) if tot_hist else None
            v["adv_concentration"] = herfindahl(vt)

        # 波动结构 (价格 1/2)
        mkt = [mean([rets[s][i] for s in live if len(rets[s]) > i]) for i in range(vol_window)] \
            if live else []
        rv = realized_vol([x for x in mkt if x is not None])
        v["vol_mkt"] = rv
        if rv is not None:
            vol_hist.append(rv)
            v["vol_of_vol"] = stdev(vol_hist[-vol_window:])
        v["downside_ratio"] = downside_ratio([x for x in mkt if x is not None])

        # 趋势相位 (价格 2/2) —— 位置,不是方向预测
        if btc and btc in closes:
            hist_c = [closes[btc][x] for x in sorted(closes[btc]) if x <= d]
            strength, age = trend_phase(hist_c, ma_window)
            v["trend_strength"], v["trend_age_days"] = strength, age

        out.append(StateVector(d=d, values=v))

    return out


async def attach_cis_and_funding(vectors: list[StateVector]) -> dict[str, Any]:
    """把 CIS 横截面与资金费维贴到已有向量上。返回每一维实际填上的天数。

    分开做,是因为它们的覆盖窗口和面板**不重合**:CIS 从 2025-05-03 起,
    funding 从 2024-02-19 起且只有 10 个标的,而面板回到 2017。
    早年那些天这几维是**真的缺**,不是坏 —— 所以填 None,不填 0。
    一个 0 是一次测量声明,而且是假的。
    """
    by_day = {sv.d: sv for sv in vectors}
    lo, hi = (min(by_day), max(by_day)) if by_day else ("9999-12-31", "0000-01-01")
    filled: dict[str, int] = {}

    read = await _sb_get("cis_scores", {
        "select": "symbol,score,grade,recorded_at",
        "recorded_at": f"gte.{lo}", "order": "recorded_at.asc", "limit": str(PAGE * 5),
    })
    # 读不到 CIS 维不是致命的(早年本来就没有),但【读不到】和【那几天真的没有】
    # 必须分开报,否则一次凭证问题会长得像一段真实的历史空白。
    if not read.ok:
        filled["cis_error"] = read.reason
    rows = read.rows if read.ok else None
    if rows:
        daily: dict[str, list[dict]] = {}
        for r in rows:
            d = str(r.get("recorded_at") or "")[:10]
            if lo <= d <= hi:
                daily.setdefault(d, []).append(r)
        prev_mean: Optional[float] = None
        for d in sorted(daily):
            sv = by_day.get(d)
            if sv is None:
                continue
            scores = [r.get("score") for r in daily[d]]
            m = mean(scores)
            sv.values["cis_mean"] = m
            sv.values["cis_disp"] = stdev(scores)
            sv.values["cis_skew"] = skew(scores)
            grades = [str(r.get("grade") or "") for r in daily[d]]
            sv.values["pct_grade_A"] = (
                sum(1 for g in grades if g.startswith("A")) / len(grades) if grades else None)
            sv.values["d_cis_mean"] = (
                None if (m is None or prev_mean is None) else m - prev_mean)
            prev_mean = m if m is not None else prev_mean
        filled["cis"] = sum(1 for sv in vectors if sv.values.get("cis_mean") is not None)

    read = await _sb_get("funding_history", {
        "select": "symbol,funding_rate,funding_time",
        "funding_time": f"gte.{lo}", "order": "funding_time.asc", "limit": str(PAGE * 5),
    })
    if not read.ok:
        filled["funding_error"] = read.reason
    rows = read.rows if read.ok else None
    if rows:
        daily_f: dict[str, list[float]] = {}
        for r in rows:
            d = str(r.get("funding_time") or "")[:10]
            fr = r.get("funding_rate")
            if lo <= d <= hi and fr is not None:
                daily_f.setdefault(d, []).append(float(fr))
        for d, xs in daily_f.items():
            sv = by_day.get(d)
            if sv is None:
                continue
            sv.values["funding_mean"] = mean(xs)
            sv.values["funding_disp"] = stdev(xs)
        filled["funding"] = sum(1 for sv in vectors if sv.values.get("funding_mean") is not None)

    return filled


async def attach_regime(vectors: list[StateVector]) -> int:
    """贴 `regime_label`。没有读数的日子留 None —— 那是 2025-05 之前的真实情况。"""
    by_day = {sv.d: sv for sv in vectors}
    read = await _sb_get("daily_macro_regime", {
        "select": "d,regime", "order": "d.asc", "limit": str(PAGE)})
    if not read.ok:
        log.warning("[MSV] regime 读不到 —— %s", read.reason)
        return 0
    rows = read.rows or []
    if not rows:
        return 0
    n = 0
    for r in rows:
        sv = by_day.get(str(r.get("d") or "")[:10])
        if sv is not None and r.get("regime"):
            sv.regime_label = str(r["regime"]).strip().upper().replace("-", "_").replace(" ", "_")
            n += 1
    return n


# ── 编排 ──────────────────────────────────────────────────────────────────────

async def recompute_all(start: str = DEFAULT_START, *, dry_run: bool = False
                        ) -> RecomputeResult:
    """全量重算并 upsert。**增量在数学上不可行** (S-232)。

    z-score 跨整段历史 —— 多一天就改变每一个历史 z 值,所以"只算今天再插一行"
    会把新行放进一个和旧行不同的坐标系,而 RPC 的余弦不会说,它照样返回一个数。
    因此:整段重算,一个 `zscore_pass` 戳,旧 pass 的行由 upsert 覆盖。
    """
    from datetime import datetime, timezone

    try:
        panel, src = await fetch_panel(start)
    except CrossSourceError as e:
        return RecomputeResult(False, False, 0, None, None, str(e))

    spec = pin_panel(panel, start, source=src.source)

    # ── 地板在写之前 (S-220) ────────────────────────────────────────────────
    if spec.n_symbols < MIN_SYMBOLS:
        return RecomputeResult(
            False, True, 0, None, spec,
            f"定盘后只剩 {spec.n_symbols} 个标的 < {MIN_SYMBOLS} —— 横截面维在这么小的"
            f"面板上不是环境读数。不写。")
    if spec.n_days < MIN_DAYS:
        return RecomputeResult(
            False, True, 0, None, spec,
            f"窗口只有 {spec.n_days} 天 < {MIN_DAYS} —— z-score 的分母不够,"
            f"标准化后的坐标系不稳。不写。")

    vectors = compute_vectors(panel, spec)
    if not vectors:
        return RecomputeResult(False, True, 0, None, spec,
                               "逐日计算后 0 个向量 —— 每一天的存活标的都不足 "
                               f"{MIN_SYMBOLS}")

    await attach_cis_and_funding(vectors)
    await attach_regime(vectors)

    zscore_columns(vectors)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    zpass = f"{src.source}:{spec.n_symbols}sym:{stamp}"
    rows = build_rows_for_upsert(vectors, zscore_pass=zpass)

    # 溯源随行同走:哪个源、哪些标的、覆盖到哪 —— 而不是留在一次运行的日志里。
    for r in rows:
        r["n_symbols"] = spec.n_symbols
        r["price_sources"] = [src.source]
        r["provenance_note"] = (
            f"single-source recompute (S-245): {src.source} only; panel pinned to "
            f"{spec.n_symbols} symbols with >={MIN_COVERAGE:.0%} coverage over "
            f"{spec.first_day}..{spec.last_day}; {len(spec.excluded)} excluded. "
            f"z-scored in one pass across the full history.")

    if dry_run:
        return RecomputeResult(True, False, len(rows), zpass, spec, "dry_run — 未写入")

    from src.api.store import supabase_upsert_table
    ok = await supabase_upsert_table("market_state_vectors", rows, on_conflict="d")
    if not ok:
        # upsert 返回 False 分不出角色门/凭证/传输,所以这里也不编一个原因。
        return RecomputeResult(False, False, 0, zpass, spec,
                               "upsert 返回 False(角色门、凭证或传输)")
    log.info("[MSV] %d rows, pass=%s, %d symbols", len(rows), zpass, spec.n_symbols)
    return RecomputeResult(True, False, len(rows), zpass, spec)


assert len(DIMS) == 24, "写者与 market_state.DIMS 的契约是 24 维"
