"""④ 资金费套息的纸面前向账(S-733 ✅ ⇒ 开前向臂;不动钱)—— HL 现货多 + 等额永续空,收空方的已实现资金费。

## 预注册(照 S-707 / S-733 原样;改任何一项 = 新起点,旧记录留档)

    名单    ① 面板 24 名里 HL 有永续费率的(当日 ≥ 20 个小时档才算有)
    臂      carry_a  常开                                     —— ④ 的基准线(什么都不判的套息拿多少)
            carry_b  每周一(UTC)看过去 7 天日费率均值 > 0 才开(至少 5 天有数),否则空仓 —— 这是 S-733 判 ✅ 的那条
            carry_b_spot  同 carry_b,只在 HL 有现货代币的 10 名上(lane-a T-250 用 spotMeta 列的;现货腿与永续腿同场馆,真能做的那一档)
    收益    当日 = 在场名字的当日费率之和(空方收正费率)÷ 当日有费率的名字数(等权、不在场的份额闲置)
    成本    每次开 / 关:现货 taker 4bp + 永续 taker 3.5bp(按该名字的名义);A 只在起点付一次
    口径    **按名义本金**。资本口径 = 名义 ÷ (1 + 保证金率);基差盈亏不记(S-707 同)
    起点    2026-11-05 收盘(决定在 11-05 做出);第一天前向收益是 11-06;NAV 在起点 = 1

## 读之前先知道

S-733 全样本 B 净 12.2%/yr 是 2024 撑的;2025 6.3%、2026H1 1.9%。前向期望按最近的写。
判活:`select arm, max(d), count(*) from carry_hl_daily group by 1`(UTC 02:00 后 max(d) 应 = 昨天)。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

import numpy as np

TABLE = "carry_hl_daily"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("d", "arm", "ret", "nav", "n_names", "n_on", "switches", "inception", "code_ref")}
CODE_REF = "carry_hl v1.2 (11-06, S-733;+ carry_b_spot;+ carry_b_top S-735)"
LOOP_NAME = "_carry_hl_loop"
ARMS = ("carry_a", "carry_b", "carry_b_spot", "carry_b_top")
#: ① 24 名里 HL 现货有对应代币的(lane-a T-250,HL info spotMeta,11-05):UBTC / UETH / USOL / BNB0 / XRP1 / UDOGE / UAVAX / LINK0 / TRX0 / AAVE0
HL_SPOT_NAMES = ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "AVAX", "LINK", "TRX", "AAVE")
INCEPTION = dt.date(2026, 11, 5)
WARMUP_DAYS = 45                  # carry_b_top 要过去 30 天的排名
COST = 0.0004 + 0.00035
MIN_HOURS = 20
MIN_COVERAGE = 0.8


def matrix(rows: list[dict], names: tuple[str, ...], d0: dt.date, d1: dt.date) -> tuple[list[dt.date], np.ndarray]:
    """纯函数。日视图行 {coin, d, rate_sum, n_hours} → 日 × 名字 的费率矩阵;小时数不够的格子是 NaN。"""
    days = [d0 + dt.timedelta(i) for i in range((d1 - d0).days + 1)]
    di = {d: i for i, d in enumerate(days)}
    ni = {n: j for j, n in enumerate(names)}
    F = np.full((len(days), len(names)), np.nan)
    for r in rows:
        d = dt.date.fromisoformat(str(r.get("d"))[:10])
        if d in di and r.get("coin") in ni and int(r.get("n_hours") or 0) >= MIN_HOURS and r.get("rate_sum") is not None:
            F[di[d], ni[r["coin"]]] = float(r["rate_sum"])
    return days, F


def rule_b(F: np.ndarray, i: int) -> np.ndarray:
    """纯函数。第 i 天(周一)的开关:过去 7 天(i−7 … i−1)至少 5 天有数且均值 > 0。"""
    w = F[max(0, i - 7):i]
    if len(w) == 0:
        return np.zeros(F.shape[1], bool)
    cnt = (~np.isnan(w)).sum(0)
    with np.errstate(all="ignore"):
        mu = np.nanmean(w, 0)
    return (cnt >= 5) & (np.nan_to_num(mu) > 0)


TOP_LOOKBACK = 30


def top_half(F: np.ndarray, i: int) -> np.ndarray:
    """纯函数。第 i 天(周一)按过去 30 天(i−30 … i−1)日费率均值排名,取前一半(并列按列序 = 代码字母序);没数的名字不入选。
    S-735 / T-253 ✅(Seth 11-06 裁定分母 = 选中的名字,读法 (i))。"""
    w = F[max(0, i - TOP_LOOKBACK):i]
    with np.errstate(all="ignore"):
        mu = np.nanmean(w, 0) if len(w) else np.full(F.shape[1], np.nan)
    ok = ~np.isnan(mu)
    sel = np.zeros(F.shape[1], bool)
    n = int(ok.sum()) // 2
    if n:
        order = sorted((j for j in range(F.shape[1]) if ok[j]), key=lambda j: (-mu[j], j))
        sel[order[:n]] = True
    return sel


def _decide(F: np.ndarray, i: int, arm: str) -> tuple[np.ndarray, np.ndarray]:
    """(持有, 计入分母的名字)。carry_b_top:持有 = 规则 B ∧ 选中,分母 = 选中;其余臂分母 = 全部。"""
    on = rule_b(F, i)
    if arm == "carry_b_top":
        sel = top_half(F, i)
        return on & sel, sel
    return on, np.ones(F.shape[1], bool)


def path(days: list[dt.date], F: np.ndarray, arm: str, inception: dt.date = INCEPTION) -> list[dict]:
    """纯函数。从起点起逐日记账:起点那天收盘建仓(成本记在第一天前向收益上),NAV 在起点 = 1。carry_b_spot 由调用方传子集列。"""
    avail = ~np.isnan(F)
    Fz = np.nan_to_num(F)
    k0 = days.index(inception)
    if arm == "carry_a":
        on = np.ones(F.shape[1], bool)
    else:
        last_mon = max(i for i in range(k0 + 1) if days[i].weekday() == 0)
        on, members = _decide(F, last_mon, arm)
    if arm == "carry_a":
        members = np.ones(F.shape[1], bool)
    pend_members = members
    held = np.zeros(F.shape[1], bool)               # 起点前空仓
    nav, out, switches = 1.0, [{"d": inception.isoformat(), "arm": arm, "ret": 0.0, "nav": 1.0, "n_names": int(avail[k0].sum()),
                                "n_on": int((on & avail[k0]).sum()), "switches": 0}], 0
    pending = on
    for i in range(k0 + 1, len(days)):
        cost = np.zeros(F.shape[1])
        if pending is not None:                       # 前一天收盘的决定在今天生效
            ch = pending != held
            if arm == "carry_a":
                ch = pending & ~held
            cost[ch] = COST
            switches += int(ch.sum())
            held = pending
            members = pend_members
            pending = None
        m = avail[i] & members
        n = int(m.sum())
        # 收益 = 分母内名字的费率之和 − 当天全部开 / 关成本(含刚被挤出选中名单的那几个)÷ 分母名数
        r = float((np.where(held, Fz[i], 0.0)[m].sum() - cost.sum()) / n) if n else 0.0
        nav *= 1.0 + r
        out.append({"d": days[i].isoformat(), "arm": arm, "ret": round(r, 8), "nav": round(nav, 8), "n_names": n,
                    "n_on": int((held & avail[i]).sum()), "switches": switches})
        if arm != "carry_a" and days[i].weekday() == 6:   # 周日收盘决定 ⇒ 周一生效(= 周一看过去 7 天)
            pending, pend_members = _decide(F, i + 1, arm)
    return out


async def run_once(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.market.hl_funding_hourly import DAILY_VIEW, coins
    from src.data.style.header import _read_all
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    through = now.date() - dt.timedelta(days=1)
    if through <= INCEPTION:
        return {"ok": True, "status": "skipped", "why": f"起点 {INCEPTION} 之后还没有完整的一天"}
    names = coins()
    d0 = INCEPTION - dt.timedelta(days=WARMUP_DAYS)
    rows = await _read_all(DAILY_VIEW, {"select": "coin,d,rate_sum,n_hours", "d": f"gte.{d0}", "order": "coin.asc,d.asc"})
    rows = [r for r in rows if str(r.get("d"))[:10] <= through.isoformat()]
    days, F = matrix(rows, names, d0, through)
    have_last = int((~np.isnan(F[-1])).sum())
    if have_last < MIN_COVERAGE * len(names):
        return {"ok": False, "refused": True, "status": "refused",
                "why": f"{through} 只有 {have_last}/{len(names)} 名有完整的已实现费率(hl_funding_hourly 还在回填或断了)"}
    spot = [j for j, n in enumerate(names) if n in HL_SPOT_NAMES]
    cols = {"carry_a": slice(None), "carry_b": slice(None), "carry_b_spot": spot, "carry_b_top": slice(None)}
    out = [r | {"inception": INCEPTION.isoformat(), "code_ref": CODE_REF} for arm in ARMS for r in path(days, F[:, cols[arm]], arm)]
    w = await supabase_upsert_table(TABLE, out, on_conflict="d,arm")
    if not w:
        return {"ok": False, "why": f"写 {TABLE} 失败:{(getattr(w, 'why', '') or '')[:200]}"}
    last = {r["arm"]: r for r in out if r["d"] == through.isoformat()}
    return {"ok": True, "written": len(out), "through": through.isoformat(),
            "nav": {a: last[a]["nav"] for a in last}, "n_on": {a: last[a]["n_on"] for a in last},
            "why": f"{through}:" + " · ".join(f"{a} NAV {last[a]['nav']:.5f}(在场 {last[a]['n_on']}/{last[a]['n_names']})" for a in sorted(last))}
