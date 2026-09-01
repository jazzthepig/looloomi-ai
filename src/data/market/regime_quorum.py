"""Regime label quorum — 一个标签的可信度不只看它多新,还看它几票通过 (S-263).

## 起因:M-120 的根因诊断错了,而它错得很有信息量

2026-08-31,Minimax 报告 `narrative_daily.macro_regime` 停滞 42 天,根因写作
"Railway `_daily_snapshot_loop()` (src/api/main.py:1227) 把 narrative_daily 写到
Supabase,producer 自 7-20 停写"。

实测:**那个循环活着**,它写的四张表全部 0–1 天新鲜
(cis_scores 0d / macro_briefs 1d / conviction_verdicts_daily 1d / narrative_snapshots 1d)。

误诊的来源是一个名字:`persist_narrative_daily()` **写的是 `narrative_snapshots`**。
grep `narrative_daily` 命中 main.py:1271,离 1227 只有 44 行,于是那个循环被认成
producer。**一个名字指一张表、函数体写另一张表** —— 又是「两个东西,一个表示」。

## 真正的问题:多数票的选民从 3 个掉到 1 个,而票面结果没变

`daily_macro_regime` 是 VIEW,不是表:每天对 `cis_scores.macro_regime` 取众数,
同时算出 `n_obs` 与 `n_sources`。**两个消费者都只取 `d, regime`,把票数扔了**
(`beta_core_paper._regime_history`、`market_state_writer`)。

实测 2026-09-01 的 Supabase:

    08-18  TIGHTENING n=1446 srcs=3  ·  NEUTRAL n=174     ← 有分歧,在重算
    08-19  TIGHTENING n=1564 srcs=3  ·  NEUTRAL n=232     ← 有分歧
    08-20  TIGHTENING n=1543 srcs=3   全票
    08-22  TIGHTENING n=1032 srcs=1   全票                 ← 选民掉到 1
    09-01  TIGHTENING n=  86 srcs=1   全票                 ← 票数也塌了 (1500→86)

**标签从 07-27 起 36 天没翻过,而「一致」恰好是在选民消失的那几天开始的。**
一致性由减员产生,不是由共识产生 —— 而下游完全看不出区别,因为下游只拿到
`regime="TIGHTENING"` 这一个字符串。

这是 S-251 的同一个形状:那次是 `binance_hist` 的标的数从 261 掉到 1 而探针报
"fresh",这次是 regime 的信源数从 3 掉到 1 而 `_regime_history` 的新鲜度检查全绿。
**新鲜度证明的是「这行是今天写的」,不是「这行今天被想过」。**

## 为什么基线必须排除最近的窗口

慢速塌陷会把自己的基线一起拖下去:如果基线取「过去 30 天的中位数」,而塌陷已经
持续了 20 天,中位数本身就已经是塌陷后的值,判据永远不触发。所以基线取
`[BASELINE_LO, BASELINE_HI]` 这一段**更早的**历史(与 `source_freshness.py`
的 45/15 天同一手法),让「现在」和「塌陷之前」比,而不是和「正在塌陷的自己」比。

## 五值裁决,不是「够不够新鲜」

    ok           票数与信源数都在基线附近
    thin         信源数低于基线但 >1,或票数显著缩水 —— 可用,须标注
    COLLAPSED    信源数 <=1 而基线 >=2,或票数 < 基线的 COLLAPSE_RATIO
    frozen       信源仍在,但标签停留时间已超过历史翻转间隔的 FROZEN_MULT 倍
    no_baseline  历史不足以给出基线 —— **不等于健康**(S-246)

`no_baseline` 与 `ok` 分开,是因为「我量过,没问题」和「我没量」在下游一旦合并,
后者就会穿着前者的衣服通过每一道门。
"""
from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

