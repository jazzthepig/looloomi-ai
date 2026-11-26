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
循环痕迹:`loop_attempt` 里的 `_asset_flow_forecast`(视图每真刷新一次记一条,11-26 起)。

## 11-26 修(S-922):上线 19 天 0 行

- 找周一用的是 `asset_flow_daily` 按日期倒序**前 8 行** —— 那张表每天 35 个币,8 行全是同一天,
  只有那天本身是周一才找得到;而视图在周二才刷出周一那天,所以**永远找不到**。现在按日历从最新一天往回推周一,
  再确认那天有向量。
- 训练统计 RPC 要 ~17 秒,走的是 10 秒的共用客户端 —— 超时还会给熔断器记一次失败。现在给它单独的超时。
- 漏掉的周一(前向起点之后、还没写的)按同一规则补写,每次最多 `MAX_CATCHUP` 个;
  **写入时已经晚于周一 + `ON_TIME_DAYS` 天的,`code_ref` 带 `late-written <日期>`**,`created_at` 也留着 ——
  读前向证据的人可以把它们分开(补写用的是今天视图里那天的向量,上游若有回补会与当天看到的不同)。
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
LOOP_NAME = "_asset_flow_forecast"
RIDGE_TIMEOUT_S = 60.0      # 11-26 实测 asset_flow_ridge_stats 16.9 s(39.9 万行);service_role 的 statement_timeout 是 30 s
MAX_CATCHUP = 4             # 一次最多补写几个周一(每个 ~17 s)
ON_TIME_DAYS = 2            # 周一那天的向量周二才刷出来;写入日 ≤ 周一 + 2 天算按时


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


def forecast_rows(rows: list[dict], b0: float, beta: np.ndarray, d: str, n_train: int, code_ref: str = CODE_REF) -> list[dict]:
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
             "n_train": int(n_train), "x30": None, "code_ref": code_ref, "settled_at": None}
            for (s, _), p, rk in zip(xs, preds, ranks)]


def mondays_due(latest: Optional[str], have: set[str], start: dt.date = FORWARD_FROM) -> list[str]:
    """纯函数。从前向起点到「最新一天及之前最近的周一」之间,还没写过的周一(升序)。

    11-26 之前用的是「最新 8 行里的周一」—— 每天 35 行的表,8 行是同一天(S-922)。按日历推,不按行数。"""
    if not latest:
        return []
    x = dt.date.fromisoformat(str(latest)[:10])
    last = x - dt.timedelta(days=x.weekday())
    first = start + dt.timedelta(days=(7 - start.weekday()) % 7)
    out, m = [], first
    while m <= last:
        if m.isoformat() not in have:
            out.append(m.isoformat())
        m += dt.timedelta(days=7)
    return out


def code_ref_for(t: str, now: dt.datetime) -> str:
    """纯函数。晚于周一 + ON_TIME_DAYS 天才写的,在 code_ref 里标出来(前向证据要能把补写的分开)。"""
    late = (now.date() - dt.date.fromisoformat(t[:10])).days > ON_TIME_DAYS
    return f"{CODE_REF} · late-written {now.date().isoformat()}" if late else CODE_REF


async def _forecast_one(t: str, now: dt.datetime) -> dict[str, Any]:
    """一个周一:截到 t − 30 天的训练统计 → 当天截面的预测 → 落表。"""
    from src.api.store import supabase_rpc_write, supabase_upsert_table
    from src.data.style.header import _read_all
    cut = (dt.date.fromisoformat(t) - dt.timedelta(days=30)).isoformat()
    # 只读的函数,走写入那条通路只是为了单独的超时(共用客户端 10 s,超时还记熔断失败);写不了的副本本来也不该写预测
    r = await supabase_rpc_write("asset_flow_ridge_stats", {"p_cut": cut}, timeout=RIDGE_TIMEOUT_S)
    st = r.value if r.ok else None
    if isinstance(st, list) and st:
        st = st[0]
    if isinstance(st, dict) and "asset_flow_ridge_stats" in st and len(st) == 1:
        st = st["asset_flow_ridge_stats"]
    if not isinstance(st, dict) or not st.get("n"):
        return {"ok": False, "d": t, "why": f"asset_flow_ridge_stats({cut}) 没有返回训练统计({(r.why or '')[:120]})"}
    b0, beta = ridge_from_stats(st)
    today_rows = await _read_all("asset_flow_daily", {"select": "symbol,vec", "d": f"eq.{t}", "vec": "not.is.null", "order": "symbol.asc"})
    ref = code_ref_for(t, now)
    rows = forecast_rows(today_rows or [], b0, beta, t, int(st["n"]), ref)
    if not rows:
        return {"ok": False, "d": t, "why": f"{t} 当天 asset_flow_daily 没有向量"}
    if not await supabase_upsert_table(TABLE, rows, on_conflict="d,symbol,model"):
        return {"ok": False, "d": t, "why": f"{t} 预测写入失败({len(rows)} 行)"}
    return {"ok": True, "d": t, "n": len(rows), "n_train": int(st["n"]), "late": ref != CODE_REF}


async def run_once(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
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
    # 2. 预测:前向起点之后、最新一天及之前的每个周一,还没写过的按时间顺序补(S-922:按日历推周一,不按行数)
    rd = await _sb_get("asset_flow_daily", {"select": "d", "vec": "not.is.null", "order": "d.desc", "limit": "1"})
    latest = (rd.rows or [{}])[0].get("d") if rd.ok and rd.rows else None
    if not latest:
        return {"ok": False, **out, "why": f"asset_flow_daily 读不到最新一天({getattr(rd, 'reason', '')});结算 {settled}"}
    hv = await _read_all(TABLE, {"select": "d", "model": f"eq.{MODEL}", "d": f"gte.{FORWARD_FROM.isoformat()}", "order": "d.asc"})
    due_mons = mondays_due(str(latest), {str(r["d"])[:10] for r in hv or []})
    if not due_mons:
        return {"ok": True, **out, "latest": latest, "why": f"周一都已预测(最新一天 {latest});结算 {settled}"}
    done, fails = [], []
    for t in due_mons[:MAX_CATCHUP]:
        r = await _forecast_one(t, now)
        (done if r.get("ok") else fails).append(r)
        if not r.get("ok"):
            break                                          # 按时间顺序补:前一个没写成就不跳过去写后一个
    left = len(due_mons) - len(done)
    out.update({"latest": latest, "written": [r["d"] for r in done], "late": [r["d"] for r in done if r.get("late")],
                "n": sum(r["n"] for r in done), "pending": left})
    if done:
        out["forecast_d"] = done[-1]["d"]
    parts = [f"{r['d']} 预测 {r['n']} 个币(训练 {r['n_train']} 行{',补写' if r.get('late') else ''})" for r in done]
    if fails:
        parts.append(f"失败:{fails[0]['why']}")
    if left and not fails:
        parts.append(f"还有 {left} 个周一下一轮补")
    return {"ok": not fails, **out, "why": f"{';'.join(parts)};结算 {settled}"}
