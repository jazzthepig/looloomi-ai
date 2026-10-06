"""L1 状态层 `state_daily` —— v0.2 阶段 2(T-048)。长表 (d, entity, feature, value, source, code_ref),加一个特征不改表结构。

lane A 交了第一版(特征清单、regime 归一、长表格式是它定的);合并时 Seth 重写了读数与时点部分(S-494):
A 版的读取端用了库里不存在的列(funding_history.d / rate、open_interest_history.d / oi_usd)、
一张手写的 24 名(与 ① 的面板只有一半重合)、风格表里不存在的 weighting / style 代码、吞掉非 200 返回、
单次请求 5,000 行(PostgREST 只给 1,000) —— 跑起来会**整列静默为空**;regime 占比在没有数据时写 0.0;
声称的 PIT 测试文件不在交付里。

## 时点(PIT)是结构上保证的,不是靠审查

`features_at(d, inputs)` 第一件事就是把每个输入截到 `≤ d`(`_cut`),之后的计算碰不到 d 之后的任何一行 ——
「偷看」写不出来(AQuA 的教训)。`tests/test_state_daily_pit.py` 再把 d 之后的数据全部改掉,逐位比对。

## 特征(entity = 'panel',每天一组;缺数据 = None,不是 0)

    mom_20 / mom_60 / mom_200   ① NAV 的日历日动量:nav(d) / nav(d−N) − 1(任一端缺 ⇒ None)
    dist_200                     nav(d) / 近 200 日均值 − 1(窗口内 ≥ 180 个点)
    vol_30                       ① 日收益近 30 日标准差 × √365(≥ 25 个点)
    vol_pct_3y                   vol_30 在近 3 年 vol_30 序列里的分位(≥ 900 个点)
    breadth_above_ma50           ① 面板里收盘高于自身 50 日均线的比例(每币窗口内 ≥ 45 个真实收盘;前推价不算)
    funding_7d_ann               Hyperliquid 资金费:每币日均小时费率 × 24 × 365,取面板中位数,再取近 7 日均值(≥ 5 天)
    oi_chg_30d                   Hyperliquid 持仓量:每币 oi(d) / oi(d−30) − 1 的面板中位数(两端都在的币 ≥ 5 个)
    style_rel_majors_30d         style_index_daily(cap):majors 30 日收益 − second_l1_l2 30 日收益
    regime_share_30d:<类>        近 30 日里各类的占比;类 = 6 类(见 REGIMES);有标签的天 < 20 ⇒ None
    regime_coverage_30d          近 30 日里有标签的天数(0–30)

资金费只有 HL(2026-09-05 起)、持仓量只有 HL(09-27 起):之前一律 None,不拼别的场所(规则 3b)。
① 只有一个读法:`registry.core_nav`。面板 = `core_cap.panel_universe()`,价格 = `panel_read.read_panel(binance_hist)`。

## 判活判据(规则 5b ②)

    select max(d), count(*) from state_daily where feature = 'mom_20';   -- UTC 08:00 后 max(d) 应 = 昨天
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

import pandas as pd

TABLE = "state_daily"
WRITES_TABLES = (TABLE,)
ENTITY = "panel"
CODE_REF = "T-048 state_daily v1"
BACKFILL_START = "2023-01-01"
RECENT_DAYS = 14

#: regime_daily.regime_db 实测 9 种写法 = 6 类(S-485 复盘时查明)
REGIMES = ("EASING", "NEUTRAL", "RISK_OFF", "RISK_ON", "STAGFLATION", "TIGHTENING")
_REGIME_ALIASES = {"riskoff": "RISK_OFF", "riskon": "RISK_ON"}
MIN_REGIME_COVERAGE = 20


def normalise_regime(raw: Optional[str]) -> Optional[str]:
    """任一写法 → 6 类之一;认不出的 ⇒ None(不是某个兜底类 —— 兜底类会被当成真的状态)。"""
    if raw is None:
        return None
    key = str(raw).strip().upper().replace("-", "_").replace(" ", "_")
    key = _REGIME_ALIASES.get(key.lower().replace("_", ""), key)
    return key if key in REGIMES else None


def _cut(x, d: pd.Timestamp):
    """把一个输入截到 ≤ d。所有特征只从截过的输入里算 —— 这是 PIT 的结构保证。"""
    if x is None:
        return None
    return x.loc[:d]


def _at(s: pd.Series, d: pd.Timestamp) -> Optional[float]:
    v = s.get(d) if s is not None else None
    return float(v) if v is not None and pd.notna(v) and math.isfinite(float(v)) else None


def _ret(s: pd.Series, d: pd.Timestamp, days: int) -> Optional[float]:
    a, b = _at(s, d), _at(s, d - pd.Timedelta(days=days))
    return a / b - 1 if a is not None and b is not None and b > 0 else None


def _clean(v: Optional[float]) -> Optional[float]:
    return float(v) if v is not None and math.isfinite(float(v)) else None


def features_at(d: pd.Timestamp, inputs: Mapping[str, Any]) -> list[dict]:
    """纯函数。`inputs`:
        core      pd.Series  ① NAV(日)
        px        pd.DataFrame 面板真实收盘(前推价已抹成 NaN),列 = 币
        regimes   pd.Series  归一后的类(日),认不出的不在里面
        funding   pd.Series  面板资金费(年化,日)
        oi        pd.DataFrame 每币持仓量(日末快照),列 = 币
        style     pd.DataFrame 列 majors / second_l1_l2 的指数水平(日)
    """
    d = pd.Timestamp(d)
    core = _cut(inputs.get("core"), d)
    px = _cut(inputs.get("px"), d)
    regimes = _cut(inputs.get("regimes"), d)
    funding = _cut(inputs.get("funding"), d)
    oi = _cut(inputs.get("oi"), d)
    style = _cut(inputs.get("style"), d)
    out: dict[str, tuple[Optional[float], str]] = {}

    if core is not None and len(core):
        for n in (20, 60, 200):
            out[f"mom_{n}"] = (_ret(core, d, n), "registry.core_nav")
        win = core[core.index > d - pd.Timedelta(days=200)]
        out["dist_200"] = ((_at(core, d) / float(win.mean()) - 1) if _at(core, d) is not None and len(win) >= 180
                           else None, "registry.core_nav")
        r = core.pct_change()
        r30 = r[r.index > d - pd.Timedelta(days=30)].dropna()
        vol = float(r30.std() * math.sqrt(365)) if len(r30) >= 25 and _at(core, d) is not None else None
        out["vol_30"] = (vol, "registry.core_nav")
        roll = r.rolling(30, min_periods=25).std() * math.sqrt(365)
        hist = roll[roll.index > d - pd.Timedelta(days=3 * 365)].dropna()
        out["vol_pct_3y"] = (float((hist <= vol).mean()) if vol is not None and len(hist) >= 900 else None,
                             "registry.core_nav")
    else:
        for f in ("mom_20", "mom_60", "mom_200", "dist_200", "vol_30", "vol_pct_3y"):
            out[f] = (None, "registry.core_nav")

    breadth = None
    if px is not None and d in px.index:
        w = px[px.index > d - pd.Timedelta(days=50)]
        last = px.loc[d]
        ok = [c for c in px.columns if pd.notna(last.get(c)) and w[c].notna().sum() >= 45]
        if ok:
            breadth = sum(1 for c in ok if float(last[c]) > float(w[c].mean())) / len(ok)
    out["breadth_above_ma50"] = (breadth, "binance_hist")

    f7 = None
    if funding is not None:
        w = funding[funding.index > d - pd.Timedelta(days=7)].dropna()
        f7 = float(w.mean()) if len(w) >= 5 and d in w.index else None
    out["funding_7d_ann"] = (f7, "funding_history:hyperliquid")

    oc = None
    if oi is not None and d in oi.index and (d - pd.Timedelta(days=30)) in oi.index:
        a, b = oi.loc[d], oi.loc[d - pd.Timedelta(days=30)]
        ch = [(float(a[c]) / float(b[c]) - 1) for c in oi.columns
              if pd.notna(a.get(c)) and pd.notna(b.get(c)) and float(b[c]) > 0]
        oc = float(pd.Series(ch).median()) if len(ch) >= 5 else None
    out["oi_chg_30d"] = (oc, "open_interest_history:hyperliquid")

    srel = None
    if style is not None and {"majors", "second_l1_l2"} <= set(style.columns):
        m, s2 = _ret(style["majors"], d, 30), _ret(style["second_l1_l2"], d, 30)
        srel = m - s2 if m is not None and s2 is not None else None
    out["style_rel_majors_30d"] = (srel, "style_index_daily:cap")

    cov = 0
    shares: dict[str, Optional[float]] = {k: None for k in REGIMES}
    if regimes is not None:
        w = regimes[regimes.index > d - pd.Timedelta(days=30)].dropna()
        cov = int(len(w))
        if cov >= MIN_REGIME_COVERAGE:
            shares = {k: float((w == k).mean()) for k in REGIMES}
    for k in REGIMES:
        out[f"regime_share_30d:{k}"] = (shares[k], "regime_daily")
    out["regime_coverage_30d"] = (float(cov), "regime_daily")

    return [{"d": d.date().isoformat(), "entity": ENTITY, "feature": f, "value": _clean(v), "source": src,
             "code_ref": CODE_REF} for f, (v, src) in out.items()]


# ── 读数(I/O)──────────────────────────────────────────────────────────────

async def load_inputs(start: str) -> dict[str, Any]:
    """读不到抛异常 —— 读不到 ≠ 没有数据。"""
    from src.data.accounting.registry import core_nav
    from src.data.market.panel_read import read_panel
    from src.data.signals.core_cap import panel_universe
    from src.data.style.header import _read_all

    core = await core_nav(start=start)
    if core is None or core.dropna().empty:
        raise RuntimeError("① NAV 读不到(registry.core_nav)—— 不出状态")
    panel = list(panel_universe())
    p = await read_panel(panel, start=start, source="binance_hist")
    idx = pd.to_datetime(p.days)
    px = pd.DataFrame(p.close, index=idx, columns=p.symbols, dtype=float)
    px = px.mask(pd.DataFrame(p.filled, index=idx, columns=p.symbols))

    rg = await _read_all("regime_daily", {"select": "d,regime_db", "order": "d.asc"})
    regimes = pd.Series({pd.Timestamp(r["d"]): normalise_regime(r.get("regime_db")) for r in rg}, dtype=object)
    regimes = regimes.dropna().sort_index()

    syms = "in.(" + ",".join(panel) + ")"
    lo = max(pd.Timestamp(start), pd.Timestamp("2026-09-01")).date().isoformat()
    fr = await _read_all("funding_history", {"select": "symbol,funding_time,funding_rate", "venue": "eq.hyperliquid",
                                             "symbol": syms, "funding_time": f"gte.{lo}", "order": "funding_time.asc"})
    funding = None
    if fr:
        f = pd.DataFrame(fr)
        f["d"] = pd.to_datetime(f["funding_time"], utc=True).dt.tz_localize(None).dt.normalize()
        daily = f.groupby(["d", "symbol"])["funding_rate"].mean().unstack()
        funding = (daily * 24 * 365).median(axis=1, skipna=True).sort_index()
    orows = await _read_all("open_interest_history", {"select": "symbol,snapshot_time,open_interest",
                                                      "venue": "eq.hyperliquid", "symbol": syms,
                                                      "snapshot_time": f"gte.{lo}", "order": "snapshot_time.asc"})
    oi = None
    if orows:
        o = pd.DataFrame(orows)
        o["d"] = pd.to_datetime(o["snapshot_time"], utc=True).dt.tz_localize(None).dt.normalize()
        oi = o.sort_values("snapshot_time").groupby(["d", "symbol"])["open_interest"].last().unstack().astype(float)
    st = await _read_all("style_index_daily", {"select": "d,style,level", "weighting": "eq.cap",
                                               "style": "in.(majors,second_l1_l2)", "order": "d.asc"})
    style = None
    if st:
        s = pd.DataFrame(st)
        s["d"] = pd.to_datetime(s["d"])
        style = s.pivot_table(index="d", columns="style", values="level").astype(float)
    return {"core": core.sort_index(), "px": px, "regimes": regimes, "funding": funding, "oi": oi, "style": style}


async def run_once(backfill: bool = False) -> dict[str, Any]:
    """平时只重算最近 RECENT_DAYS 天(幂等 upsert);`backfill=True` 从 BACKFILL_START 整条写。"""
    from src.api.store import supabase_upsert_table
    from src.data.style.header import _read_all

    target = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)
    have = await _read_all(TABLE, {"select": "d", "feature": "eq.mom_20", "order": "d.desc", "limit": "1"})
    first = backfill or not have
    start_days = pd.Timestamp(BACKFILL_START) if first else target - pd.Timedelta(days=RECENT_DAYS)
    # 读的起点要早于写的起点:200 日动量、3 年波动分位要往回看
    inputs = await load_inputs((start_days - pd.Timedelta(days=3 * 365 + 60)).date().isoformat())
    last_core = inputs["core"].dropna().index.max()
    end = min(target, last_core)
    days = pd.date_range(start_days, end, freq="D")
    if len(days) == 0:
        return {"ok": True, "refused": True, "written": 0, "reason": f"① 最新 {last_core.date()},没有新的日子"}
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for d in days:
        for r in features_at(d, inputs):
            r["computed_at"] = now
            rows.append(r)
    for i in range(0, len(rows), 1000):
        res = await supabase_upsert_table(TABLE, rows[i:i + 1000], on_conflict="d,entity,feature")
        if not res.ok:
            return {"ok": False, "refused": False, "written": i, "reason": f"写入失败:{res.why}"}
    last = [r for r in rows if r["d"] == end.date().isoformat()]
    n_null = sum(1 for r in last if r["value"] is None)
    return {"ok": True, "refused": False, "written": len(rows), "last_d": end.date().isoformat(),
            "reason": f"写到 {end.date()}({'回填' if first else '近 ' + str(RECENT_DAYS) + ' 天'});最后一天 {len(last)} 个特征,空 {n_null} 个",
            "null_last_day": [r["feature"] for r in last if r["value"] is None]}
