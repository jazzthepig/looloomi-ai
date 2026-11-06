#!/usr/bin/env python3
"""T-263 / S-741:联合模型 v2 —— 样本外预测换成「相对自身过去 90 个预测的 z」(时点可得),加 11-06 新并进来的
风格 / 链上 / 持仓结构 / 渠道维度;必须胜过「过去 30 天收益」朴素基线。

口径全部按 S-741 预注册写死(REFUTATION_LEDGER.md,2026-11-06 07:38 UTC):
- 框架 / 折数(6)/ 隔离带(= 持有期)/ 最少训练 365 天 / 两模型超参 / 种子 739 —— 全部照 S-739
- 样本起点 2021-03-24;目标 = BTC 永续之后 30 天(主)/ 7 天(副)对数收益
- 分数 z_t = (p_t − 过去 90 个**样本外预测**的均值) / 标准差;历史不足 60 个当天不出分
- 零分布 1,000 次、块长 20、**种子 741**
- **只调 src/data/evaluation/joint_model.py;不重写 IC / 零分布 / 走步;只算、不写库**

用法:
  python3 docs/research/t263_joint_v2.py --probe   # 只做数据清点(列清单 + 指纹),不出模型
  python3 docs/research/t263_joint_v2.py           # 全量:两模型 × 两目标 + 消融 + 副项
产物:docs/research/t263_results.json
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

PROBE = "--probe" in sys.argv
HERE = Path(__file__).resolve()
REPO = HERE.parents[2]
SETH_WORKSPACE = Path("/Users/sbb/Projects/looloomi-ai")
CACHE_DIR = Path("/tmp/cometcloud_cache")

# ---------------------------------------------------------------- 口径(写死,不要改)
START = "2021-03-24"          # DVOL 的第一天 = 预注册写的样本起点
N_FOLDS = 6
MIN_TRAIN = 365
RIDGE_ALPHA = 10.0
HGB_KW = dict(max_depth=3, learning_rate=0.05, max_iter=300, random_state=739)
N_NULL = 1000
BLOCK = 20
SEED = 739                    # 模型 / 折 / 置换重要性种子(照 S-739)
NULL_SEED = 741               # 零分布种子(照 S-741)
CUT = "2026-11-01"            # 前向才有的列(opt:*)在这天之前必须为空,否则不算前向列
TARGETS = (30, 7)
Z_WIN = 90                    # 过去 90 个样本外预测
Z_MIN = 60                    # 不足 60 个当天不出分
NEW_PREFIXES = ("style:", "chain:", "pos:", "channel:")   # 11-06 新并进来的四个维度族

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


def count_rows(table: str, params: dict) -> int | None:
    """只数不取:Range 0-0 + Prefer: count=exact → 从 Content-Range 读总数。"""
    url = f"{BASE}/rest/v1/{table}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    req.add_header("apikey", KEY)
    req.add_header("Authorization", f"Bearer {KEY}")
    req.add_header("Range", "0-0")
    req.add_header("Prefer", "count=exact")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            cr = r.headers.get("Content-Range") or ""
            if "/" in cr:
                try:
                    return int(cr.split("/")[-1])
                except ValueError:
                    return None
    except Exception:                                          # noqa: BLE001
        return None
    return None


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


# ---------------------------------------------------------------- 取数(只读一次,算指纹,中途不重读)
def load_data():
    cache = CACHE_DIR / "t263_features_cache.json"
    if cache.exists():
        blob = json.loads(cache.read_text(encoding="utf-8"))
        return blob["frows"], blob["ftotal"], blob["n_pre"], blob["prows"], blob["ptotal"]
    frows, ftotal = fetch_all("feature_matrix_daily",
                               {"select": "d,f", "d": f"gte.{START}", "order": "d.asc"})
    n_pre = count_rows("feature_matrix_daily", {"select": "d", "d": f"lt.{START}", "order": "d.asc"})
    prows, ptotal = fetch_all("perp_bv_daily",
                               {"select": "d,c", "symbol": "eq.BTC",
                                "d": f"gte.{START}", "order": "d.asc"})
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"frows": frows, "ftotal": ftotal, "n_pre": n_pre,
                                 "prows": prows, "ptotal": ptotal}, default=str), encoding="utf-8")
    return frows, ftotal, n_pre, prows, ptotal


def build(frows, prows):
    """→ (行, 日期, 列清单, 价, 价日期, 价数组)。行 = 日期有特征且价格序列存在;同日期多行取第一行(并计数)。"""
    px = {}
    for r in prows:
        d = str(r.get("d"))[:10]
        c = r.get("c")
        if d and c is not None:
            px[d] = float(c)
    dates = sorted(px)
    pxd = np.array([px[d] for d in dates])

    rows, seen, dup = [], set(), 0
    for r in frows:
        d = str(r.get("d"))[:10]
        if not d or d not in px:
            continue
        if d in seen:
            dup += 1
            continue
        seen.add(d)
        rows.append({"d": d, "f": r.get("f") or {}})
    rows.sort(key=lambda r: r["d"])
    ds = [r["d"] for r in rows]
    keys = sorted({k for r in rows for k in r["f"].keys()})
    return rows, ds, keys, px, dates, pxd, dup


def column_stats(rows, keys):
    out = []
    for k in keys:
        vals = [r["f"].get(k) for r in rows]
        present = [(r["d"], v) for r, v in zip(rows, vals) if isinstance(v, (int, float)) and v == v]
        out.append({
            "name": k,
            "family": ("new" if k.startswith(NEW_PREFIXES) else "old"),
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


# ---------------------------------------------------------------- 核心:时点可得的 z 变换
def z_of_oof(oof, win: int = Z_WIN, min_hist: int = Z_MIN):
    """S-741 的分数:z_t = (p_t − 过去 win 个样本外预测的均值)/标准差;历史不足 min_hist 个当天不出分。

    窗口里的「过去 win 个」= **严格早于当天的样本外预测**(按时间序),不是日历天 ——
    样本外预测只存在于测试段,所以窗口自然跨折(这正是 S-739 折间不可比的修法)。
    标准差用样本标准差(ddof=1);窗口标准差为 0 ⇒ 当天不出分(分母为 0)。
    """
    z = np.full(len(oof), np.nan)
    hist: list[float] = []
    n_short = n_flat = n_ok = 0
    for i, v in enumerate(oof):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        v = float(v)
        if len(hist) >= min_hist:
            w = np.asarray(hist[-win:], float)
            m = float(np.mean(w))
            s = float(np.std(w, ddof=1))
            if s > 0:
                z[i] = (v - m) / s
                n_ok += 1
            else:
                n_flat += 1
        else:
            n_short += 1
        hist.append(v)
    return z, {"n_scored": n_ok, "n_short_history": n_short, "n_flat_window": n_flat}


def z_of_series(values, win: int = Z_WIN, min_hist: int = Z_MIN):
    """同一 z 变换作用在一条按时间排好、可能含 NaN 的序列上(朴素基线用)。"""
    v = np.asarray(values, float)
    z = np.full(len(v), np.nan)
    hist: list[float] = []
    for i in range(len(v)):
        if math.isnan(v[i]):
            continue
        if len(hist) >= min_hist:
            w = np.asarray(hist[-win:], float)
            m = float(np.mean(w))
            s = float(np.std(w, ddof=1))
            if s > 0:
                z[i] = (v[i] - m) / s
        hist.append(float(v[i]))
    return z


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


# ---------------------------------------------------------------- 模型工厂(超参照 S-739 写死)
def ridge_factory():
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return make_pipeline(StandardScaler(), Ridge(alpha=RIDGE_ALPHA))


def hgb_factory():
    from sklearn.ensemble import HistGradientBoostingRegressor
    return HistGradientBoostingRegressor(**HGB_KW)


def ic(a, b):
    v = JM.spearman(a, b)
    return None if v is None else round(float(v), 4)


def main():
    frows, ftotal, n_pre, prows, ptotal = load_data()
    rows, ds, keys, px, dates, pxd, n_dup = build(frows, prows)
    stats = column_stats(rows, keys)
    kept = [s["name"] for s in stats if not s["forward_only"] and s["n_present"] > 0]
    dropped = [s for s in stats if s["name"] not in kept]
    old_cols = [k for k in kept if not k.startswith(NEW_PREFIXES)]
    new_cols = [k for k in kept if k.startswith(NEW_PREFIXES)]
    venue_cols = [s for s in stats if s["name"].startswith("venue:")]

    X = np.full((len(rows), len(kept)), np.nan)
    for i, r in enumerate(rows):
        for j, k in enumerate(kept):
            v = r["f"].get(k)
            X[i, j] = float(v) if isinstance(v, (int, float)) and v == v else np.nan
    months = [d[:7] for d in ds]

    fingerprint = hashlib.sha256(
        json.dumps([[r["d"], r["f"]] for r in rows], sort_keys=True, default=str).encode()).hexdigest()
    price_fingerprint = hashlib.sha256(
        json.dumps([[d, px[d]] for d in dates], sort_keys=True, default=str).encode()).hexdigest()

    out = {
        "meta": {
            "card": "T-263", "prereg": "S-741",
            "generated_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            "joint_model_source": JM.__source_path__,
            "spec": {"n_folds": N_FOLDS, "min_train": MIN_TRAIN, "embargo": "= 持有期",
                     "ridge_alpha": RIDGE_ALPHA, "hgb": HGB_KW, "n_null": N_NULL,
                     "block": BLOCK, "seed": SEED, "null_seed": NULL_SEED, "start": START,
                     "cut_for_forward_only": CUT, "z_win": Z_WIN, "z_min": Z_MIN,
                     "z_std": "ddof=1", "new_prefixes": list(NEW_PREFIXES)},
            "data_fingerprint": fingerprint,
            "price_fingerprint": price_fingerprint,
        },
        "data": {
            "feature_rows_in_window": ftotal, "feature_rows_before_start": n_pre,
            "price_rows_btc": ptotal, "rows_joined": len(rows), "dup_dates_skipped": n_dup,
            "date_min": ds[0] if ds else None, "date_max": ds[-1] if ds else None,
            "price_date_min": dates[0] if dates else None, "price_date_max": dates[-1] if dates else None,
            "n_keys": len(keys), "n_kept": len(kept), "n_dropped": len(dropped),
            "n_old_kept": len(old_cols), "n_new_kept": len(new_cols),
            "venue_columns": [s["name"] for s in venue_cols],
            "venue_missing_rate_max": max([s["missing_rate"] for s in venue_cols], default=None),
        },
        "columns": stats,
        "kept_columns": kept,
        "old_columns": old_cols,
        "new_columns": new_cols,
        "dropped_columns": [d["name"] for d in dropped],
    }

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
            "p_vix_gt_25": round(float(np.mean([float(r["f"].get("macro:vix")) > 25
                                                 for r in rows if isinstance(r["f"].get("macro:vix"), (int, float))])), 4),
            "last_day": rows[-1]["d"],
            "last_breadth": rows[-1]["f"].get("breadth_above_ma50"),
            "last_vix": rows[-1]["f"].get("macro:vix"),
            "last_price_perp": px.get(rows[-1]["d"]),
            "data_fingerprint": fingerprint,
        }
        # ohlcv_daily 的 BTC 收盘(情景台账的 close:BTC 读它)
        try:
            oc, _ = fetch_all("ohlcv_daily", {"select": "trade_date,close", "source": "eq.binance_hist",
                                              "symbol": "eq.BTC", "order": "trade_date.desc",
                                              "trade_date": "gte.2026-10-20"})
            rates["ohlcv_btc_last5"] = [(str(r.get("trade_date"))[:10], r.get("close")) for r in oc[:5]]
        except Exception as e:                                # noqa: BLE001
            rates["ohlcv_btc_error"] = str(e)
        print(json.dumps(rates, ensure_ascii=False, indent=1))
        return

    if "--columns-md" in sys.argv:
        # 报告开头的列清单(机器生成,免手抄)
        print("| # | 列 | 族 | 有值天数 | 缺值率 | 起始 | 截止 |")
        print("|---|-----|----|---------|--------|------|------|")
        for i, s in enumerate(stats, 1):
            fam = {"old": "旧", "new": "新"}[s["family"]]
            print(f"| {i} | `{s['name']}` | {fam} | {s['n_present']} / {s['n_rows']} | "
                  f"{s['missing_rate']:.3f} | {s['first']} | {s['last']} |")
        return

    if PROBE:
        print(json.dumps(out["data"], ensure_ascii=False, indent=1))
        for s in stats:
            print(f"{s['name']:<34} fam={s['family']:<3} present={s['n_present']:>5} "
                  f"miss={s['missing_rate']:.3f} {s['first']} → {s['last']} "
                  f"{'[前向]' if s['forward_only'] else ''}")
        print("fingerprint:", fingerprint)
        return

    # ---------------------------------------------------------------- 朴素基线:BTC 过去 30 天对数收益
    # 同一 z 变换作用在它上面(A:全日网格;B:只在模型有样本外预测的日子上)。
    idx_price = {d: i for i, d in enumerate(dates)}
    past_ret = np.full(len(ds), np.nan)
    for i, d in enumerate(ds):
        j = idx_price.get(d)
        if j is None or j - 30 < 0:
            continue
        past_ret[i] = math.log(pxd[j] / pxd[j - 30])
    z_base_daily = z_of_series(past_ret)
    # 网格 B:压缩到模型有样本外预测的日子(在每个目标里各自的网格上算)
    z_base_grid = {}

    results = {}
    oof_store = {}
    z_store = {}
    for h in TARGETS:
        y = target_vector(ds, px, dates, pxd, h)
        ok = ~np.isnan(y)
        Xh, yh = X[ok], y[ok]
        mh = [m for m, k in zip(months, ok) if k]
        dsh = [d for d, k in zip(ds, ok) if k]
        folds = JM.purged_folds(len(yh), N_FOLDS, h, MIN_TRAIN)
        # 基线网格 B:只在 OOF 格子上做 z
        oof_any = np.zeros(len(yh), bool)
        for _, te in folds:
            oof_any[te] = True
        pr_h = past_ret[ok]
        zb_grid = np.full(len(yh), np.nan)
        vals = [(i, pr_h[i]) for i in range(len(yh)) if oof_any[i] and not math.isnan(pr_h[i])]
        seq = [v for _, v in vals]
        zz = z_of_series(seq)
        for (i, _), zv in zip(vals, zz):
            zb_grid[i] = zv
        z_base_grid[h] = zb_grid

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
            z, zinfo = z_of_oof(oof)
            ev = JM.evaluate(z, yh, mh, block=BLOCK, n_null=N_NULL, seed=NULL_SEED)
            ev_raw = JM.evaluate(oof, yh, mh, block=BLOCK, n_null=N_NULL, seed=NULL_SEED)
            per_fold = []
            for k, (tr, te) in enumerate(folds, 1):
                v = JM.spearman(z[te], yh[te])
                per_fold.append({"fold": k, "n": int(len(te)),
                                 "ic": None if v is None else round(v, 4),
                                 "ic_no_z": ic(oof[te], yh[te]),
                                 "test_start": dsh[te[0]], "test_end": dsh[te[-1]]})
            late = np.concatenate([te for k, (tr, te) in enumerate(folds, 1) if k >= 4])
            v_late = JM.spearman(z[late], yh[late])
            # (e) 朴素基线:同一 z 变换作用在 BTC 过去 30 天收益上
            cmp_rows = []
            for tag, zb in (("A_daily_grid", z_base_daily[ok]), ("B_oof_grid", zb_grid)):
                m = ~(np.isnan(z) | np.isnan(zb) | np.isnan(yh))
                ic_model = JM.spearman(z[m], yh[m])
                ic_base = JM.spearman(zb[m], yh[m])
                cmp_rows.append({
                    "baseline_variant": tag,
                    "n_common": int(m.sum()),
                    "ic_model_z": None if ic_model is None else round(float(ic_model), 4),
                    "ic_baseline": None if ic_base is None else round(float(ic_base), 4),
                    "ic_diff": None if (ic_model is None or ic_base is None) else round(float(ic_model - ic_base), 4),
                })
            block["models"][name] = {
                "z_score": {**ev, **zinfo},
                "raw_no_z": ev_raw,
                "per_fold_ic": per_fold,
                "late_folds_4_6_ic": None if v_late is None else round(float(v_late), 4),
                "late_folds_4_6_n": int(len(late)),
                "vs_naive_baseline": cmp_rows,
            }
            oof_store[(h, name)] = (oof, z, yh, dsh)
            z_store[(h, name)] = (z, yh, dsh)
        results[f"h{h}"] = block

    out["results"] = results

    # ---------------------------------------------------------------- 判据(只用 30 天)
    crit_all = []
    for name in ("ridge", "hgb"):
        m = results["h30"]["models"][name]
        zs = m["z_score"]
        a = zs["ic"] is not None and zs["ic"] >= 0.10
        b = zs["pctile"] is not None and zs["pctile"] >= 0.95
        c = zs["t"] is not None and zs["t"] >= 2.0
        d = m["late_folds_4_6_ic"] is not None and m["late_folds_4_6_ic"] > 0
        cmpA = [x for x in m["vs_naive_baseline"] if x["baseline_variant"] == "A_daily_grid"][0]
        cmpB = [x for x in m["vs_naive_baseline"] if x["baseline_variant"] == "B_oof_grid"][0]
        e = cmpA["ic_diff"] is not None and cmpA["ic_diff"] >= 0.05
        crit_all.append({
            "model": name,
            "a_ic_ge_0.10": bool(a), "a_ic": zs["ic"],
            "b_pctile_ge_0.95": bool(b), "b_pctile": zs["pctile"], "b_null_p95": zs.get("null_p95"),
            "c_monthly_t_ge_2.0": bool(c), "c_t": zs["t"], "c_n_months": zs.get("n_months"),
            "d_late_folds_ic_gt_0": bool(d), "d_ic": m["late_folds_4_6_ic"],
            "e_beats_naive_ge_0.05": bool(e), "e_ic_diff_daily_grid": cmpA["ic_diff"],
            "e_ic_model": cmpA["ic_model_z"], "e_ic_baseline": cmpA["ic_baseline"],
            "e_n_common": cmpA["n_common"],
            "e_robust_oof_grid_ic_diff": cmpB["ic_diff"],
            "e_robust_oof_grid_ic_baseline": cmpB["ic_baseline"],
            "pass": bool(a and b and c and d and e),
        })
    out["criteria_30d"] = crit_all
    out["verdict"] = "✅" if any(x["pass"] for x in crit_all) else "❌"
    # 中途落盘:置换重要性最慢(700+ 次拟合),先保住主结果,免得进程被杀就什么都没了
    outp = REPO / "docs/research/t263_results.json"
    outp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------------------------------------------------------------- 副:消融两格(30 天)
    y30 = target_vector(ds, px, dates, pxd, 30)
    ok30 = ~np.isnan(y30)
    X30, y30k = X[ok30], y30[ok30]
    m30 = [m for m, k in zip(months, ok30) if k]
    folds30 = JM.purged_folds(len(y30k), N_FOLDS, 30, MIN_TRAIN)
    keep_idx = {k: i for i, k in enumerate(kept)}
    abl = {}
    cells = [
        ("A1_z_only_no_new_dims", old_cols, True),
        ("A2_new_dims_no_z", kept, False),
    ]
    for tag, cols, use_z in cells:
        idxs = [keep_idx[c] for c in cols]
        Xc = X30[:, idxs]
        for name, factory in (("ridge", ridge_factory), ("hgb", hgb_factory)):
            oof = JM.walk_forward(Xc, y30k, folds30, factory)
            if use_z:
                z, zinfo = z_of_oof(oof)
                ev = JM.evaluate(z, y30k, m30, block=BLOCK, n_null=N_NULL, seed=NULL_SEED)
            else:
                ev = JM.evaluate(oof, y30k, m30, block=BLOCK, n_null=N_NULL, seed=NULL_SEED)
                zinfo = {"n_scored": int((~np.isnan(oof)).sum())}
            abl.setdefault(tag, {})[name] = {**ev, "n_cols": len(cols), **zinfo}
    out["ablation_h30"] = abl

    # ---------------------------------------------------------------- 副:置换重要性前 10(30 天,原模型)
    perm = {}
    for name, factory in (("ridge", ridge_factory), ("hgb", hgb_factory)):
        imp = JM.permutation_importance(X30, y30k, folds30, factory, kept, seed=SEED)
        perm[name] = imp[:10]
        perm[f"{name}_all"] = imp
    out["perm_importance_h30"] = perm

    # ---------------------------------------------------------------- 副:按 S-737 的 6 类状态拆 IC(30 天)
    lab, note = state_labels(rows)
    out["state_note"] = note
    if lab:
        per_state = []
        for name in ("ridge", "hgb"):
            z, yh, dsh = z_store[(30, name)]
            for s in range(6):
                idx = [i for i, d in enumerate(dsh) if lab.get(d, (None,))[0] == s]
                if len(idx) < 20:
                    per_state.append({"model": name, "state": s, "n": len(idx),
                                      "ic_z": None, "ic_raw": None})
                    continue
                oof, _, _, _ = oof_store[(30, name)]
                per_state.append({"model": name, "state": s, "n": len(idx),
                                  "ic_z": ic(z[idx], yh[idx]), "ic_raw": ic(oof[idx], yh[idx])})
        out["state_ic_h30"] = per_state

    # ---------------------------------------------------------------- 副:两模型样本外预测的相关
    side = {}
    for h in TARGETS:
        a = oof_store.get((h, "ridge"))
        b = oof_store.get((h, "hgb"))
        if a and b:
            m = ~(np.isnan(a[0]) | np.isnan(b[0]))
            side[f"model_corr_raw_h{h}"] = round(float(np.corrcoef(a[0][m], b[0][m])[0, 1]), 4) if m.sum() > 10 else None
            za, zb = a[1], b[1]
            m2 = ~(np.isnan(za) | np.isnan(zb))
            side[f"model_corr_z_h{h}"] = round(float(np.corrcoef(za[m2], zb[m2])[0, 1]), 4) if m2.sum() > 10 else None

    # z 分数自身的分布(诊断:z 是不是基本是噪声)
    zdiag = {}
    for name in ("ridge", "hgb"):
        z, yh, dsh = z_store[(30, name)]
        m = ~np.isnan(z)
        zdiag[name] = {
            "n": int(m.sum()),
            "z_mean": round(float(np.mean(z[m])), 4) if m.sum() else None,
            "z_std": round(float(np.std(z[m])), 4) if m.sum() else None,
            "z_min": round(float(np.min(z[m])), 4) if m.sum() else None,
            "z_max": round(float(np.max(z[m])), 4) if m.sum() else None,
            "ic_z_vs_past30ret": ic(z, past_ret[ok30]),
        }
    out["z_diag_h30"] = zdiag
    out["side"] = side

    p = REPO / "docs/research/t263_results.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    slim = {k: v for k, v in out.items() if k not in ("columns", "perm_importance_h30")}
    slim["perm_importance_h30"] = {k: v for k, v in perm.items() if not k.endswith("_all")}
    print(json.dumps(slim, ensure_ascii=False, indent=1))
    print("written:", p)


if __name__ == "__main__":
    main()
