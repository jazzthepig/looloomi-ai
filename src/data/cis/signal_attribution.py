"""每个 CIS 信号的归因 —— 为什么出、出了之后怎样(T-078 / S-529)。

## 为什么

Jazz 10-09:「是根据过往表现展示,并非预测。然后我们需要给他们每个信号都归因。」
S-527:标 OUTPERFORM 的名字 17 个月跑输同类 —— 一个信号如果不说清「它是被什么推出来的」和
「之后发生了什么、多少是市场、多少是它自己」,读者只能把它当预测读。机构要归因,我们也要。

## 信号 = 一次变化

某个名字的五档信号在 UTC 日 d 与它上一个有记录日不同。首次出现不算(没有「之前」)。

## 归因两半

- **驱动**:五个支柱在 d 与上一个记录日之间的变化 × 该类别的基础权重(CIS_METHODOLOGY §4.1)= 贡献;
  分数实际变化 − 贡献之和 = 残差(状态权重调整、置信度折扣等,不硬分)。主驱动 = 贡献绝对值最大的支柱。
  另记出信号前 30 天的价格变化、相对同类的变化 —— 信号描述的是已经发生的事。
- **结果**:7 天、30 天;入场 = d 的收盘。自身收益 = 同类等权(加密 = 全部 CIS 加密名字;传统资产 = 同一类别)
  + 相对同类。加密另报 BTC、90 天 β(d 及以前)、β 调整后超额。没到期的不填数,标未到期。

价格源:加密 binance_hist,传统资产 eodhd(都在 TRUSTED_RETURN_SOURCES 里)。读不到价的信号照记驱动,结果为空。

## 判活判据(规则 5b ②)

    select max(d) from cis_signal_attribution;   -- ≥ 最近一次信号变化的日期
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

TABLE = "cis_signal_attribution"
WRITES_TABLES = (TABLE,)
CODE_REF = "T-078 signal attribution v1"
#: S-534 / T-080:一张表两条序列(主键 symbol, d, series)。
#: standard = 统一标准日终序列(cis_rebuild_daily 同版本的按时点重建 + cis_official_daily 的已发布,已发布优先)—— 对外默认;
#: live_mixed = 10-10 及以前实际对外发布的实时信号(v_cis_signal_daily),冻结在 LEGACY_END,只让结果到期。
SERIES_STANDARD, SERIES_LEGACY = "standard", "live_mixed"
LEGACY_END = "2026-10-10"
STANDARD_START = "2023-01-01"
HORIZONS = (7, 30)
BETA_DAYS, BETA_MIN = 90, 60
MA_DAYS = 50
START = "2025-05-01"
PILLARS = ("F", "M", "O", "S", "A")
CRYPTO_CLASSES = frozenset({"Crypto", "DeFi", "Gaming", "Infrastructure", "L1", "L2", "Memecoin", "RWA"})
STABLES = frozenset({"USDT", "USDC", "DAI", "FDUSD", "USDE", "TUSD", "PYUSD", "USDS", "USD1"})

#: CIS_METHODOLOGY §4.1 基础权重。表里没有的类别用 DEFAULT(与 L1 相同)—— 归因里标明用的是哪一套。
BASE_WEIGHTS: dict[str, dict[str, float]] = {
    "L1": {"F": .30, "M": .25, "O": .20, "S": .15, "A": .10},
    "L2": {"F": .30, "M": .25, "O": .20, "S": .15, "A": .10},
    "DeFi": {"F": .25, "M": .25, "O": .25, "S": .15, "A": .10},
    "RWA": {"F": .35, "M": .20, "O": .20, "S": .15, "A": .10},
    "Infrastructure": {"F": .30, "M": .20, "O": .25, "S": .10, "A": .15},
    "Memecoin": {"F": .15, "M": .35, "O": .15, "S": .25, "A": .10},
    "US Equity": {"F": .30, "M": .25, "O": .10, "S": .20, "A": .15},
    "US Bond": {"F": .30, "M": .20, "O": .10, "S": .20, "A": .20},
    "Commodity": {"F": .25, "M": .25, "O": .10, "S": .20, "A": .20},
}
DEFAULT_WEIGHTS = {"F": .30, "M": .25, "O": .20, "S": .15, "A": .10}

#: 表的全部列 —— 每行补齐(PostgREST 批量写要求每个对象同一组键)。
COLUMNS = ("symbol", "d", "series", "asset_class", "grp", "provenance", "pct", "prev_pct", "signal", "prev_signal", "prev_d", "score", "prev_score", "grade",
           "d_score", "contrib", "contrib_residual", "top_driver", "weights", "pre30_ret", "pre30_rel", "beta_btc",
           "btc_below_ma50", "matured_7", "ret_7", "univ_7", "rel_7", "btc_7", "alpha_7",
           "matured_30", "ret_30", "univ_30", "rel_30", "btc_30", "alpha_30",
           "next_d", "next_signal", "held_days", "reverted_3d", "note", "code_ref", "computed_at")
WHIPSAW_DAYS = 3


def group_of(asset_class: Optional[str]) -> str:
    """纯函数。加密全体是一个同类组;传统资产按类别分组。"""
    c = (asset_class or "").strip()
    return "crypto" if c in CRYPTO_CLASSES else f"tradfi:{c or 'unknown'}"


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def find_events(rows: list[dict]) -> list[dict]:
    """纯函数。rows:每个名字每个 UTC 日一条(v_cis_signal_daily)。返回信号变化事件,带上一个记录日的值。"""
    by_sym: dict[str, list[dict]] = {}
    for r in rows or []:
        if r.get("symbol") and r.get("d") and r.get("signal"):
            by_sym.setdefault(r["symbol"], []).append(r)
    out = []
    for sym, rs in by_sym.items():
        rs = sorted(rs, key=lambda r: r["d"])
        for prev, cur in zip(rs, rs[1:]):
            if cur["signal"] != prev["signal"]:
                out.append({"symbol": sym, "cur": cur, "prev": prev})
    return sorted(out, key=lambda e: (e["cur"]["d"], e["symbol"]))


def drivers(cur: Mapping[str, Any], prev: Mapping[str, Any]) -> dict[str, Any]:
    """纯函数。支柱变化 × 基础权重 = 贡献;残差 = 分数变化 − 贡献之和。缺支柱的不算贡献(不补 0),残差照算。"""
    cls = cur.get("asset_class") or ""
    w = BASE_WEIGHTS.get(cls, DEFAULT_WEIGHTS)
    contrib: dict[str, Optional[float]] = {}
    for p in PILLARS:
        a, b = _f(cur.get(f"pillar_{p.lower()}")), _f(prev.get(f"pillar_{p.lower()}"))
        contrib[p] = round(w[p] * (a - b), 3) if a is not None and b is not None else None
    s1, s0 = _f(cur.get("score")), _f(prev.get("score"))
    d_score = round(s1 - s0, 3) if s1 is not None and s0 is not None else None
    known = [v for v in contrib.values() if v is not None]
    residual = round(d_score - sum(known), 3) if d_score is not None and known else None
    top = max((p for p in PILLARS if contrib[p] is not None), key=lambda p: abs(contrib[p]), default=None)
    return {"d_score": d_score, "contrib": contrib, "contrib_residual": residual, "top_driver": top,
            "weights": "base:" + (cls if cls in BASE_WEIGHTS else "default")}


def ew_index(px: pd.DataFrame) -> pd.Series:
    """纯函数。每日再平衡的等权篮子:当天有收益的名字取平均,累乘成指数。"""
    r = px.pct_change(fill_method=None)
    return (1 + r.mean(axis=1, skipna=True).fillna(0.0)).cumprod()


def _ret(s: pd.Series, a: pd.Timestamp, b: pd.Timestamp) -> Optional[float]:
    if a not in s.index or b not in s.index:
        return None
    x0, x1 = s.at[a], s.at[b]
    if pd.isna(x0) or pd.isna(x1) or x0 <= 0:
        return None
    return float(x1 / x0 - 1)


def beta_at(asset: pd.Series, bench: pd.Series, d: pd.Timestamp) -> Optional[float]:
    """纯函数。d 及以前 BETA_DAYS 天的日对数收益回归斜率;观测 < BETA_MIN ⇒ None。"""
    la = np.log(asset / asset.shift(1))
    lb = np.log(bench / bench.shift(1))
    win = pd.concat([la, lb], axis=1).loc[:d].tail(BETA_DAYS).dropna()
    if len(win) < BETA_MIN or float(win.iloc[:, 1].var()) == 0:
        return None
    return float(win.iloc[:, 0].cov(win.iloc[:, 1]) / win.iloc[:, 1].var())


def outcomes(sym: str, d: pd.Timestamp, px: pd.DataFrame, idx: pd.Series, btc: Optional[pd.Series],
             last: pd.Timestamp) -> dict[str, Any]:
    """纯函数。px:同组价格(日 × 名字);idx:同组等权指数;btc:加密才给。last:价格最后一天。"""
    out: dict[str, Any] = {}
    s = px[sym] if sym in px.columns else None
    if s is None or d not in s.index or pd.isna(s.get(d)):
        out["note"] = "信号日没有收盘价 —— 只记驱动"
        return out
    pre = d - pd.Timedelta(days=30)
    r_pre, u_pre = _ret(s, pre, d), _ret(idx, pre, d)
    out["pre30_ret"] = r_pre
    out["pre30_rel"] = r_pre - u_pre if r_pre is not None and u_pre is not None else None
    beta = beta_at(s, btc, d) if btc is not None else None
    out["beta_btc"] = beta
    if btc is not None:
        ma = btc.loc[:d].tail(MA_DAYS)
        out["btc_below_ma50"] = bool(btc.get(d) < ma.mean()) if len(ma.dropna()) == MA_DAYS and pd.notna(btc.get(d)) else None
    for h in HORIZONS:
        e = d + pd.Timedelta(days=h)
        out[f"matured_{h}"] = bool(e <= last)
        if e > last:
            continue
        r, u = _ret(s, d, e), _ret(idx, d, e)
        out[f"ret_{h}"] = r
        out[f"univ_{h}"] = u
        out[f"rel_{h}"] = r - u if r is not None and u is not None else None
        if btc is not None:
            b = _ret(btc, d, e)
            out[f"btc_{h}"] = b
            out[f"alpha_{h}"] = r - beta * b if r is not None and b is not None and beta is not None else None
    return out


def persistence(events: list[dict], last_day: str) -> dict[tuple[str, str], dict[str, Any]]:
    """纯函数。每次变化维持了多久:下一次变化的日期与档位;没有下一次 ⇒ 维持到 last_day(仍是当前档)。
    reverted_3d = 下一次变化在 WHIPSAW_DAYS 天内、且变回了原档 —— 边界来回跳。**事后才知道**,只用于归因与描述。"""
    by_sym: dict[str, list[dict]] = {}
    for ev in events:
        by_sym.setdefault(ev["symbol"], []).append(ev)
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for sym, evs in by_sym.items():
        evs = sorted(evs, key=lambda e: e["cur"]["d"])
        for i, ev in enumerate(evs):
            d = str(ev["cur"]["d"])[:10]
            nxt = evs[i + 1] if i + 1 < len(evs) else None
            if nxt is None:
                held = (pd.Timestamp(last_day) - pd.Timestamp(d)).days
                out[(sym, d)] = {"next_d": None, "next_signal": None, "held_days": held, "reverted_3d": None if held < WHIPSAW_DAYS else False}
                continue
            nd = str(nxt["cur"]["d"])[:10]
            held = (pd.Timestamp(nd) - pd.Timestamp(d)).days
            out[(sym, d)] = {"next_d": nd, "next_signal": nxt["cur"]["signal"], "held_days": held,
                             "reverted_3d": bool(held <= WHIPSAW_DAYS and nxt["cur"]["signal"] == ev["prev"]["signal"])}
    return out


def build_rows(events: list[dict], groups: Mapping[str, tuple[pd.DataFrame, pd.Series]],
               btc: Optional[pd.Series], last_day: Optional[str] = None, series: str = SERIES_LEGACY) -> list[dict]:
    """纯函数。groups:组名 → (价格, 等权指数)。last_day:信号数据的最后一天(算「仍是当前档」维持了几天)。"""
    now = datetime.now(timezone.utc).isoformat()
    last_day = last_day or max((str(e["cur"]["d"])[:10] for e in events), default=None)
    pers = persistence(events, last_day) if last_day else {}
    rows = []
    for ev in events:
        cur, prev = ev["cur"], ev["prev"]
        g = group_of(cur.get("asset_class"))
        d = pd.Timestamp(cur["d"])
        row: dict[str, Any] = {
            "symbol": ev["symbol"], "d": str(cur["d"])[:10], "series": series, "asset_class": cur.get("asset_class"), "grp": g,
            "pct": _f(cur.get("pct")), "prev_pct": _f(prev.get("pct")),
            "signal": cur["signal"], "prev_signal": prev["signal"], "prev_d": str(prev["d"])[:10],
            "score": _f(cur.get("score")), "prev_score": _f(prev.get("score")), "grade": cur.get("grade"),
            "provenance": provenance_of(cur.get("source")),
            **drivers(cur, prev), **pers.get((ev["symbol"], str(cur["d"])[:10]), {}),
            "code_ref": CODE_REF, "computed_at": now}
        if g in groups:
            px, idx = groups[g]
            last = px.dropna(how="all").index.max()
            row.update(outcomes(ev["symbol"], d, px, idx, btc if g == "crypto" else None, last))
        else:
            row["note"] = "这个组没有价格源 —— 只记驱动"
        for k, v in list(row.items()):
            if isinstance(v, float):
                row[k] = round(v, 6) if math.isfinite(v) else None
        rows.append({c: row.get(c) for c in COLUMNS})
    return rows


def provenance_of(source: Optional[str]) -> str:
    """纯函数。信号日那条记录的来源 → live / reconstructed。事后重建(historical_reconstruction、按时点重建 cis_rebuild)
    不是当时发布的信号。"""
    return "reconstructed" if (source or "") in ("historical_reconstruction", "cis_rebuild") else "live"


def standard_series(rebuild: list[dict], official: list[dict]) -> list[dict]:
    """纯函数。统一标准序列:每个 (名字, 日) 一条,已发布(cis_official_daily)优先于按时点重建(cis_rebuild_daily)。
    两张表列名不同,这里统一成 find_events / drivers 读的形状(score = 状态调整分,档位按它的同组分位定)。"""
    out: dict[tuple[str, str], dict] = {}
    for r in rebuild or []:
        k = (r.get("symbol"), str(r.get("d"))[:10])
        out[k] = {"symbol": k[0], "d": k[1], "asset_class": r.get("asset_class"), "signal": r.get("signal_pct"),
                  "score": r.get("score"), "grade": r.get("grade"), "pct": r.get("pct"),
                  **{f"pillar_{p}": r.get(f"pillar_{p}") for p in "fmosa"}, "source": "cis_rebuild"}
    for r in official or []:
        k = (r.get("symbol"), str(r.get("d"))[:10])
        out[k] = {"symbol": k[0], "d": k[1], "asset_class": r.get("asset_class"), "signal": r.get("signal"),
                  "score": r.get("regime_adjusted_score"), "grade": r.get("grade"), "pct": r.get("pct"),
                  **{f"pillar_{p}": r.get(f"pillar_{p}") for p in "fmosa"}, "source": "official"}
    return sorted(out.values(), key=lambda r: (r["d"], r["symbol"] or ""))


def track_record(rows: list[dict]) -> dict[str, Any]:
    """纯函数。已到期的信号按 (组, 档) 汇总:次数、平均 / 中位相对同类、相对为正的占比;加密再按 BTC 是否在 50 日线下方拆。
    3 天内变回原档的(边界来回跳)单独报占比,不进结果统计 —— 那是标签噪声,不是一次信号。"""
    def agg(rs: list[dict], h: int) -> dict[str, Any]:
        xs = [r[f"rel_{h}"] for r in rs if r.get(f"rel_{h}") is not None]
        if not xs:
            return {"n": 0}
        a = np.array(xs, dtype=float)
        return {"n": int(len(a)), "mean_rel_pct": round(float(a.mean()) * 100, 2),
                "median_rel_pct": round(float(np.median(a)) * 100, 2), "share_rel_positive": round(float((a > 0).mean()), 3)}

    out: dict[str, Any] = {"excludes": "changes that reverted to the previous signal within 3 days (label noise at a grade boundary)"}
    for major in ("crypto", "tradfi"):
        rs = [r for r in rows if (r.get("grp") == "crypto") == (major == "crypto")]
        by_sig: dict[str, Any] = {}
        for sig in ("STRONG OUTPERFORM", "OUTPERFORM", "NEUTRAL", "UNDERPERFORM", "UNDERWEIGHT"):
            allc = [r for r in rs if r.get("signal") == sig]
            if not allc:
                continue
            ss = [r for r in allc if r.get("reverted_3d") is not True]
            known = [r for r in allc if r.get("reverted_3d") is not None]
            e: dict[str, Any] = {f"{h}d": agg(ss, h) for h in HORIZONS}
            e["changes"] = len(allc)
            e["reverted_within_3d_share"] = (round(sum(1 for r in known if r["reverted_3d"]) / len(known), 3)
                                             if known else None)
            if major == "crypto":
                e["btc_below_ma50"] = {f"{h}d": agg([r for r in ss if r.get("btc_below_ma50") is True], h) for h in HORIZONS}
                e["btc_above_ma50"] = {f"{h}d": agg([r for r in ss if r.get("btc_below_ma50") is False], h) for h in HORIZONS}
            by_sig[sig] = e
        out[major] = by_sig
    return out


async def _read_series(series: str) -> list[dict]:
    from src.data.style.header import _read_all
    if series == SERIES_LEGACY:
        sig = await _read_all("v_cis_signal_daily", {
            "select": "symbol,asset_class,d,signal,score,grade,pillar_f,pillar_m,pillar_o,pillar_s,pillar_a,source",
            "and": f"(d.gte.{START},d.lte.{LEGACY_END})", "order": "d.asc"})
        return [r for r in sig if r.get("symbol") not in STABLES]
    from src.data.cis.official import TABLE as OFFICIAL
    from src.data.cis.rebuild import CODE_REF as STD_REF, TABLE as REBUILD
    cols = "symbol,asset_class,d,score,grade,pct,pillar_f,pillar_m,pillar_o,pillar_s,pillar_a"
    reb = await _read_all(REBUILD, {"select": cols + ",signal_pct", "code_ref": f"eq.{STD_REF}",
                                    "d": f"gte.{STANDARD_START}", "order": "d.asc,symbol.asc"})
    off = await _read_all(OFFICIAL, {"select": cols.replace("score", "regime_adjusted_score") + ",signal",
                                     "order": "d.asc,symbol.asc"})
    return [r for r in standard_series(reb, off) if r.get("symbol") not in STABLES]


async def run_once(series: str = SERIES_STANDARD) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.market.panel_read import read_panel

    sig = await _read_series(series)
    if not sig:
        return {"ok": False, "refused": True, "written": 0, "reason": f"{series} 序列读到 0 行"}
    if series == SERIES_STANDARD:
        last = max(str(r["d"])[:10] for r in sig)
        lag = (datetime.now(timezone.utc).date() - date.fromisoformat(last)).days
        if lag > 3:
            # 重建正在全量重写(或停了):读到的是半截序列,算出来的换档会是假的 —— 不写
            return {"ok": False, "refused": True, "written": 0,
                    "reason": f"standard 序列最后一天 {last}(落后 {lag} 天)—— 重建没写完或停了,不归因"}
    evs = find_events(sig)
    cls_of = {r["symbol"]: r.get("asset_class") for r in sig}
    groups: dict[str, tuple[pd.DataFrame, pd.Series]] = {}
    btc = None
    by_grp: dict[str, set] = {}
    for s, c in cls_of.items():
        by_grp.setdefault(group_of(c), set()).add(s)
    first = min(str(r["d"])[:10] for r in sig)
    start = (pd.Timestamp(first) - pd.Timedelta(days=BETA_DAYS + 40)).date().isoformat()
    missing: dict[str, str] = {}
    for g, syms in by_grp.items():
        src = "binance_hist" if g == "crypto" else "eodhd"
        want = sorted(syms | ({"BTC"} if g == "crypto" else set()))
        try:
            p = await read_panel(want, start=start, source=src, enforce_tradeable=False)
        except Exception as e:                              # noqa: BLE001
            missing[g] = f"{type(e).__name__}: {str(e)[:80]}"
            continue
        idx_ = pd.to_datetime(p.days)
        px = pd.DataFrame(p.close, index=idx_, columns=p.symbols, dtype=float)
        px = px.mask(pd.DataFrame(p.filled, index=idx_, columns=p.symbols))
        px = px.reindex(pd.date_range(px.index.min(), px.index.max(), freq="D"))
        if g != "crypto":
            px = px.ffill(limit=4)      # 传统资产周末 / 假日没有收盘:用 d 及以前最近的收盘(当时已知)
        if g == "crypto" and "BTC" in px.columns:
            btc = px["BTC"]
        members = [s for s in px.columns if s in syms]
        groups[g] = (px, ew_index(px[members]))
    last_day = max(str(r["d"])[:10] for r in sig)
    rows = build_rows(evs, groups, btc, last_day, series=series)
    for i in range(0, len(rows), 1000):
        res = await supabase_upsert_table(TABLE, rows[i:i + 1000], on_conflict="symbol,d,series")
        if not res.ok:
            return {"ok": False, "refused": False, "written": i, "reason": f"{series} 写入失败:{res.why}"}
    with_out = sum(1 for r in rows if r.get("ret_7") is not None)
    published = sum(1 for r in rows if r.get("provenance") == "live")
    return {"ok": not missing, "refused": False, "written": len(rows), "with_outcome_7d": with_out,
            "published": published, "series": series, "groups_without_prices": missing,
            "reason": f"{series}:{len(rows)} 个信号变化(已发布 {published}),{with_out} 个有 7 天结果"
                      + (f";无价格组 {list(missing)}" if missing else "")}


async def run_all() -> dict[str, Any]:
    """两条序列各跑一遍。对外默认 standard;live_mixed 冻结在 LEGACY_END,只为让最后一批结果到期。"""
    out = {s: await run_once(s) for s in (SERIES_STANDARD, SERIES_LEGACY)}
    return {"ok": all(r.get("ok") for r in out.values()), "refused": any(r.get("refused") for r in out.values()),
            "written": sum(r.get("written") or 0 for r in out.values()),
            "with_outcome_7d": sum(r.get("with_outcome_7d") or 0 for r in out.values()),
            "reason": " | ".join(str(r.get("reason")) for r in out.values()), "by_series": out}