#: 基线取这一段历史(天),两端都排除最近的窗口,免得塌陷拉低自己的基线。
BASELINE_LO_DAYS, BASELINE_HI_DAYS = 60, 21
#: 判为塌陷的比例门槛(相对基线中位数)。
COLLAPSE_RATIO = 0.50
#: 判为变薄的比例门槛。
THIN_RATIO = 0.80
#: 标签停留超过「历史最长连续段 × 这个倍数」即判 frozen。
#:
#: ⚠️ 第一版拿的是**翻转间隔的中位数**,在真实数据上直接错了。实测 2026-06-19→09-01:
#: 六月底到七月底是一段高频震荡(翻转间隔 1/2/3 天),中位数被压到 2.5 天,
#: 于是 `36 > 2.5×3` 触发 frozen —— 而同一段历史里明摆着有一个 **25 天的
#: TIGHTENING 连续段**。一个 36 天的段和一个 25 天的先例是同一个量级,不是异常。
#:
#: 「平均多久翻一次」回答不了「这段持续得反常吗」——  前者被震荡期支配,
#: 后者要问的是**这个面板见过多长的段**。改成对历史最长段取倍数:
#: 今天 36 天 vs 25×1.5=37.5 不触发(正确),再过两天触发(也正确 —— 一个
#: 明显长于任何先例的段值得看一眼)。
FROZEN_MULT = 1.5
#: 计算基线所需的最少天数。低于它给 no_baseline,不给 ok。
MIN_BASELINE_DAYS = 10

OK, THIN, COLLAPSED, FROZEN, NO_BASELINE, NO_DATA = (
    "ok", "thin", "COLLAPSED", "frozen", "no_baseline", "no_data")


@dataclass(frozen=True)
class RegimeQuorum:
    """一天的 regime 标签 + 它是几票通过的 + 裁决。

    `regime` 与 `verdict` 是**两个字段**,故意不合并:一个 COLLAPSED 的
    TIGHTENING 仍然是 TIGHTENING,调用方有权知道标签是什么、同时知道它不可信。
    把不可信的标签换成 None 会让「没有标签」和「标签不可信」再一次共用一个表示。
    """
    d: str
    regime: Optional[str]
    n_obs: int
    n_sources: int
    verdict: str
    reason: str
    baseline_sources: Optional[float] = None
    baseline_obs: Optional[float] = None
    days_since_flip: Optional[int] = None
    #: 今天那一行(还在填)的数字,仅供展示,不参与裁决。
    partial_today: Optional[tuple] = None

    @property
    def usable(self) -> bool:
        """可以拿来定仓位吗。**`no_baseline` 不算可用** —— 没量过不是健康。"""
        return self.verdict in (OK, THIN)


def _as_date(s: str) -> Optional[dt.date]:
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except Exception:                                          # noqa: BLE001
        return None


def days_since_flip(series: Sequence[tuple[str, str]]) -> Optional[int]:
    """最后一次标签变化距今多少天。series 为 (d, regime),按日期升序。"""
    if len(series) < 2:
        return None
    newest = _as_date(series[-1][0])
    if newest is None:
        return None
    last = series[-1][1]
    for d, g in reversed(series[:-1]):
        if g != last:
            dd = _as_date(d)
            return (newest - dd).days if dd else None
    return (newest - (_as_date(series[0][0]) or newest)).days   # 全程没翻过


def longest_prior_run(series: Sequence[tuple[str, str]]) -> Optional[int]:
    """历史上最长的一段同标签连续期(天),**不含正在进行的那一段**。

    问的是「这个面板见过多长的段」,不是「它平均多久翻一次」。排除进行中的段,
    否则当前这段会成为自己的基线,判据永远不触发 —— 与基线窗口排除近端同理。
    """
    runs: list[int] = []
    start = None
    prev_g = None
    prev_d = None
    for d, g in series:
        dd = _as_date(d)
        if dd is None:
            continue
        if prev_g is None:
            start, prev_g, prev_d = dd, g, dd
            continue
        if g != prev_g:
            runs.append((prev_d - start).days)
            start = dd
            prev_g = g
        prev_d = dd
    # 末尾那段是进行中的,故意不 append
    return max(runs) if runs else None


