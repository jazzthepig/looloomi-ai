"""状态地图的前向记录(S-737 → T-257):每天按**冻结的** k-means 给市场状态打标;落在 S5 的日子记一张「BTC + 30 天 90% 看跌」纸面票。

## 冻结的是什么

T-257(lane-b)在 2021-03-01 → 2023-12-31 上拟合:13 个特征(下面 `FEATURES`)、训练期均值 / 标准差标准化、k = 6、种子 737、
n_init 20。这里**每次按同一规格重拟合**(训练窗是过去的、数据是按时点的 ⇒ 结果确定),再用 T-257 报告里各类的原始单位均值
(`T257_MEANS`)把拟合出来的类对到 S0 … S5 —— sklearn 版本不同类号会变,对齐靠中心,不靠编号。对不上(最近中心的标准化距离 > 1.0)
⇒ 那天 refused,不猜。

## 纸面票(S5 × A6,30 格里唯一过 BH 的那格)

进 S5 的那天 d:d 收盘「买」1 份 BTC 现货 + 1 份 30 天、行权价 = 0.9 × 现货的看跌(权利金 = `options_surface_daily.put90_30d_cost_pct`
的**真实报价**;那天没有期权面 ⇒ 用 DVOL 的 Black-Scholes 估价并标 `put_source = 'bs_dvol'`)。30 天后结算:
现货收益 + max(0, 0.9 − 到期价 / 进场价) − 权利金。同时记不带保护的 A1 作对照。已有一张在场 ⇒ 不叠加。**只记,不动钱。**

判活:`select d, state, dist from state_map_daily order by d desc limit 3`;`select status, count(*) from protected_long_paper group by 1`。
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Optional

import numpy as np

STATE_TABLE = "state_map_daily"
TICKET_TABLE = "protected_long_paper"
WRITES_TABLES = (STATE_TABLE, TICKET_TABLE)
WRITES_COLUMNS = {STATE_TABLE: ("d", "state", "dist", "features", "code_ref"),
                  TICKET_TABLE: ("ticket_id", "state", "entry_d", "entry_px", "strike", "put_cost_pct", "put_source", "expiry_d",
                                 "status", "exit_px", "ret_spot", "ret_protected", "code_ref")}
CODE_REF = "state_map v1 (11-06, S-737 / T-257 冻结规格)"
LOOP_NAME = "_state_map_loop"
FEATURES = ("mom_20", "mom_60", "mom_200", "dist_200", "vol_30", "vratio_30_180", "breadth_above_ma50", "funding_7d_ann_binance",
            "taker_buy_share_30d", "stable_supply_30d", "cycle:deterioration", "dvol:btc_pct_1y", "macro:vix")
TRAIN = ("2021-03-01", "2023-12-31")
K, SEED, N_INIT = 6, 737, 20
TARGET_STATE = 5
HOLD_DAYS = 30
STRIKE = 0.90
MAX_ALIGN_DIST = 1.0
#: T-257 报告(docs/research/t257_results.json)各类在训练期的原始单位均值,按 FEATURES 顺序 —— 只用来对齐类号
T257_MEANS = {
    0: (-0.1835, -0.1102, 2.5123, 0.1862, 1.5123, 1.4887, 0.0896, 0.051, 0.4903, 0.2113, -0.356, 0.7895, 17.8596),
    1: (-0.1707, -0.3669, -0.1287, -0.3212, 0.9095, 1.0706, 0.0525, -0.1776, 0.4927, -0.0073, -0.5371, 0.5667, 24.768),
    2: (0.1435, 0.2517, 0.2011, 0.1467, 0.564, 1.0265, 0.8353, 0.106, 0.4981, 0.0192, 0.1821, 0.3756, 18.0817),
    3: (0.1541, 0.5031, 4.8501, 1.0519, 0.755, 1.2986, 0.8077, 0.6365, 0.4945, 0.2321, 0.24, 0.5569, 18.7044),
    4: (-0.0225, -0.0642, 0.2219, 0.0133, 0.4024, 0.5036, 0.2707, 0.0199, 0.4874, 0.0004, -0.3247, 0.0767, 15.9762),
    5: (-0.0471, -0.0421, -0.182, -0.1465, 0.6533, 1.0237, 0.2083, -0.0228, 0.4975, 0.0126, -0.1426, 0.1951, 25.2221),
}


def matrix(rows: list[dict]) -> tuple[list[str], np.ndarray]:
    """纯函数。feature_matrix_daily 行 → (日期, 矩阵);13 个特征缺任何一个的日子不要。"""
    ds, X = [], []
    for r in sorted(rows, key=lambda r: str(r.get("d"))):
        f = r.get("f") or {}
        v = [f.get(k) for k in FEATURES]
        if all(isinstance(x, (int, float)) and x == x for x in v):
            ds.append(str(r["d"])[:10])
            X.append([float(x) for x in v])
    return ds, np.asarray(X, float).reshape(-1, len(FEATURES))


def fit(ds: list[str], X: np.ndarray) -> dict[str, Any]:
    """纯函数。冻结规格拟合 + 把拟合的类对到 T-257 的 S0 … S5(按标准化空间里最近的中心,一对一)。"""
    from sklearn.cluster import KMeans
    tr = np.array([TRAIN[0] <= d <= TRAIN[1] for d in ds])
    if tr.sum() < 200:
        raise ValueError(f"训练期只有 {int(tr.sum())} 天齐全")
    mu, sd = X[tr].mean(0), X[tr].std(0)
    sd = np.where(sd > 0, sd, 1.0)
    km = KMeans(n_clusters=K, random_state=SEED, n_init=N_INIT).fit((X[tr] - mu) / sd)
    ref = {s: (np.asarray(m) - mu) / sd for s, m in T257_MEANS.items()}
    # 每个拟合类的训练期均值(原始单位 → 标准化),一对一贪心匹配到最近的参考中心
    labels = km.labels_
    own = {c: ((X[tr][labels == c].mean(0) - mu) / sd) for c in range(K)}
    pairs = sorted((float(np.linalg.norm(own[c] - ref[s])), c, s) for c in range(K) for s in ref)
    mapping, used, worst = {}, set(), 0.0
    for dist, c, s in pairs:
        if c in mapping or s in used:
            continue
        mapping[c], worst = s, max(worst, dist)
        used.add(s)
    return {"mu": mu, "sd": sd, "km": km, "mapping": mapping, "align_worst": worst}


def assign(model: dict, x: np.ndarray) -> tuple[int, float]:
    z = (np.asarray(x, float) - model["mu"]) / model["sd"]
    d = np.linalg.norm(model["km"].cluster_centers_ - z, axis=1)
    c = int(np.argmin(d))
    return model["mapping"][c], float(d[c])


def bs_put(spot: float, strike: float, days: int, vol: float) -> float:
    """Black-Scholes 看跌(r = 0),占现货的比例。"""
    T = days / 365.0
    if vol <= 0 or T <= 0:
        return max(0.0, strike - spot) / spot
    d1 = (math.log(spot / strike) + 0.5 * vol * vol * T) / (vol * math.sqrt(T))
    d2 = d1 - vol * math.sqrt(T)
    N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    return (strike * N(-d2) - spot * N(-d1)) / spot


def settle(entry_px: float, exit_px: float, put_cost_pct: float) -> tuple[float, float]:
    """纯函数。(现货收益, 带保护的收益);put_cost_pct 是 % 现货。"""
    r = exit_px / entry_px - 1.0
    return r, r + max(0.0, STRIKE - exit_px / entry_px) - put_cost_pct / 100.0


async def run_once(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.style.header import _read_all
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    rows = await _read_all("feature_matrix_daily", {"select": "d,f", "d": "gte.2021-01-01", "order": "d.asc"})
    ds, X = matrix(rows)
    if not ds:
        return {"ok": False, "refused": True, "why": "feature_matrix_daily 没有 13 个特征齐全的日子"}
    model = fit(ds, X)
    if model["align_worst"] > MAX_ALIGN_DIST:
        return {"ok": False, "refused": True, "why": f"重拟合的类对不上 T-257 的中心(最差距离 {model['align_worst']:.2f} > {MAX_ALIGN_DIST})"}
    d, x = ds[-1], X[-1]
    state, dist = assign(model, x)
    w = await supabase_upsert_table(STATE_TABLE, [{"d": d, "state": state, "dist": round(dist, 4),
                                                   "features": dict(zip(FEATURES, [round(v, 6) for v in x])), "code_ref": CODE_REF}],
                                    on_conflict="d")
    if not w:
        return {"ok": False, "why": f"写 {STATE_TABLE} 失败"}
    px = await _read_all("perp_bv_daily", {"select": "d,c", "pair": "eq.BTCUSDT", "d": f"gte.{(dt.date.fromisoformat(d) - dt.timedelta(days=45)).isoformat()}",
                                           "order": "d.asc"})
    close = {str(r["d"])[:10]: float(r["c"]) for r in px if r.get("c")}
    tickets = await _read_all(TICKET_TABLE, {"select": ",".join(WRITES_COLUMNS[TICKET_TABLE]), "status": "eq.open"})   # 全列 —— upsert 不能把没读的列写成 null
    changed = []
    for t in tickets:                                                     # 到期结算
        exp = str(t["expiry_d"])[:10]
        if exp in close:
            rs, rp = settle(float(t["entry_px"]), close[exp], float(t["put_cost_pct"]))
            changed.append({**t, "status": "closed", "exit_px": close[exp], "ret_spot": round(rs, 6), "ret_protected": round(rp, 6),
                            "code_ref": CODE_REF})
    opened = None
    still_open = [t for t in tickets if t["ticket_id"] not in {c["ticket_id"] for c in changed}]
    if state == TARGET_STATE and not still_open and d in close:
        op = await _read_all("options_surface_daily", {"select": "put90_30d_cost_pct", "currency": "eq.BTC", "d": f"eq.{d}", "limit": "1"})
        cost, src = (float(op[0]["put90_30d_cost_pct"]), "deribit") if op and op[0].get("put90_30d_cost_pct") is not None else (None, None)
        if cost is None:
            dv = await _read_all("deriv_vol_daily", {"select": "dvol_close", "currency": "eq.BTC", "d": f"lte.{d}", "order": "d.desc", "limit": "1"})
            if dv:
                cost, src = round(bs_put(1.0, STRIKE, HOLD_DAYS, float(dv[0]["dvol_close"]) / 100.0) * 100, 4), "bs_dvol"
        if cost is not None:
            opened = {"ticket_id": f"S5A6:{d}", "state": state, "entry_d": d, "entry_px": close[d], "strike": round(STRIKE * close[d], 2),
                      "put_cost_pct": cost, "put_source": src,
                      "expiry_d": (dt.date.fromisoformat(d) + dt.timedelta(days=HOLD_DAYS)).isoformat(), "status": "open",
                      "exit_px": None, "ret_spot": None, "ret_protected": None, "code_ref": CODE_REF}
            changed.append(opened)
    if changed:
        w = await supabase_upsert_table(TICKET_TABLE, [{k: c.get(k) for k in WRITES_COLUMNS[TICKET_TABLE]} for c in changed],
                                        on_conflict="ticket_id")
        if not w:
            return {"ok": False, "why": f"写 {TICKET_TABLE} 失败"}
    return {"ok": True, "d": d, "state": state, "dist": round(dist, 3), "align_worst": round(model["align_worst"], 3),
            "opened": bool(opened), "closed": sum(1 for c in changed if c.get("status") == "closed"),
            "why": f"{d}:S{state}(距中心 {dist:.2f})" + (f" · 开 S5 保护性多头票(看跌 {opened['put_cost_pct']}% · {opened['put_source']})" if opened else "")}
