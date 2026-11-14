"""⓪ 周期向量(HIGH_DIM_ONTOLOGY §5b-bis:「⓪ 层是我们最该建的能力」;Jazz 11-04「继续」)—— 先把「拐点长什么样」记成一张表。

## 为什么不是又一个减仓信号

③ 的四条路三条 ❌(S-685 / S-692 / S-710):每条都是**一个标量**过阈值就减仓。⓪ 层问的不一样:不是「哪个指标高了」,
是「流动性周期是不是在**转向**」—— 转向是状态的**移动**,不是状态的**位置**。所以这里记两样东西:
- `deterioration`:九个分量的带符号 z 分数均值(流动性 / 广度 / 买盘为正好,杠杆 / 借贷利率 / 波动率抬升为负好);
- `shift`:今天的向量离**过去 90 → 30 天质心**的欧氏距离(状态搬了多远)。
拐点 = 既在恶化、又在快速搬家、**并且持续**(连续 3 天)。`phase`(normal / turning)按 S-713 写死的规则打,带滞回。**这里只记,不动钱**;
S-713 让 lane-c 在 2019 起的每一段 ≥ 30% 回撤上回放它值不值。

## 分量(全部按时点;z 用**扩张窗口**的均值 / 标准差,前 365 天不打分)

| 名 | 来源 | 符号(+ = 对风险资产好) |
|---|---|---|
| stable_supply_30d | state_daily panel | + 稳定币供给增 |
| fed_liq_60d | macro_daily fed_net_liquidity 60 日变化 | + |
| breadth | state_daily breadth_above_ma50 | + |
| taker_buy | state_daily taker_buy_share_30d | + |
| mom_60 | state_daily mom_60 | + |
| funding | state_daily funding_7d_ann_binance(binance_perp 5 主流,2020-01 起;HL 的 funding_7d_ann 只有 2026-09 起,混进同一条 z 序列就是 S-273 那种「两条看起来一样的量」) | − 杠杆拥挤 |
| oi_chg | state_daily oi_chg_30d(HL,2026-10-27 起;满 365 天前不参与打分,是**第 9 个**,不是前 8 个的条件) | − |
| lend_apy | state_daily stable_lend_apy_7d | − 借贷需求晚周期 |
| vratio | state_daily vratio_30_180 | − 波动率抬升 |

表 `cycle_vector_daily`(d 主键)。每天整条重算、整条 upsert(2019 起约 2,900 行;幂等,无状态可丢)。
判活:`select d, deterioration, shift, phase from cycle_vector_daily order by d desc limit 3`。
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Optional

TABLE = "cycle_vector_daily"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {"cycle_vector_daily": ("d", "components", "z", "deterioration", "shift", "shift_pct", "phase", "n_components", "code_ref")}
CODE_REF = "cycle_vector v1.1 (11-04: funding ← binance 2020 起; 不写 d 之后的行; code_ref 变了整条重算)"
LOOP_NAME = "_cycle_vector_loop"
SIGN = {"stable_supply_30d": 1, "fed_liq_60d": 1, "breadth": 1, "taker_buy": 1, "mom_60": 1,
        "funding": -1, "oi_chg": -1, "lend_apy": -1, "vratio": -1}
STATE_FEATURES = {"stable_supply_30d": "stable_supply_30d", "breadth": "breadth_above_ma50", "taker_buy": "taker_buy_share_30d",
                  "mom_60": "mom_60", "funding": "funding_7d_ann_binance", "oi_chg": "oi_chg_30d", "lend_apy": "stable_lend_apy_7d",
                  "vratio": "vratio_30_180"}
MIN_HISTORY = 365
CENTROID_FROM, CENTROID_TO = 90, 30
MIN_COMPONENTS = 6
#: S-713 的相位规则(写死,不扫):恶化 ≤ −0.5 且搬家距离在自己扩张历史的 ≥ 75 分位 **连续 3 天** ⇒ turning;恶化回到 > 0 ⇒ normal(滞回)。
#: 连续 3 天是去抖:九个独立噪声分量的均值 ≤ −0.5 本身每天就有约 7% 的概率,单日触发在纯噪声上一年误报十几次。
TURN_DET, TURN_SHIFT_PCT, EXIT_DET, TURN_DAYS = -0.5, 0.75, 0.0, 3


def _f(x: Any) -> Optional[float]:
    try:
        v = None if x is None else float(x)
    except (TypeError, ValueError):
        return None
    return v if v is None or v == v else None


def components_by_day(state_rows: list[dict], macro_rows: list[dict]) -> dict[str, dict[str, float]]:
    """纯函数。state_daily(panel)行 + macro_daily(fed_net_liquidity)行 → {d: {分量: 值}}。fed_liq_60d = 60 日前有值才算。"""
    out: dict[str, dict[str, float]] = {}
    for r in state_rows:
        d, f, v = str(r.get("d"))[:10], r.get("feature"), _f(r.get("value"))
        for name, feat in STATE_FEATURES.items():
            if f == feat and v is not None:
                out.setdefault(d, {})[name] = v
    liq = {str(r.get("d"))[:10]: _f(r.get("value")) for r in macro_rows if _f(r.get("value")) is not None}
    days = sorted(liq)
    for i, d in enumerate(days):
        back = (dt.date.fromisoformat(d) - dt.timedelta(days=60)).isoformat()
        j = max((k for k in days[:i] if k <= back), default=None)
        if j and liq[j]:
            out.setdefault(d, {})["fed_liq_60d"] = liq[d] / liq[j] - 1.0
    return out


def zscores(comps: dict[str, dict[str, float]]) -> list[dict]:
    """纯函数。按日期顺序的扩张窗口 z(每个分量各自的均值 / 标准差,只用 ≤ d 的历史;前 MIN_HISTORY 天不打分)→
    每天一行 {d, components, z, deterioration, shift, shift_pct, phase, n_components}。"""
    days = sorted(comps)
    sums: dict[str, float] = {}
    sq: dict[str, float] = {}
    n: dict[str, int] = {}
    z_hist: list[dict[str, float]] = []
    shift_hist: list[float] = []
    rows: list[dict] = []
    phase = "normal"
    streak = 0
    for i, d in enumerate(days):
        c = comps[d]
        z: dict[str, float] = {}
        for k, v in c.items():
            if n.get(k, 0) >= MIN_HISTORY:
                mean = sums[k] / n[k]
                var = sq[k] / n[k] - mean * mean
                sd = math.sqrt(var) if var > 1e-18 else 0.0
                if sd > 0:
                    z[k] = max(-4.0, min(4.0, (v - mean) / sd))
            sums[k] = sums.get(k, 0.0) + v
            sq[k] = sq.get(k, 0.0) + v * v
            n[k] = n.get(k, 0) + 1
        z_hist.append(z)
        det = shift = pct = None
        if len(z) >= MIN_COMPONENTS:
            det = sum(SIGN[k] * v for k, v in z.items()) / len(z)
            past = [h for h in z_hist[max(0, i - CENTROID_FROM):max(0, i - CENTROID_TO)] if len(h) >= MIN_COMPONENTS]
            if past:
                keys = [k for k in z if all(k in h for h in past)]
                if len(keys) >= MIN_COMPONENTS:
                    cen = {k: sum(h[k] for h in past) / len(past) for k in keys}
                    shift = math.sqrt(sum((z[k] - cen[k]) ** 2 for k in keys) / len(keys))
                    pct = sum(1 for s in shift_hist if s <= shift) / len(shift_hist) if shift_hist else None
                    shift_hist.append(shift)
            if det is not None:
                hit = shift is not None and pct is not None and det <= TURN_DET and pct >= TURN_SHIFT_PCT
                streak = streak + 1 if hit else 0
                if phase == "normal" and streak >= TURN_DAYS:
                    phase = "turning"
                elif phase == "turning" and det > EXIT_DET:
                    phase, streak = "normal", 0
        rows.append({"d": d, "components": {k: round(v, 6) for k, v in c.items()}, "z": {k: round(v, 4) for k, v in z.items()},
                     "deterioration": None if det is None else round(det, 4), "shift": None if shift is None else round(shift, 4),
                     "shift_pct": None if pct is None else round(pct, 3), "phase": phase if det is not None else None,
                     "n_components": len(z), "code_ref": CODE_REF})
    return rows


async def latest() -> dict[str, Any]:
    from src.data.style.header import _read_all
    # 11-06:最新一行常常是「分量还没到齐」(deterioration / phase 为空)—— 取最近一条打过分的,并带上它的日期,
    # 否则 ③ 的决定读到的 ⓪ 是空的(11-05 的 inputs.cycle_phase = null)。
    rows = await _read_all(TABLE, {"select": "d,deterioration,shift,shift_pct,phase", "deterioration": "not.is.null",
                                   "order": "d.desc", "limit": "1"})
    return rows[0] if rows else {}


async def run_once(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.style.header import _read_all
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    d = (now.date() - dt.timedelta(days=1)).isoformat()
    have = await _read_all(TABLE, {"select": "d,code_ref", "d": f"eq.{d}", "limit": "1"})
    if have and (have[0].get("code_ref") or "") == CODE_REF:
        return {"ok": True, "status": "already_done", "why": f"{d} 已写"}
    feats = ",".join(STATE_FEATURES.values())
    state = await _read_all("state_daily", {"select": "d,feature,value", "entity": "eq.panel", "feature": f"in.({feats})", "order": "d.asc,feature.asc"})
    macro = await _read_all("macro_daily", {"select": "d,value", "series": "eq.fed_net_liquidity", "order": "d.asc"})
    comps = components_by_day(state, macro)
    if d not in comps:
        return {"ok": True, "status": "skipped", "why": f"{d} 的 state_daily 还没到"}
    rows = [r for r in zscores(comps) if r["d"] <= d]           # state_daily 可能已有今天的半日行;不写 d 之后的
    w = await supabase_upsert_table(TABLE, rows, on_conflict="d")
    if not w:
        return {"ok": False, "why": f"写 {TABLE} 失败:{(getattr(w, 'why', '') or '')[:200]}"}
    last = rows[-1]
    return {"ok": True, "d": d, "written": len(rows), "deterioration": last["deterioration"], "shift": last["shift"],
            "shift_pct": last["shift_pct"], "phase": last["phase"],
            "why": f"重算至 {d}:恶化 {last['deterioration']} · 搬家 {last['shift']}(分位 {last['shift_pct']})· {last['phase']}"}