def classify(rows: Iterable[dict], *, today: Optional[dt.date] = None) -> RegimeQuorum:
    """对最新一天出裁决。`rows` 是 `daily_macro_regime` 的行,须含 n_obs / n_sources。

    调用方**必须**把这三列都取来。只取 `d, regime` 正是本模块存在的原因。
    """
    today = today or dt.date.today()
    clean = []
    for r in rows or []:
        d = _as_date(r.get("d", ""))
        if d is None or not r.get("regime"):
            continue
        clean.append((d, str(r["regime"]), int(r.get("n_obs") or 0),
                      int(r.get("n_sources") or 0)))
    if not clean:
        return RegimeQuorum("", None, 0, 0, NO_DATA, "daily_macro_regime 没有可用行")
    clean.sort(key=lambda x: x[0])

    # ── 今天这一行还在填,不能当完整的一天来判 ──────────────────────────
    #
    # `daily_macro_regime` 按日期聚合,所以当天的行整天都在长:实测 2026-09-01
    # 上午 `n_obs=86`,而基线中位数是 ~1450。拿它跟基线比 → 6%,直接判 COLLAPSED。
    # **那会变成每天早上一次误报**,而误报的代价是下游拒绝定仓。
    #
    # 「一天写完了」和「一天塌了」是两个状态,行数上长得一样。唯一能区分它们的
    # 不是行数,是**日期是不是今天**。所以判据落在最新的【完整】一天上,
    # 今天那行的数字另外带出去,由调用方自己看。
    partial = None
    judged = clean
    if clean[-1][0] >= today:
        partial = clean[-1]
        judged = clean[:-1]
    if not judged:
        d_p, g_p, o_p, s_p = partial                             # type: ignore[misc]
        return RegimeQuorum(d_p.isoformat(), g_p, o_p, s_p, NO_BASELINE,
                            "只有今天这一行,而今天还没写完 —— 无法判定")
    d_now, g_now, obs_now, src_now = judged[-1]

    series = [(d.isoformat(), g) for d, g, _o, _s in judged]
    dsf = days_since_flip(series)

    # 基线:更早的一段,不含最近 BASELINE_HI_DAYS 天。
    lo = today - dt.timedelta(days=BASELINE_LO_DAYS)
    hi = today - dt.timedelta(days=BASELINE_HI_DAYS)
    base = [(o, s) for d, _g, o, s in judged if lo <= d <= hi]
    if len(base) < MIN_BASELINE_DAYS:
        return RegimeQuorum(
            d_now.isoformat(), g_now, obs_now, src_now, NO_BASELINE,
            f"基线窗口({BASELINE_LO_DAYS}–{BASELINE_HI_DAYS}d 前)只有 {len(base)} 天,"
            f"不足 {MIN_BASELINE_DAYS} —— 未量,不等于健康 (S-246)",
            days_since_flip=dsf)

    b_src = statistics.median(s for _o, s in base)
    b_obs = statistics.median(o for o, _s in base)

    def _pack(verdict: str, reason: str) -> RegimeQuorum:
        return RegimeQuorum(d_now.isoformat(), g_now, obs_now, src_now, verdict,
                            reason, b_src, b_obs, dsf,
                            partial_today=(partial[0].isoformat(), partial[1],
                                           partial[2], partial[3]) if partial else None)

    # ── 塌陷优先于其它裁决:一个只有 1 个信源的「一致」不是一致 ──────────
    if b_src >= 2 and src_now <= 1:
        return _pack(COLLAPSED,
                     f"信源数 {src_now}(基线中位数 {b_src:g})—— 「全票通过」是减员"
                     f"产生的,不是共识。标签仍是 {g_now},但它现在只有一个投票人")
    if b_obs > 0 and obs_now < b_obs * COLLAPSE_RATIO:
        return _pack(COLLAPSED,
                     f"票数 {obs_now} < 基线 {b_obs:g} 的 {COLLAPSE_RATIO:.0%} —— "
                     f"投票的资产少了一半以上,众数不再代表这个面板")

    # ── 冻结:信源还在,但标签停太久 ────────────────────────────────────
    lpr = longest_prior_run(series)
    if dsf is not None and lpr and dsf > lpr * FROZEN_MULT:
        return _pack(FROZEN,
                     f"标签 {g_now} 已停留 {dsf} 天,而这个面板历史上最长的一段是 "
                     f"{lpr} 天(× {FROZEN_MULT:g} = {lpr * FROZEN_MULT:g})—— 可能是判断,"
                     f"也可能是输入死了之后被抄下来的;两者从这里分不开,所以不放行")

    if src_now < b_src or (b_obs > 0 and obs_now < b_obs * THIN_RATIO):
        return _pack(THIN,
                     f"信源 {src_now}/基线 {b_src:g} · 票数 {obs_now}/基线 {b_obs:g}"
                     f" —— 可用但须在下游标注")

    return _pack(OK, f"信源 {src_now} · 票数 {obs_now} · 距上次翻转 {dsf} 天")


#: PostgREST 的 select 串。**集中在这里**,因为「只取 d,regime」正是本模块要修的
#: 那个 bug —— 把列清单散在两个调用点上,下一个调用点还会漏掉票数。
SELECT_COLS = "d,regime,n_obs,n_sources"
