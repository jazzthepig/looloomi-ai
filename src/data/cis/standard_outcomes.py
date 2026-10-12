"""每个 (名字, 日) 在正式序列上的 30 日结果 —— 档位历史表现(track record / edge map)只从这里算(S-540)。

## 为什么

S-539 之后,页面上的分数、等级、档位都是正式日终序列;但「这一档历史上表现怎样」的两个面 ——
`/api/v1/signals/track-record`(按档 × 等级)与 `/api/v1/signals/edge-map`(按档 × 风险带)—— 还是用
实时引擎的 `cis_scores` 与旧的 `signal_outcomes` 算的:同一个 OUTPERFORM,资产页旁边的历史记录(归因,正式序列)
和档位表现页(旧序列)是两套数。

## 做法

正式序列 = 已发布(cis_official_daily)优先,之前用同标准按时点重建(cis_rebuild_daily 当前版本)。
每个 (名字, d):d 收盘 → d+30 收盘的收益(与标准同一份收盘:加密 CG 日收盘、传统资产 EODHD 复权),
基准 BTC(加密)/ SPY(传统资产),基准过去 30 日涨跌(风险带),同日加密等权面板的前后 30 日。
落表 `cis_standard_outcomes`;两个 RPC(`refresh_signal_track_record` / `refresh_signal_edge_map`)改为从这张表聚合。
每行带 provenance(published / reconstructed)。
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

import pandas as pd

TABLE = "cis_standard_outcomes"
WRITES_TABLES = (TABLE,)
HORIZON = 30
COLUMNS = ("symbol", "d", "asset_class", "grp", "signal", "grade", "provenance", "bench", "a_ret", "b_ret", "alpha",
           "bench_trail_30d", "panel_fwd_30d", "panel_trail_30d", "computed_at")


def _ret(s: pd.Series, a: pd.Timestamp, b: pd.Timestamp) -> Optional[float]:
    x, y = s.get(a), s.get(b)
    if x is None or y is None or pd.isna(x) or pd.isna(y) or x <= 0:
        return None
    return float(y / x - 1)


def outcome_rows(points: Mapping[str, list[dict]], closes: Mapping[str, pd.Series], classes: Mapping[str, str],
                 tradfi: frozenset, last_close: pd.Timestamp) -> list[dict]:
    """纯函数。points:{symbol: [{d, signal, grade, provenance}]};closes:{symbol: 日收盘(传统资产已向前填 ≤ 4 天)}。
    只出 d + 30 ≤ last_close 的行(结果已到期)。收益是比例(0.05 = 5%)。"""
    now = datetime.now(timezone.utc).isoformat()
    h = pd.Timedelta(days=HORIZON)
    crypto = [s for s in closes if classes.get(s) not in tradfi]
    panel_f, panel_t = {}, {}
    for sym in crypto:
        px = closes[sym]
        if not len(px):
            continue
        f = px.shift(-HORIZON, freq="D").reindex(px.index) / px - 1
        t = px / px.shift(HORIZON, freq="D").reindex(px.index) - 1
        for d, v in f.dropna().items():
            panel_f.setdefault(d, []).append(float(v))
        for d, v in t.dropna().items():
            panel_t.setdefault(d, []).append(float(v))
    pf = {d: sum(v) / len(v) for d, v in panel_f.items() if len(v) >= 10}
    pt = {d: sum(v) / len(v) for d, v in panel_t.items() if len(v) >= 10}
    out = []
    for sym, pts in points.items():
        px = closes.get(sym)
        if px is None or not len(px):
            continue
        cls = classes.get(sym)
        is_tf = cls in tradfi
        bench = "SPY" if is_tf else "BTC"
        bpx = closes.get(bench)
        for p in pts:
            d = pd.Timestamp(p["d"])
            if d + h > last_close or not p.get("signal"):
                continue
            a = _ret(px, d, d + h)
            b = _ret(bpx, d, d + h) if bpx is not None else None
            bt = _ret(bpx, d - h, d) if bpx is not None else None
            if a is None:
                continue
            row = {"symbol": sym, "d": str(p["d"])[:10], "asset_class": cls, "grp": "tradfi" if is_tf else "crypto",
                   "signal": p["signal"], "grade": p.get("grade"), "provenance": p.get("provenance"), "bench": bench,
                   "a_ret": a, "b_ret": b, "alpha": (a - b) if b is not None else None, "bench_trail_30d": bt,
                   "panel_fwd_30d": None if is_tf else pf.get(d), "panel_trail_30d": None if is_tf else pt.get(d),
                   "computed_at": now}
            for k, v in list(row.items()):
                if isinstance(v, float):
                    row[k] = round(v, 6) if math.isfinite(v) else None
            out.append({c: row.get(c) for c in COLUMNS})
    return out


async def run_once() -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.cis.official import standard_history
    from src.data.cis.rebuild import START, TRADFI, load_inputs
    end = pd.Timestamp(datetime.now(timezone.utc).date())
    assets, data = await load_inputs(end)
    syms = list(assets)
    days = (end - START).days + 1
    hist = await standard_history(syms, days)
    if not any(hist.values()):
        return {"ok": False, "refused": True, "written": 0, "reason": "正式序列读到 0 行"}
    closes: dict[str, pd.Series] = {}
    for sym, c in data["crypto"].items():
        closes[sym] = c[0].dropna()
    for sym, t in data["tradfi"].items():
        s = t[0].dropna()
        if len(s):
            s = s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="D")).ffill(limit=4)
        closes[sym] = s
    last_close = max((s.index.max() for s in closes.values() if len(s)), default=end)
    classes = {k: v["class"] for k, v in assets.items()}
    points = {s: [{"d": p["d"], "signal": p.get("signal"), "grade": p.get("grade"), "provenance": p.get("provenance")}
                  for p in pts] for s, pts in hist.items()}
    rows = outcome_rows(points, closes, classes, TRADFI, last_close)
    for i in range(0, len(rows), 1000):
        res = await supabase_upsert_table(TABLE, rows[i:i + 1000], on_conflict="symbol,d")
        if not res.ok:
            return {"ok": False, "refused": False, "written": i, "reason": f"写入失败:{res.why}"}
    pub = sum(1 for r in rows if r["provenance"] == "published")
    return {"ok": True, "refused": False, "written": len(rows), "published": pub,
            "reason": f"{len(rows)} 个 (名字, 日) 的 30 日结果(其中已发布 {pub})"}
