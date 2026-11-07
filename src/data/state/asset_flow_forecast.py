"""S-774 R 臂 ✅ 的前向记录(11-07):每个周一用 `asset_flow_daily` 的 11 维做 Ridge 预测,之后补上真实的 30 天超额。

## 口径(lane-c `docs/research/t293_asset_flow.py` R 臂原样)

- 训练集 = d' < t − 30 天、vec 与 x30 都有的全部 (币, 日);sklearn `Ridge(alpha=10)`(带截距,截距不进惩罚),输入就是 vec
  (11 维截面百分位居中到 [−1, 1]),目标 x30。这里不搬 23 万行:库里 `asset_flow_ridge_stats(cut)` 一次给出 n / Σx / Σy / Σxx / Σxy,
  居中后解 (XcᵀXc + αI)β = Xcᵀyc,截距 = ȳ − x̄ᵀβ —— 与 sklearn 同一个解(tests 对过)。
- 预测 = 周一 t 当天有 vec 的每个币;`pct` = 当天截面里的百分位(越高 = 预测越好)。
- 结算 = 到期后从同一张视图读 x30(d+1 开盘 → d+30 收盘,减当天截面等权)。
- cohort:t ≥ `FORWARD_FROM`(S-774 的数据到 2026-11-06)= forward;更早的不写(历史走步是研究,不是前向证据)。

**只描述,不进敞口。** 「最低五分位不进多头书」要另立预注册;S-776 先判力量来自「因」还是价格相位。
判活:`select d, count(*), count(x30) from asset_flow_forecast_daily group by 1 order by 1 desc`。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

import numpy as np

TABLE = "asset_flow_forecast_daily"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("d", "symbol", "model", "pred", "pct", "n_train", "x30", "code_ref", "settled_at")}
MODEL = "ridge11_a10"
ALPHA = 10.0
CODE_REF = "asset_flow_forecast v1 (11-07, S-774 R / T-293)"
FORWARD_FROM = dt.date(2026, 11, 9)
DIM = 11


def ridge_from_stats(st: dict, alpha: float = ALPHA) -> tuple[float, np.ndarray]:
    """纯函数。充分统计量 → (截距, β)。与带截距的 sklearn Ridge 同一个解。"""
    n = float(st["n"])
    sx = np.asarray(st["sx"], dtype=float)
    sxy = np.asarray(st["sxy"], dtype=float)
    up = np.asarray(st["sxx_upper"], dtype=float)
    sxx = np.zeros((DIM, DIM))
    k = 0
    for i in range(DIM):
        for j in range(i, DIM):
            sxx[i, j] = sxx[j, i] = up[k]
            k += 1
    xbar, ybar = sx / n, float(st["sy"]) / n
    cxx = sxx - n * np.outer(xbar, xbar)
    cxy = sxy - n * xbar * ybar
    beta = np.linalg.solve(cxx + alpha * np.eye(DIM), cxy)
    return float(ybar - xbar @ beta), beta


def parse_vec(v: Any) -> Optional[np.ndarray]:
    if v is None:
        return None
    if isinstance(v, str):
        v = [float(x) for x in v.strip("[]").split(",") if x.strip()]
    a = np.asarray(v, dtype=float)
    return a if a.shape == (DIM,) else None


def forecast_rows(rows: list[dict], b0: float, beta: np.ndarray, d: str, n_train: int) -> list[dict]:
    """纯函数。当天截面 → 预测行(百分位 = 秩 / (n − 1),并列取平均)。"""
    xs = [(r["symbol"], parse_vec(r.get("vec"))) for r in rows]
    xs = [(s, v) for s, v in xs if v is not None]
    if not xs:
        return []
    preds = np.array([b0 + v @ beta for _, v in xs])
    order = preds.argsort(kind="stable")
    ranks = np.empty(len(preds))
    ranks[order] = np.arange(len(preds))
    for val in np.unique(preds):                       # 并列取平均秩
        m = preds == val
        if m.sum() > 1:
            ranks[m] = ranks[m].mean()
    denom = max(len(preds) - 1, 1)
    return [{"d": d, "symbol": s, "model": MODEL, "pred": round(float(p), 6), "pct": round(float(rk / denom), 4),
             "n_train": int(n_train), "x30": None, "code_ref": CODE_REF, "settled_at": None}
            for (s, _), p, rk in zip(xs, preds, ranks)]


def latest_monday(days: list[str]) -> Optional[str]:
    """纯函数。日期里最近的一个周一。"""
    mons = [d for d in days if dt.date.fromisoformat(d[:10]).weekday() == 0]
    return max(mons)[:10] if mons else None


async def run_once(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    from src.api.store import supabase_rpc, supabase_upsert_table
    from src.data.style.header import _read_all
    from src.data.vector.market_state_writer import _sb_get
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    out: dict[str, Any] = {}
    # 1. 结算:到期的旧预测补 x30
    pend = await _read_all(TABLE, {"select": "d,symbol,model", "x30": "is.null", "order": "d.asc,symbol.asc"})
    due = sorted({r["d"] for r in pend or [] if (now.date() - dt.date.fromisoformat(str(r["d"])[:10])).days > 31})
    settled = 0
    for d in due:
        xs = await _read_all("asset_flow_daily", {"select": "symbol,x30", "d": f"eq.{d}", "x30": "not.is.null", "order": "symbol.asc"})
        xmap = {x["symbol"]: x["x30"] for x in xs or []}
        upd = [{"d": d, "symbol": r["symbol"], "model": r["model"], "x30": xmap[r["symbol"]],
                "settled_at": now.isoformat()} for r in pend if r["d"] == d and r["symbol"] in xmap]
        if upd and await supabase_upsert_table(TABLE, upd, on_conflict="d,symbol,model"):
            settled += len(upd)
    out["settled"] = settled
    # 2. 预测:最近一个周一(且在前向起点之后)还没写过
    rd = await _sb_get("asset_flow_daily", {"select": "d", "vec": "not.is.null", "order": "d.desc", "limit": "8"})
    t = latest_monday([r["d"] for r in (rd.rows or [])]) if rd.ok else None
    if not t or dt.date.fromisoformat(t) < FORWARD_FROM:
        return {"ok": True, **out, "why": f"没有新的周一可预测(最近的周一 {t},前向从 {FORWARD_FROM});结算 {settled}"}
    have = await _sb_get(TABLE, {"select": "d", "d": f"eq.{t}", "model": f"eq.{MODEL}", "limit": "1"})
    if have.ok and have.rows:
        return {"ok": True, **out, "why": f"{t} 已预测;结算 {settled}"}
    cut = (dt.date.fromisoformat(t) - dt.timedelta(days=30)).isoformat()
    st = await supabase_rpc("asset_flow_ridge_stats", {"p_cut": cut})
    if not isinstance(st, dict) or not st.get("n"):
        return {"ok": False, **out, "why": f"asset_flow_ridge_stats({cut}) 没有返回训练统计"}
    b0, beta = ridge_from_stats(st)
    today_rows = await _read_all("asset_flow_daily", {"select": "symbol,vec", "d": f"eq.{t}", "vec": "not.is.null", "order": "symbol.asc"})
    rows = forecast_rows(today_rows or [], b0, beta, t, int(st["n"]))
    if not rows or not await supabase_upsert_table(TABLE, rows, on_conflict="d,symbol,model"):
        return {"ok": False, **out, "why": f"{t} 预测写入失败({len(rows)} 行)"}
    return {"ok": True, **out, "forecast_d": t, "n": len(rows), "n_train": int(st["n"]),
            "why": f"{t} 预测 {len(rows)} 个币(训练 {int(st['n'])} 行,截到 {cut});结算 {settled}"}
