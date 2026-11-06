"""S-741 联合模型 v2 的前向记分(lane-c T-263 判 ✅:Ridge,z 的合并样本外 IC 0.1756、块置换分位 0.986、胜朴素基线 +0.104)。

**授权只有两件:③ 决定的描述输入 + 前向记分。不动钱、不进任何规则。**

## 每天做什么

1. 读 `feature_matrix_daily`(2021-03-24 起)与 BTC 永续收盘(`perp_bv_daily` symbol = BTC)。
2. 特征 = T-263 那一轮的 **59 个键,冻结**(`FEATURES`;之后才有的 `venue:*` 等不进 —— 换特征集 = 新预注册)。
3. 对每一个还没有预测的交易日 i:用 **i − 30 之前**(隔离带 = 持有期)、30 天目标已实现的行训练 Ridge(α = 10,训练段标准化,
   缺值填训练段中位数 —— 与 `joint_model.walk_forward` 同一口径),预测第 i 天。**已存的预测永不重算**(前向锁)。
   与 T-263 的唯一差别:研究里 6 折、每折重训一次;实盘每天重训(扩张窗口、1 天的测试段)—— 实盘不可能等 271 天才重训一次。
   第一次运行把 2022 年起的历史一并按同一口径补上(`kind = backfill`),z 才有 90 个历史;此后每天一行 `kind = live`。
4. 分数 z = (今天的预测 − 严格更早的 90 个预测的均值) / 标准差(ddof = 1);不足 60 个不出分 —— 与 S-741 一字不差。
5. 30 天到期的行补上实现的对数收益;**只用 `live` 行**算前向 IC(补的历史行是用今天的数据算的,不算前向证据)。

判活:`select kind, count(*), max(d), count(fwd_ret_30d) from joint_forecast_daily group by 1` —— live 的 max(d) = 昨天或今天。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import math
from typing import Any, Optional

import numpy as np

TABLE = "joint_forecast_daily"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("d", "model", "kind", "pred", "z", "n_train", "n_hist", "fwd_ret_30d", "features_hash", "code_ref", "computed_at")}
LOOP_NAME = "_joint_forecast_loop"
MODEL = "ridge_v2"
CODE_REF = "s741-t263-ridge-daily-v1"
START = "2021-03-24"
HORIZON = 30
EMBARGO = 30
MIN_TRAIN = 365
ALPHA = 10.0
Z_WIN, Z_MIN = 90, 60
FEATURES = (
    "breadth_above_ma50", "chain:dex_30v30", "chain:dex_to_total_vol", "chain:fees_30v30", "chain:tvl_30d", "channel:rwa_30d",
    "channel:tokenized_30d", "cycle:deterioration", "cycle:shift_pct", "cycle:turning", "dist_200", "dvol:btc", "dvol:btc_pct_1y",
    "funding_7d_ann", "funding_7d_ann_binance", "macro:fed_balance_sheet", "macro:fed_net_liquidity", "macro:fed_rrp", "macro:fed_tga",
    "macro:fng", "macro:total_mcap", "macro:total_volume", "macro:vix", "mom_20", "mom_200", "mom_60", "oi_chg_30d",
    "pos:alt_crowd_median_ln", "pos:alt_smart_minus_crowd_median", "pos:alt_taker_median_ln", "pos:btc_crowd_ln",
    "pos:btc_smart_minus_crowd", "pos:btc_top_pos_ln", "pos:n_symbols", "regime_coverage_30d", "regime_share_30d:EASING",
    "regime_share_30d:NEUTRAL", "regime_share_30d:RISK_OFF", "regime_share_30d:RISK_ON", "regime_share_30d:STAGFLATION",
    "regime_share_30d:TIGHTENING", "spy_ret_21", "stable_lend_apy_7d", "stable_supply_30d", "style:ai_rel30",
    "style:app_eq_minus_cap_30", "style:app_rel30", "style:defi_rel30", "style:infra_tokenization_rel30", "style:meme_rel30",
    "style:second_l1_l2_rel30", "style:top_l1_rel30", "style_rel_majors_30d", "taker_buy_share_30d", "vol_30", "vol_pct_3y",
    "vratio_30_180", "xasset:btc_qqq_corr60", "xasset:btc_uup_corr60")
FEATURES_HASH = hashlib.sha1("|".join(FEATURES).encode()).hexdigest()[:12]


def _num(v: Any) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return float("nan")
    return x if math.isfinite(x) else float("nan")


def build(frows: list[dict], prows: list[dict]) -> tuple[list[str], np.ndarray, np.ndarray]:
    """纯函数。→ (日期, X[n × 59], y[n] = 之后 30 根的对数收益,不知道 ⇒ NaN)。只留当天有价的日子。"""
    px = {str(r["d"])[:10]: float(r["c"]) for r in prows if r.get("c") is not None and float(r["c"]) > 0}
    pdates = sorted(px)
    pidx = {d: i for i, d in enumerate(pdates)}
    seen, rows = set(), []
    for r in sorted(frows, key=lambda r: str(r.get("d"))):
        d = str(r.get("d"))[:10]
        if d in px and d not in seen and d >= START:
            seen.add(d)
            rows.append((d, r.get("f") or {}))
    ds = [d for d, _ in rows]
    X = np.array([[_num(f.get(k)) for k in FEATURES] for _, f in rows], float).reshape(len(rows), len(FEATURES))
    y = np.full(len(ds), np.nan)
    for i, d in enumerate(ds):
        j = pidx[d]
        if j + HORIZON < len(pdates):
            y[i] = math.log(px[pdates[j + HORIZON]] / px[d])
    return ds, X, y


def predict_at(X: np.ndarray, y: np.ndarray, i: int) -> tuple[Optional[float], int]:
    """纯函数。只用 i − EMBARGO 之前、目标已实现的行训练 → 第 i 行的预测(训练行不足 MIN_TRAIN ⇒ None)。"""
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    tr = np.arange(0, max(0, i - EMBARGO))
    tr = tr[~np.isnan(y[tr])]
    if len(tr) < MIN_TRAIN:
        return None, len(tr)
    Xtr = X[tr]
    med = np.nanmedian(np.where(np.isnan(Xtr).all(axis=0), 0.0, Xtr), axis=0) if len(Xtr) else np.zeros(X.shape[1])
    med = np.where(np.isnan(med), 0.0, med)
    fill = lambda M: np.where(np.isnan(M), med, M)  # noqa: E731
    m = make_pipeline(StandardScaler(), Ridge(alpha=ALPHA))
    m.fit(fill(Xtr), y[tr])
    return float(m.predict(fill(X[i:i + 1]))[0]), len(tr)


def z_scores(preds: list[Optional[float]]) -> list[Optional[float]]:
    """纯函数。按时间排好的预测 → S-741 的 z(严格更早的 Z_WIN 个;不足 Z_MIN 个 / 窗口标准差为 0 ⇒ None)。"""
    out, hist = [], []
    for v in preds:
        if v is None:
            out.append(None)
            continue
        z = None
        if len(hist) >= Z_MIN:
            w = np.asarray(hist[-Z_WIN:], float)
            s = float(np.std(w, ddof=1))
            if s > 0:
                z = (v - float(np.mean(w))) / s
        out.append(None if z is None else round(z, 4))
        hist.append(v)
    return out


def forward_ic(rows: list[dict], kind: str = "live") -> dict[str, Any]:
    """纯函数。z 与已实现 30 天收益的 Spearman(≥ 20 对才给数)。**只有 live 是前向证据**;backfill 那份只作口径核对
    (实盘每天重训 vs 研究 6 折 —— 两者差得远就说明口径换了东西),不进任何判。"""
    from src.data.evaluation.joint_model import spearman
    pairs = [(r["z"], r["fwd_ret_30d"]) for r in rows if r.get("kind") == kind and r.get("z") is not None and r.get("fwd_ret_30d") is not None]
    if len(pairs) < 20:
        return {"n": len(pairs), "ic": None}
    v = spearman([p[0] for p in pairs], [p[1] for p in pairs])
    return {"n": len(pairs), "ic": None if v is None else round(v, 4)}


def plan(ds: list[str], X: np.ndarray, y: np.ndarray, have: dict[str, dict], today: dt.date, stamp: str) -> list[dict]:
    """纯函数。已有行的预测不动;没有的按 predict_at 补;z 全部按存下的预测序列重算(只依赖更早的预测,稳定);到期的补收益。"""
    rows = []
    for i, d in enumerate(ds):
        old = have.get(d)
        if old and old.get("pred") is not None:
            pred, n_train, kind = float(old["pred"]), old.get("n_train"), old.get("kind") or "backfill"
        else:
            pred, n_train = predict_at(X, y, i)
            if pred is None:
                continue
            kind = "live" if dt.date.fromisoformat(d) >= today - dt.timedelta(days=2) else "backfill"
        rows.append({"d": d, "model": MODEL, "kind": kind, "pred": round(pred, 6), "n_train": n_train,
                     "fwd_ret_30d": None if math.isnan(y[i]) else round(float(y[i]), 6),
                     "features_hash": FEATURES_HASH, "code_ref": CODE_REF, "computed_at": (old or {}).get("computed_at") or stamp})
    zs = z_scores([r["pred"] for r in rows])
    for r, z, k in zip(rows, zs, range(len(rows))):
        r["z"], r["n_hist"] = z, min(k, Z_WIN)
    return rows


async def run_once(now: Optional[dt.datetime] = None, read=None, upsert=None) -> dict[str, Any]:
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    if read is None:
        from src.data.style.header import _read_all as read
    if upsert is None:
        from src.api.store import supabase_upsert_table as upsert
    frows = await read("feature_matrix_daily", {"select": "d,f", "d": f"gte.{START}", "order": "d.asc"})
    prows = await read("perp_bv_daily", {"select": "d,c", "symbol": "eq.BTC", "d": f"gte.{START}", "order": "d.asc"})
    if not frows or not prows:
        return {"ok": False, "refused": True, "why": f"读不到特征({len(frows or [])})或价格({len(prows or [])})"}
    ds, X, y = build(frows, prows)
    have = {str(r["d"])[:10]: r for r in await read(TABLE, {"select": "d,kind,pred,n_train,computed_at", "model": f"eq.{MODEL}", "order": "d.asc"})}
    import asyncio
    rows = await asyncio.to_thread(plan, ds, X, y, have, now.date(), now.isoformat())   # 首轮约 1,600 次拟合,别占住事件循环
    if not rows:
        return {"ok": False, "refused": True, "why": f"训练行不足 {MIN_TRAIN}"}
    for k in range(0, len(rows), 1000):
        if not await upsert(TABLE, rows[k:k + 1000], on_conflict="d,model"):
            return {"ok": False, "why": f"写 {TABLE} 失败"}
    last = rows[-1]
    fic, bic = forward_ic(rows, "live"), forward_ic(rows, "backfill")
    new = sum(1 for r in rows if r["d"] not in have)
    return {"ok": True, "written": len(rows), "new": new, "latest_d": last["d"], "z": last["z"], "pred": last["pred"],
            "forward_ic": fic, "backfill_ic_not_evidence": bic,
            "why": f"{last['d']} z = {last['z']}(预测 {last['pred']:+.4f})· 新增 {new} 行 · 前向 IC {fic} · 回补口径核对 {bic}"}


async def latest() -> dict[str, Any]:
    """给 ③ 决定 / AI 判断档案的描述输入:最近一行(读不到 ⇒ {})。"""
    from src.data.vector.market_state_writer import _sb_get
    rd = await _sb_get(TABLE, {"select": "d,kind,pred,z,n_hist", "model": f"eq.{MODEL}", "order": "d.desc", "limit": "1"})
    return (rd.rows or [{}])[0] if rd.ok else {}
