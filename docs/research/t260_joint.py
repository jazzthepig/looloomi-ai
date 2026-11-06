#!/usr/bin/env python3
"""T-260 / S-739:第一次「放在一起」—— feature_matrix_daily 全部维度的联合模型,对 BTC 之后 30 天(与 7 天)收益,样本外。

口径全部按 S-739 预注册写死(REFUTATION_LEDGER.md,2026-11-06 06:15 UTC):
- 样本:feature_matrix_daily 的全部键(2021-03-24 起 = DVOL 的第一天);缺值留空,由框架按训练段中位数填
- 目标:BTC 之后 30 天 / 7 天对数收益(perp_bv_daily, symbol=eq.BTCUSDT, 收盘 c)
- 框架:6 折走步、隔离带 = 持有期(30 / 7 天)、最少训练 365 天;Ridge(alpha=10,训练段标准化)与
  HistGradientBoosting(max_depth 3, learning_rate 0.05, max_iter 300, 种子 739);零分布 1,000 次、块长 20、种子 739
- **只调 src/data/evaluation/joint_model.py;不重写 IC / 零分布 / 走步;只算、不写库**

用法:python3 docs/research/t260_joint.py [--probe]     # --probe:只做数据清点,不出模型
产物:docs/research/t260_results.json
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

PROBE = "--probe" in sys.argv
HERE = Path(__file__).resolve()
REPO = HERE.parents[2]
SETH_WORKSPACE = Path("/Users/sbb/Projects/looloomi-ai")

# ---------------------------------------------------------------- 口径(写死,不要改)
START = "2021-03-24"          # DVOL 的第一天 = 预注册写的样本起点
N_FOLDS = 6
MIN_TRAIN = 365
RIDGE_ALPHA = 10.0
HGB_KW = dict(max_depth=3, learning_rate=0.05, max_iter=300, random_state=739)
N_NULL = 1000
BLOCK = 20
SEED = 739
CUT = "2026-11-01"            # 前向才有的列(opt:*)在这天之前必须为空,否则不算前向列
TARGETS = (30, 7)

BASE = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_KEY", "")
if not BASE or not KEY:
    sys.exit("缺 SUPABASE_URL / SUPABASE_KEY 环境变量,退出")


# ---------------------------------------------------------------- 只读 REST(分页带 order)
def fetch_all(table: str, params: dict, page: int = 1000):
    """只读分页取全表。翻页一律带 order=(按主键排),每页 ≤ 1000 行(limit>1000 会被静默截断)。
    末页按 Content-Range 的总数夹住(否则 PostgREST 对越界的 Range 回 416)。"""
    rows: list[dict] = []
    off = 0
    total = None
    while True:
        q = dict(params)
        # 不传 limit:PostgREST 在 limit + Range(偏移>0) 同时出现时回 416(PGRST103)—— 每页大小只由 Range 决定
        url = f"{BASE}/rest/v1/{table}?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url)
        req.add_header("apikey", KEY)
        req.add_header("Authorization", f"Bearer {KEY}")
        end = off + page - 1
        if total is not None:
            end = min(end, total - 1)
        req.add_header("Range", f"{off}-{end}")
        if total is None:
            req.add_header("Prefer", "count=exact")
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                if total is None:
                    cr = r.headers.get("Content-Range") or ""
                    if "/" in cr:
                        try:
                            total = int(cr.split("/")[-1])
                        except ValueError:
                            total = None
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:                     # 416 = 越界,后面没有了
            if e.code == 416:
                break
            raise
        rows.extend(data)
        off += len(data)
        if len(data) < page:
            break
        if total is not None and off >= total:
            break
    return rows, total


# ---------------------------------------------------------------- 框架(joint_model.py,只 import)
def load_joint_model():
    """joint_model.py 若还没合进 main,就从 Seth 的工作区读 —— 只 import,不改。"""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from src.data.evaluation import apparatus  # noqa: F401  (joint_model 依赖它)
    cands = [REPO / "src/data/evaluation/joint_model.py",
             SETH_WORKSPACE / "src/data/evaluation/joint_model.py"]
    for p in cands:
        if not p.exists():
            continue
        spec = importlib.util.spec_from_file_location("src.data.evaluation.joint_model", p)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["src.data.evaluation.joint_model"] = mod
        spec.loader.exec_module(mod)
        mod.__source_path__ = str(p)
        return mod
    sys.exit("找不到 src/data/evaluation/joint_model.py(main 与 Seth 工作区都没有)")


JM = load_joint_model()


# ---------------------------------------------------------------- 取数
def load_data():
    frows, ftotal = fetch_all("feature_matrix_daily",
                               {"select": "d,f", "d": f"gte.{START}", "order": "d.asc"})
    # 起点之前还有多少行(报告里写明)
    pre, _ = fetch_all("feature_matrix_daily", {"select": "d", "d": f"lt.{START}", "order": "d.asc"})
    prows, ptotal = fetch_all("perp_bv_daily",
                               {"select": "d,c", "symbol": "eq.BTC",
                                "d": f"gte.{START}", "order": "d.asc"})
    return frows, ftotal, len(pre), prows, ptotal


def build(frows, prows):
    """→ (行, 目标, 列清单)。行 = 日期有特征 且 价格序列存在;列 = 全部出现过的键。"""
    px = {}
    for r in prows:
        d = str(r.get("d"))[:10]
        c = r.get("c")
        if d and c is not None:
            px[d] = float(c)
    dates = sorted(px)
    pxd = np.array([px[d] for d in dates])

    rows = []
    seen = set()
    for r in frows:
        d = str(r.get("d"))[:10]
        if not d or d in seen or d not in px:
            continue
        seen.add(d)
        rows.append({"d": d, "f": r.get("f") or {}})
    rows.sort(key=lambda r: r["d"])
    ds = [r["d"] for r in rows]
    keys = sorted({k for r in rows for k in r["f"].keys()})
    return rows, ds, keys, px, dates, pxd


def column_stats(rows, keys):
    out = []
    for k in keys:
        vals = [r["f"].get(k) for r in rows]
        present = [(r["d"], v) for r, v in zip(rows, vals) if isinstance(v, (int, float)) and v == v]
        out.append({
            "name": k,
            "n_present": len(present),
            "n_rows": len(rows),
            "missing_rate": round(1 - len(present) / max(1, len(rows)), 4),
            "first": present[0][0] if present else None,
            "last": present[-1][0] if present else None,
            "forward_only": bool(present) and present[0][0] > CUT,
        })
    return out


def target_vector(ds, px, dates, pxd, h):
    """之后 h 天的对数收益(按序列行数算);取不到就 NaN。"""
    idx = {d: i for i, d in enumerate(dates)}
    y = np.full(len(ds), np.nan)
    for i, d in enumerate(ds):
        j = idx.get(d)
        if j is None or j + h >= len(pxd):
            continue
        y[i] = math.log(pxd[j + h] / pxd[j])
    return y


# ---------------------------------------------------------------- 状态标注(S-737 的 6 类,T-257 冻结规格)
def state_labels(rows):
    """用 src/data/state/state_map.py(已冻结:13 特征 / 训练窗 / k=6 / 种子 737)给每个日子打标。
    state_map.py 还没合进 main 时从 Seth 的工作区读 —— 只 import,不改。"""
    try:
        from src.data.state import state_map
    except Exception:                                         # noqa: BLE001
        cands = [REPO / "src/data/state/state_map.py",
                 SETH_WORKSPACE / "src/data/state/state_map.py"]
        state_map = None
        for p in cands:
            if not p.exists():
                continue
            spec = importlib.util.spec_from_file_location("src.data.state.state_map", p)
            mod = importlib.util.module_from_spec(spec)
            sys.modules["src.data.state.state_map"] = mod
            try:
                spec.loader.exec_module(mod)
            except Exception as e:                            # noqa: BLE001
                return None, f"state_map 载入失败({p}): {e}"
            state_map = mod
            break
        if state_map is None:
            return None, "state_map 找不到(main 与 Seth 工作区都没有)"
    try:
        ds, X = state_map.matrix(rows)
        model = state_map.fit(ds, X)
        lab = {}
        for d, x in zip(ds, X):
            s, dist = state_map.assign(model, x)
            lab[d] = (s, dist)
        return lab, f"align_worst={model['align_worst']:.3f} · src={getattr(state_map, '__file__', '?')}"
    except Exception as e:                                    # noqa: BLE001
        return None, f"state_map 失败: {e}"


# ---------------------------------------------------------------- 诊断(副项,不参与 S-739 判定)
def fold_diagnostics(oof, y, folds, dsh):
    """每折:原 IC、去时间趋势后的 IC、块置换零分布分位;外加折内去均值 / 去趋势后的合并 IC。
    用来回答一个数:折内 IC 高、合并 IC 近 0 —— 是「跨折水平漂移」还是「时间趋势的共同分量」。"""
    from src.data.evaluation.apparatus import block_permute, null_distribution, percentile_of
    p = np.asarray(oof, float)
    yv = np.asarray(y, float)
    pm, ym, pd, yd = p.copy(), yv.copy(), p.copy(), yv.copy()
    out = {"per_fold": []}
    for k, (tr, te) in enumerate(folds, 1):
        tt = np.arange(len(te), dtype=float)
        pt, yt = p[te], yv[te]
        ic_raw = JM.spearman(pt, yt)
        rp = pt - np.polyval(np.polyfit(tt, pt, 1), tt)
        rt = yt - np.polyval(np.polyfit(tt, yt, 1), tt)
        ic_dt = JM.spearman(rp, rt)
        try:
            null = null_distribution(lambda r: JM.spearman(block_permute(pt, BLOCK, r), yt) or 0.0,
                                     N_NULL, SEED + k, actual=ic_raw)
            n95, pct = round(float(np.percentile(null, 95)), 4), round(float(percentile_of(ic_raw, null)), 4)
        except Exception as e:                                # noqa: BLE001
            n95, pct = None, f"null 失败: {e}"
        out["per_fold"].append({
            "fold": k, "test_start": dsh[te[0]], "test_end": dsh[te[-1]],
            "ic_raw": None if ic_raw is None else round(ic_raw, 4),
            "ic_detrended": None if ic_dt is None else round(ic_dt, 4),
            "null_p95": n95, "pctile": pct,
            "oof_mean": round(float(np.mean(pt)), 4), "oof_std": round(float(np.std(pt)), 4),
            "y_mean": round(float(np.mean(yt)), 4),
        })
        pm[te], ym[te] = pt - pt.mean(), yt - yt.mean()
        pd[te], yd[te] = rp, rt
    m = ~(np.isnan(pm) | np.isnan(ym))
    out["pooled_ic_demeaned_within_fold"] = round(JM.spearman(pm[m], ym[m]) or 0.0, 4)
    m2 = ~(np.isnan(pd) | np.isnan(yd))
    out["pooled_ic_detrended_within_fold"] = round(JM.spearman(pd[m2], yd[m2]) or 0.0, 4)
    return out


# ---------------------------------------------------------------- 主流程
def main():
    frows, ftotal, n_pre, prows, ptotal = load_data()
    rows, ds, keys, px, dates, pxd = build(frows, prows)
    stats = column_stats(rows, keys)
    kept = [s["name"] for s in stats if not s["forward_only"] and s["n_present"] > 0]
    dropped = [s for s in stats if s["name"] not in kept]

    out = {
        "meta": {
            "card": "T-260", "prereg": "S-739",
            "generated_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            "joint_model_source": JM.__source_path__,
            "spec": {"n_folds": N_FOLDS, "min_train": MIN_TRAIN, "embargo": "= 持有期",
                     "ridge_alpha": RIDGE_ALPHA, "hgb": HGB_KW, "n_null": N_NULL,
                     "block": BLOCK, "seed": SEED, "start": START, "cut_for_forward_only": CUT},
        },
        "data": {
            "feature_rows_in_window": ftotal, "feature_rows_before_start": n_pre,
            "price_rows_btc": ptotal, "rows_joined": len(rows),
            "date_min": ds[0] if ds else None, "date_max": ds[-1] if ds else None,
            "price_date_min": dates[0] if dates else None, "price_date_max": dates[-1] if dates else None,
            "n_keys": len(keys), "n_kept": len(kept), "n_dropped": len(dropped),
        },
        "columns": stats,
        "kept_columns": kept,
        "dropped_columns": [d["name"] for d in dropped],
    }

    if PROBE:
        print(json.dumps(out["data"], ensure_ascii=False, indent=1))
        for s in stats:
            print(f"{s['name']:<34} present={s['n_present']:>5} miss={s['missing_rate']:.3f} "
                  f"{s['first']} → {s['last']} {'[前向]' if s['forward_only'] else ''}")
        return

    if "--rates" in sys.argv:
        # 前向预期要用的基率:某些量在本样本里的「> 0 比例」与最新值
        y30 = target_vector(ds, px, dates, pxd, 30)
        ok = ~np.isnan(y30)
        rates = {
            "n": int(ok.sum()),
            "p_fwd30_gt0": round(float(np.mean(y30[ok] > 0)), 4),
            "p_fwd30_lt0": round(float(np.mean(y30[ok] < 0)), 4),
            "p_breadth_gt0": round(float(np.mean([float(r["f"].get("breadth_above_ma50", 0) or 0) > 0
                                                  for r in rows])), 4),
            "p_breadth_lt_025": round(float(np.mean([(float(r["f"].get("breadth_above_ma50", 0) or 0)) <= 0.25
                                                      for r in rows])), 4),
            "p_vix_gt_25": round(float(np.mean([(float(r["f"].get("macro:vix")) > 25)
                                                 for r in rows if isinstance(r["f"].get("macro:vix"), (int, float))])), 4),
            "last_day": rows[-1]["d"],
            "last_breadth": rows[-1]["f"].get("breadth_above_ma50"),
            "last_vix": rows[-1]["f"].get("macro:vix"),
            "last_dvol_pct_1y": rows[-1]["f"].get("dvol:btc_pct_1y"),
            "last_price": px.get(rows[-1]["d"]),
        }
        # ohlcv_daily 的 BTC 收盘(情景台账的 close:BBC 读它)
        try:
            oc, _ = fetch_all("ohlcv_daily", {"select": "trade_date,close", "source": "eq.binance_hist",
                                              "symbol": "eq.BTC", "order": "trade_date.asc",
                                              "trade_date": "gte.2026-09-01"})
            rates["ohlcv_btc_last5"] = [(str(r.get("trade_date"))[:10], r.get("close")) for r in oc[-5:]]
        except Exception as e:                                # noqa: BLE001
            rates["ohlcv_btc_error"] = str(e)
        print(json.dumps(rates, ensure_ascii=False, indent=1))
        return

    # ---- 矩阵
    X = np.full((len(rows), len(kept)), np.nan)
    for i, r in enumerate(rows):
        for j, k in enumerate(kept):
            v = r["f"].get(k)
            X[i, j] = float(v) if isinstance(v, (int, float)) and v == v else np.nan
    months = [d[:7] for d in ds]

    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    def ridge_factory():
        return make_pipeline(StandardScaler(), Ridge(alpha=RIDGE_ALPHA))

    def hgb_factory():
        return HistGradientBoostingRegressor(**HGB_KW)

    if "--ridge-only" in sys.argv:
        # 快速复核:数据指纹 + Ridge 的合并样本外 IC(用来判断两次运行之间的数变了是代码还是数据变了)
        import hashlib
        y = target_vector(ds, px, dates, pxd, 30)
        ok = ~np.isnan(y)
        Xh, yh = X[ok], y[ok]
        folds = JM.purged_folds(len(yh), N_FOLDS, 30, MIN_TRAIN)
        oof = JM.walk_forward(Xh, yh, folds, ridge_factory)
        ev = JM.evaluate(oof, yh, [m for m, k in zip(months, ok) if k], block=BLOCK, n_null=N_NULL, seed=SEED)
        fp = hashlib.sha256(json.dumps([[r["d"], r["f"]] for r in rows], sort_keys=True, default=str).encode()).hexdigest()
        print(json.dumps({"fingerprint": fp, "rows": len(rows), "date_max": ds[-1], "eval": ev,
                          "per_fold": [round(JM.spearman(oof[te], yh[te]) or 0.0, 4) for tr, te in folds]},
                         ensure_ascii=False, indent=1))
        return

    results = {}
    oof_store = {}
    for h in TARGETS:
        y = target_vector(ds, px, dates, pxd, h)
        ok = ~np.isnan(y)
        Xh, yh, mh = X[ok], y[ok], [m for m, k in zip(months, ok) if k]
        dsh = [d for d, k in zip(ds, ok) if k]
        folds = JM.purged_folds(len(yh), N_FOLDS, h, MIN_TRAIN)
        block = {
            "h": h, "n": int(len(yh)), "n_folds": len(folds),
            "date_min": dsh[0] if dsh else None, "date_max": dsh[-1] if dsh else None,
            "folds": [{"k": k, "train_n": len(tr), "test_n": len(te),
                       "test_start": dsh[te[0]] if len(te) else None,
                       "test_end": dsh[te[-1]] if len(te) else None} for k, (tr, te) in enumerate(folds, 1)],
            "models": {},
        }
        for name, factory in (("ridge", ridge_factory), ("hgb", hgb_factory)):
            oof = JM.walk_forward(Xh, yh, folds, factory)
            ev = JM.evaluate(oof, yh, mh, block=BLOCK, n_null=N_NULL, seed=SEED)
            per_fold = []
            for k, (tr, te) in enumerate(folds, 1):
                v = JM.spearman(oof[te], yh[te])
                per_fold.append({"fold": k, "n": int(len(te)), "ic": None if v is None else round(v, 4),
                                 "test_start": dsh[te[0]], "test_end": dsh[te[-1]]})
            late = np.concatenate([te for k, (tr, te) in enumerate(folds, 1) if k >= 4])
            v_late = JM.spearman(oof[late], yh[late])
            block["models"][name] = {
                **ev,
                "per_fold_ic": per_fold,
                "late_folds_4_6_ic": None if v_late is None else round(v_late, 4),
                "late_folds_4_6_n": int(len(late)),
                "diag": fold_diagnostics(oof, yh, folds, dsh),
            }
            oof_store[(h, name)] = (oof, yh, dsh)
        # 判据(只用 30 天;7 天只报)
        if h == 30:
            crit = []
            for name in ("ridge", "hgb"):
                m = block["models"][name]
                a = (m["ic"] is not None and m["ic"] >= 0.10)
                b = (m["pctile"] is not None and m["pctile"] >= 0.95)
                c = (m["t"] is not None and m["t"] >= 2.0)
                d = (m["late_folds_4_6_ic"] is not None and m["late_folds_4_6_ic"] > 0)
                crit.append({"model": name, "a_ic_ge_0.10": a, "b_pctile_ge_0.95": b,
                             "c_monthly_t_ge_2.0": c, "d_late_folds_ic_gt_0": d,
                             "pass": bool(a and b and c and d)})
            block["criteria"] = crit
            block["verdict"] = "✅" if any(x["pass"] for x in crit) else "❌"
        results[f"h{h}"] = block

    # ---- 副:两模型样本外预测的相关
    side = {}
    for h in TARGETS:
        a = oof_store.get((h, "ridge"))
        b = oof_store.get((h, "hgb"))
        if a and b:
            m = ~(np.isnan(a[0]) | np.isnan(b[0]))
            side[f"model_corr_h{h}"] = round(float(np.corrcoef(a[0][m], b[0][m])[0, 1]), 4) if m.sum() > 10 else None

    # ---- 副:置换重要性前 10(两模型各一份,30 天目标)
    y30 = target_vector(ds, px, dates, pxd, 30)
    ok = ~np.isnan(y30)
    X30, y30k = X[ok], y30[ok]
    folds30 = JM.purged_folds(len(y30k), N_FOLDS, 30, MIN_TRAIN)
    for name, factory in (("ridge", ridge_factory), ("hgb", hgb_factory)):
        imp = JM.permutation_importance(X30, y30k, folds30, factory, kept, seed=SEED)
        side[f"perm_importance_h30_{name}"] = imp[:10]
        side[f"perm_importance_h30_{name}_all"] = imp

    # ---- 副:按 S-737 的 6 类状态拆 IC(30 天目标)
    lab, note = state_labels(rows)
    side["state_note"] = note
    if lab:
        oof_r, yh, dsh = oof_store[(30, "ridge")]
        oof_h, _, _ = oof_store[(30, "hgb")]
        per_state = []
        for s in range(6):
            idx = [i for i, d in enumerate(dsh) if lab.get(d, (None,))[0] == s]
            if len(idx) < 20:
                per_state.append({"state": s, "n": len(idx), "ic_ridge": None, "ic_hgb": None})
                continue
            v1 = JM.spearman(oof_r[idx], yh[idx])
            v2 = JM.spearman(oof_h[idx], yh[idx])
            per_state.append({"state": s, "n": len(idx),
                              "ic_ridge": None if v1 is None else round(v1, 4),
                              "ic_hgb": None if v2 is None else round(v2, 4)})
        side["state_ic_h30"] = per_state

    out["results"] = results
    out["side"] = side
    p = REPO / "docs/research/t260_results.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"data": out["data"], "results": results, "side": {k: v for k, v in side.items()
                                                                        if not k.endswith("_all")}}, ensure_ascii=False, indent=1))
    print("written:", p)


if __name__ == "__main__":
    main()
