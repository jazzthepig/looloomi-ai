#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-315 / S-795 —— 单币形态识别:「出事之前」的 60 天形状能否被提前认出。

口径照 REFUTATION_LEDGER S-795 预注册原文,只算一次(K=20/100 只作描述)。
只读:不改代码、不入库。

用法:
  python3 t315_shape.py probe    # 探表结构(改了同一个文件再跑)
  python3 t315_shape.py fetch    # 拉只读快照 -> .t315_cache/
  python3 t315_shape.py run      # 算两臂 + 判据 (a)-(d)
"""
import os
import sys
import json
import math
import csv
import time
import hashlib
import urllib.request
import urllib.error
from datetime import date, timedelta, datetime, timezone
from collections import Counter, defaultdict

U = os.environ.get("SUPABASE_URL", "").rstrip("/")
K = os.environ.get("SUPABASE_KEY", "")
if not U or not K:
    raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY,退出")

REPO = "/Users/sbb/Projects/looloomi-ai-lane-a"
CACHE = os.environ.get("T315_CACHE", os.path.join(REPO, ".t315_cache"))
RESEARCH = os.path.join(REPO, "docs/research")
EVENTS_CSV = "/Users/sbb/Projects/looloomi-ai/docs/research/t309_events.csv"

MODE = sys.argv[1] if len(sys.argv) > 1 else "probe"
_ARGV = sys.argv[2:]
if "--cache" in _ARGV:
    CACHE = _ARGV[_ARGV.index("--cache") + 1]
MAXSYM = int(_ARGV[_ARGV.index("--maxsym") + 1]) if "--maxsym" in _ARGV else 0


def get(path, extra=None):
    url = U + "/rest/v1/" + path
    req = urllib.request.Request(url)
    req.add_header("apikey", K)
    req.add_header("Authorization", "Bearer " + K)
    for k, v in (extra or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read().decode(), r.headers.get("Content-Range")


def get_rows(path, page=1000, extra=None):
    """翻页读,必须带 order=;每页 ≤1000 行。"""
    rows = []
    offset = 0
    while True:
        sep = "&" if "?" in path else "?"
        full = f"{path}{sep}limit={page}&offset={offset}"
        body, cr = get(full, extra or {"Prefer": "count=exact"})
        batch = json.loads(body)
        if not isinstance(batch, list):
            raise SystemExit(f"非列表响应: {body[:200]}")
        rows.extend(batch)
        if len(batch) < page:
            return rows, cr
        offset += page
        if offset > 400000:
            raise SystemExit("翻页超过上限,中止")


# ----------------------------------------------------------------------------- probe
def probe():
    for tbl, sel, n in [
        ("perp_bv_pairs", "*", 3),
        ("perp_bv_daily", "*", 2),
        ("delisting_watch", "*", 3),
    ]:
        body, cr = get(f"{tbl}?select={sel}&limit={n}", {"Prefer": "count=exact"})
        rows = json.loads(body)
        print(f"--- {tbl}  count_range={cr}")
        if rows:
            print("    keys:", list(rows[0].keys()))
            for r in rows[:n]:
                print("    ", {k: str(v)[:70] for k, v in r.items()})
        else:
            print("    (空)")
    # 边界:最早/最晚 d
    for tbl, col in [("perp_bv_daily", "d"), ("delisting_watch", "d0")]:
        for direction in ["asc", "desc"]:
            try:
                body, cr = get(f"{tbl}?select=*&order={col}.{direction}&limit=1")
                rows = json.loads(body)
                if rows:
                    print(f"    {tbl} {col} {direction}: {str(rows[0].get(col))} keys={list(rows[0].keys())}")
            except urllib.error.HTTPError as e:
                print(f"    {tbl} {col} {direction}: HTTP {e.code} {e.read().decode()[:160]}")


def kinds():
    pairs, cr = get_rows("perp_bv_pairs?select=pair,symbol,first_d,active,dead_from,kind,underlying_type&order=symbol.asc")
    print("pairs rows:", len(pairs), "count_range:", cr)
    print("kind:", Counter(str(p["kind"]) for p in pairs).most_common())
    print("underlying_type:", Counter(str(p["underlying_type"]) for p in pairs).most_common())
    print("active:", Counter(str(p["active"]) for p in pairs).most_common())
    coin = [p for p in pairs if p["kind"] == "coin"]
    print("kind=='coin':", len(coin), "sample:", [(p["symbol"], p["first_d"], p["active"]) for p in coin[:6]])
    print("first_d range:", min(str(p["first_d"]) for p in pairs), max(str(p["first_d"]) for p in pairs))
    json.dump(pairs, open(os.path.join(CACHE, "pairs.json"), "w"))


def fetch():
    os.makedirs(CACHE, exist_ok=True)
    pairs = json.load(open(os.path.join(CACHE, "pairs.json")))
    coin_syms = sorted({p["symbol"] for p in pairs if p["kind"] == "coin"})
    print("coin symbols:", len(coin_syms), flush=True)
    dl, cr = get_rows("delisting_watch?select=symbol,announced_at,d0,title,kind&order=d0.asc,symbol.asc")
    print("delisting_watch rows:", len(dl), cr, flush=True)
    json.dump(dl, open(os.path.join(CACHE, "delisting.json"), "w"))
    outp = os.path.join(CACHE, "daily.csv")
    n = 0
    with open(outp, "w") as f:
        for i in range(0, len(coin_syms), 100):
            chunk = coin_syms[i:i + 100]
            path = ("perp_bv_daily?select=symbol,d,c,qv&symbol=in.("
                    + ",".join(chunk) + ")&order=symbol.asc,d.asc")
            rows, cr = get_rows(path)
            for r in rows:
                f.write("%s,%s,%s,%s\n" % (r["symbol"], r["d"], r["c"], r["qv"]))
            n += len(rows)
            print("chunk %d: %d rows (total %d)" % (i // 100, len(rows), n), flush=True)
    print("daily rows:", n, flush=True)


# ============================================================================= run
JUDGE_START = "2024-01-01"
JUDGE_END = "2026-08-31"
HORIZON = 60          # 天:标签窗口 (t, t+60]
K_PRIMARY = 50        # 预注册 K;K=20/100 只作描述
K_DESC = (20, 100)
NEED_DAYS = 90        # dd90 绑定:近 90 个有价日
DAYS_31 = 31          # 判定区间末周一后取价用的日历天数


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def _add_days(iso, n):
    y, m, d = (int(x) for x in iso.split("-"))
    return (date(y, m, d) + timedelta(days=n)).isoformat()


def _mondays(d0, d1):
    d = date(*(int(x) for x in d0.split("-")))
    end = date(*(int(x) for x in d1.split("-")))
    while d <= end:
        if d.weekday() == 0:
            yield d.isoformat()
        d += timedelta(days=1)


def load_prices(path):
    per = defaultdict(lambda: ([], [], []))
    with open(path) as f:
        for line in f:
            parts = line.rstrip("\n").split(",")
            if len(parts) != 4:
                continue
            sym, d, c, qv = parts
            c = _f(c)
            if c is None:
                continue
            days, closes, qvs = per[sym]
            days.append(d)
            closes.append(c)
            qvs.append(_f(qv) or 0.0)
    out = {}
    for sym, (days, closes, qvs) in per.items():
        order = sorted(range(len(days)), key=lambda i: days[i])
        out[sym] = ([days[i] for i in order], [closes[i] for i in order], [qvs[i] for i in order])
    return out


def build_events(pairs, tag, dlist):
    """事件表 + 永续匹配(精确 → 去掉代号前缀 → 去掉代号对应前缀的代号)。"""
    by_sym = defaultdict(list)
    for p in pairs:
        by_sym[p["symbol"]].append(p)
    rows = []
    ev_day = {}          # 永续代号 → 事件日
    ev_codes = defaultdict(list)
    for code in sorted(set(tag) | set(dlist)):
        srcs = []
        if code in tag:
            srcs.append("monitoring_tag")
        if code in dlist:
            srcs.append("delisting_watch")
        cands = [x for x in (tag.get(code), dlist.get(code)) if x]
        eday = min(cands)
        matched, rule = None, "unmatched"
        if code in by_sym:
            matched, rule = code, "exact"
        else:
            for pref in ("1000000", "1000"):
                if code.startswith(pref) and code[len(pref):] in by_sym:
                    matched, rule = code[len(pref):], "strip_code:" + pref
                    break
            if matched is None:
                for s in by_sym:
                    for pref in ("1000000", "1000"):
                        if s.startswith(pref) and s[len(pref):] == code:
                            matched, rule = s, "strip_pair:" + pref
                            break
                    if matched:
                        break
        kind = None
        if matched:
            kind = by_sym[matched][0].get("kind")
        in_uni = bool(matched) and kind == "coin"
        if in_uni:
            ev_codes[matched].append(code)
            ev_day[matched] = min(ev_day.get(matched, eday), eday)
        rows.append({
            "code": code, "event_day": eday, "source": "+".join(srcs),
            "tag_d0": tag.get(code) or "", "delist_d0": dlist.get(code) or "",
            "matched_symbol": matched or "", "match_rule": rule,
            "pair_kind": kind or "", "in_universe": int(in_uni),
        })
    return rows, ev_day, ev_codes


def run():
    import numpy as np
    from bisect import bisect_right, bisect_left
    from datetime import date, timedelta
    sys.path.insert(0, REPO)
    from src.data.state.window_vectors import window_vector
    from src.data.evaluation.apparatus import shuffle_within
    try:                                     # main 上没有就按预注册的后备公式
        from src.data.evaluation.apparatus import p_upper, content_fingerprint
    except ImportError:
        p_upper = None
        content_fingerprint = None

    t0 = time.time()
    pairs = json.load(open(os.path.join(CACHE, "pairs.json")))
    delisting = json.load(open(os.path.join(CACHE, "delisting.json")))
    tag = {}
    with open(EVENTS_CSV) as f:
        for r in csv.DictReader(f):
            s, d = r["symbol"], r["d0"]
            if s not in tag or d < tag[s]:
                tag[s] = d
    dlist = {}
    for r in delisting:
        s, d = r["symbol"], r["d0"]
        if s not in dlist or d < dlist[s]:
            dlist[s] = d
    ev_rows, ev_day, ev_codes = build_events(pairs, tag, dlist)
    print("事件: 代号 %d 个(标签 %d / 下架 %d);匹配进宇宙 %d 个"
          % (len(ev_rows), len(tag), len(dlist), len(ev_day)), flush=True)

    prices = load_prices(os.path.join(CACHE, "daily.csv"))
    coin = sorted({p["symbol"] for p in pairs if p["kind"] == "coin"})
    universe = [s for s in coin if s in prices]
    if MAXSYM:
        universe = universe[:MAXSYM]
    print("宇宙: kind=coin %d 个, 有价 %d 个" % (len(coin), len(universe)), flush=True)

    alld = sorted({d for s in universe for d in prices[s][0]})
    grid = list(_mondays(alld[0], alld[-1]))
    print("价格区间:", alld[0], "→", alld[-1], "| 周一格点", len(grid), flush=True)

    # ---- 样本表(全部周一;判定区间外的周一只做参照集)
    mond_idx = {m: i for i, m in enumerate(grid)}
    S = dict(sym=[], mon=[], y=[], shp=[], feat=[], gid=[])
    per_week = defaultdict(list)   # monday -> [global ids]
    n_missing = Counter()
    for s in universe:
        days, closes, qvs = prices[s]
        ed = ev_day.get(s)
        for m in grid:
            k = bisect_right(days, m)
            if k < NEED_DAYS:
                continue
            if days[k - 1] != m:            # 预注册:该币在 t 有收盘(死币不留)
                n_missing["no_close_at_t"] += 1
                continue
            if ed is not None and ed <= m:
                continue                      # 出过事件的币从事件日起退出
            shp = window_vector(closes[k - 61:k])
            if shp is None:
                n_missing["shape"] += 1
                continue
            w = qvs[k - 30:k]
            if min(w) <= 0:
                n_missing["qv"] += 1
                continue
            lr = [math.log(closes[j] / closes[j - 1]) for j in range(k - 30, k)]
            mu = sum(lr) / 30.0
            feat = [
                math.log(closes[k - 1] / closes[k - 31]),
                math.log(closes[k - 1] / closes[k - 61]),
                closes[k - 1] / max(closes[k - 90:k]) - 1.0,
                math.sqrt(sum((x - mu) ** 2 for x in lr) / 29.0),
                math.log(sum(w) / 30.0),
            ]
            if not all(math.isfinite(x) for x in feat):
                n_missing["feat"] += 1
                continue
            y = 1 if (ed is not None and m < ed <= _add_days(m, HORIZON)) else 0
            gid = len(S["sym"])
            S["sym"].append(s); S["mon"].append(m); S["y"].append(y)
            S["shp"].append(shp); S["feat"].append(feat); S["gid"].append(gid)
            per_week[m].append(gid)
    print("样本: 总 %d(缺 shape %d / qv %d / feat %d) 用时 %.0fs"
          % (len(S["sym"]), n_missing["shape"], n_missing["qv"], n_missing["feat"], time.time() - t0), flush=True)

    y_all = np.asarray(S["y"], dtype=float)
    mon_all = np.asarray(S["mon"], dtype=object)
    shp_all = np.asarray(S["shp"], dtype=float)
    feat_all = np.asarray(S["feat"], dtype=float)
    week_rows = {m: np.asarray(v, dtype=np.int64) for m, v in per_week.items()}

    eval_weeks = [m for m in grid if JUDGE_START <= m <= JUDGE_END]
    wrows_by_gidx = [np.asarray(per_week.get(m, []), dtype=np.int64) for m in grid]
    # 参照集:周一 ≤ t-60 天 ⇒ 前缀
    ref_prefix = []
    for m in eval_weeks:
        cut = _add_days(m, -HORIZON)
        ref_prefix.append(bisect_right(np.asarray(grid), cut))
    print("判定区间: %d 周 (%s → %s)" % (len(eval_weeks), eval_weeks[0], eval_weeks[-1]), flush=True)

    # ---- 两臂
    from sklearn.linear_model import LogisticRegression
    from sklearn.neighbors import NearestNeighbors
    from scipy.stats import rankdata

    def auc(y, s):
        y = np.asarray(y, dtype=float)
        if y.sum() == 0 or y.sum() == len(y):
            return float("nan")
        r = rankdata(np.asarray(s, dtype=float))
        npos = y.sum()
        return float((r[y == 1].sum() - npos * (npos + 1) / 2.0) / (npos * (len(y) - npos)))

    knn_scores, base_scores, knn_scores_desc = [], [], {k: [] for k in K_DESC}
    base_scores_desc = {k: [] for k in K_DESC}
    eval_ids, eval_weeks_lbl, ev_y = [], [], []
    neighbors_store = []
    week_stats = []
    for wi, m in enumerate(eval_weeks):
        eids = week_rows.get(m, np.asarray([], dtype=np.int64))
        if len(eids) == 0:
            week_stats.append({"week": m, "n": 0})
            continue
        rlim = ref_prefix[wi]
        rids = (np.concatenate([w for w in wrows_by_gidx[:rlim] if w.size])
                if rlim > 0 else np.asarray([], dtype=np.int64))
        if len(rids) < K_PRIMARY:
            week_stats.append({"week": m, "n": int(len(eids)), "ref": int(len(rids)), "skip": "ref<K"})
            continue
        yr = y_all[rids]
        if len(np.unique(yr)) < 2:
            week_stats.append({"week": m, "n": int(len(eids)), "pos": int(y_all[eids].sum()),
                               "ref": int(len(rids)), "ref_pos": int(yr.sum()),
                               "skip": "ref_single_class"})
            continue
        Rm = shp_all[rids]
        Em = shp_all[eids]
        nnb = min(100, len(rids))
        nn = NearestNeighbors(n_neighbors=nnb, metric="euclidean", algorithm="brute")
        nn.fit(Rm)
        _d, _i = nn.kneighbors(Em, n_neighbors=nnb)
        nb = rids[_i]                          # 全局行号,按距离升序
        neighbors_store.append((eids, nb))
        ky = y_all[nb[:, :K_PRIMARY]].mean(axis=1)
        knn_scores.append(ky)
        for kk in K_DESC:
            knn_scores_desc[kk].append(y_all[nb[:, :min(kk, nnb)]].mean(axis=1))
        # 基线:逻辑回归(参照集标准化,每周重拟合)
        Fr = feat_all[rids]
        mu, sd = Fr.mean(axis=0), Fr.std(axis=0)
        sd = np.where(sd <= 0, 1.0, sd)
        lr = LogisticRegression(C=1.0, max_iter=1000)
        lr.fit((Fr - mu) / sd, y_all[rids])
        pb = lr.predict_proba((feat_all[eids] - mu) / sd)[:, 1]
        base_scores.append(pb)
        eval_ids.append(eids); eval_weeks_lbl.append(np.full(len(eids), wi)); ev_y.append(y_all[eids])
        week_stats.append({
            "week": m, "n": int(len(eids)), "pos": int(y_all[eids].sum()),
            "ref": int(len(rids)), "ref_pos": int(y_all[rids].sum()),
        })
        if wi % 20 == 0:
            print("  week %d/%d %s n=%d pos=%d ref=%d (%.0fs)"
                  % (wi, len(eval_weeks), m, len(eids), int(y_all[eids].sum()), len(rids), time.time() - t0), flush=True)

    eval_ids = np.concatenate(eval_ids)
    knn = np.concatenate(knn_scores)
    base = np.concatenate(base_scores)
    yv = np.concatenate(ev_y)
    wk = np.concatenate(eval_weeks_lbl)
    knn_desc = {kk: np.concatenate(v) for kk, v in knn_scores_desc.items()}
    print("判定样本 %d(正 %d) 用时 %.0fs" % (len(yv), int(yv.sum()), time.time() - t0), flush=True)

    auc_knn = auc(yv, knn)
    auc_base = auc(yv, base)
    print("AUC kNN=%.4f  基线=%.4f  差=%+.4f" % (auc_knn, auc_base, auc_knn - auc_base), flush=True)

    # ---- (a) 周内打乱标签的零分布
    rng = np.random.default_rng(795)
    all_nb = np.concatenate([nb for _, nb in neighbors_store])
    all_eid = np.concatenate([eids for eids, _ in neighbors_store])
    null = []
    for _ in range(1000):
        py = shuffle_within(y_all, mon_all, rng).astype(float)
        sc = py[all_nb].mean(axis=1)
        null.append(auc(py[all_eid], sc))
    null = np.asarray(null)
    if p_upper is not None:
        p_a = p_upper(auc_knn, null)
        p_a_method = "apparatus.p_upper"
    else:
        p_a = float((1 + int((null >= auc_knn).sum())) / (1 + len(null)))
        p_a_method = "fallback:(1+#{null>=actual})/(1+n)"
    print("(a) AUC=%.4f p_upper=%.4f" % (auc_knn, p_a), flush=True)

    # ---- (b) 整周块自助
    rng2 = np.random.default_rng(795)
    by_w = [np.flatnonzero(wk == i) for i in range(len(eval_weeks))]
    diffs = []
    for _ in range(1000):
        pick = rng2.integers(0, len(eval_weeks), len(eval_weeks))
        ix = np.concatenate([by_w[p] for p in pick])
        diffs.append(auc(yv[ix], knn[ix]) - auc(yv[ix], base[ix]))
    diffs = np.asarray(diffs)
    ci = (float(np.quantile(diffs, 0.025)), float(np.quantile(diffs, 0.975)))

    # ---- (c) 两半
    nw = len(eval_weeks)
    h1 = np.concatenate([by_w[i] for i in range(nw // 2 + nw % 2)])
    h2 = np.concatenate([by_w[i] for i in range(nw // 2 + nw % 2, nw)])
    halves = {
        "h1": {"weeks": int(nw // 2 + nw % 2), "from": eval_weeks[0], "to": eval_weeks[nw // 2 + nw % 2 - 1],
               "n": int(len(h1)), "pos": int(yv[h1].sum()),
               "auc_knn": auc(yv[h1], knn[h1]), "auc_base": auc(yv[h1], base[h1]),
               "gap": auc(yv[h1], knn[h1]) - auc(yv[h1], base[h1])},
        "h2": {"weeks": int(nw - (nw // 2 + nw % 2)), "from": eval_weeks[nw // 2 + nw % 2], "to": eval_weeks[-1],
               "n": int(len(h2)), "pos": int(yv[h2].sum()),
               "auc_knn": auc(yv[h2], knn[h2]), "auc_base": auc(yv[h2], base[h2]),
               "gap": auc(yv[h2], knn[h2]) - auc(yv[h2], base[h2])},
    }

    # ---- (d) 金额:前 10% 两臂
    pos_of = {int(g): i for i, g in enumerate(eval_ids)}

    def money(scores):
        out = []
        for wi, m in enumerate(eval_weeks):
            ix = by_w[wi]
            if len(ix) == 0:
                continue
            rows_ = []
            for pos in ix:
                gi = int(eval_ids[pos])
                s = S["sym"][gi]
                days, closes, _ = prices[s]
                i0 = bisect_right(days, m)
                i1 = bisect_left(days, _add_days(m, DAYS_31))
                if i0 >= len(days) or i1 >= len(days) or i1 <= i0:
                    continue
                rows_.append((closes[i1] / closes[i0] - 1.0, int(pos)))
            if len(rows_) < 5:
                continue
            rets = np.asarray([r for r, _ in rows_])
            uni = float(rets.mean())
            k = max(5, int(math.ceil(0.10 * len(rows_))))
            top = sorted(rows_, key=lambda t: -scores[t[1]])[:k]
            out.append(float(np.mean([r for r, _ in top]) - uni))
        return np.asarray(out)

    mk = money(knn)
    mb = money(base)
    def dist(a):
        if len(a) == 0:
            return {}
        return {"mean_pp": float(a.mean() * 100), "median_pp": float(np.median(a) * 100),
                "p10_pp": float(np.percentile(a, 10) * 100), "p90_pp": float(np.percentile(a, 90) * 100),
                "weeks": int(len(a)), "n_pos_weeks": int((a < 0).sum())}

    # ---- 指纹
    fp_rows = []
    with open(os.path.join(CACHE, "daily.csv")) as f:
        for line in f:
            p = line.rstrip("\n").split(",")
            if len(p) == 4:
                fp_rows.append({"symbol": p[0], "d": p[1], "c": p[2], "qv": p[3]})

    def _fp_fallback(rows, fields):
        """main 上没有 content_fingerprint 时的后备:按 (symbol,d,c,qv) 排序后 sha256。"""
        def canon(v):
            if v is None:
                return None
            if isinstance(v, float):
                return None if not math.isfinite(v) else format(v, ".12g")
            return str(v)
        lines = sorted(json.dumps([canon(r.get(k)) for k in fields], ensure_ascii=False,
                                  separators=(",", ":")) for r in rows)
        h = hashlib.sha256()
        h.update(json.dumps(list(fields), ensure_ascii=False).encode("utf-8"))
        for ln in lines:
            h.update(b"\n")
            h.update(ln.encode("utf-8"))
        return {"n": len(lines), "fields": list(fields), "sha256": h.hexdigest()}

    fp_fields = ["symbol", "d", "c", "qv"]
    if content_fingerprint is not None:
        fp = content_fingerprint(fp_rows, fp_fields)
        fp["method"] = "apparatus.content_fingerprint"
    else:
        fp = _fp_fallback(fp_rows, fp_fields)
        fp["method"] = "fallback:sort(symbol,d,c,qv)+sha256"
    ev_fields = ["code", "event_day", "source", "matched_symbol", "match_rule"]
    if content_fingerprint is not None:
        ev_fp = content_fingerprint(ev_rows, ev_fields)
        ev_fp["method"] = "apparatus.content_fingerprint"
    else:
        ev_fp = _fp_fallback(ev_rows, ev_fields)
        ev_fp["method"] = "fallback:sort+sha256"
    print("指纹:", fp["sha256"][:16], fp["n"], flush=True)

    # 事件币的价格轨迹(给前向情景用):事件日收盘 / 最后收盘
    ev_examples = []
    for s, ed in sorted(ev_day.items(), key=lambda kv: kv[1], reverse=True):
        if s not in prices:
            continue
        days, closes, _ = prices[s]
        i = bisect_left(days, ed)
        if i >= len(days):
            continue
        ev_examples.append({"symbol": s, "event_day": ed, "close_at_event": closes[i],
                            "last_d": days[-1], "close_last": closes[-1],
                            "codes": ev_codes.get(s, [])})
        if len(ev_examples) >= 12:
            break

    res = {
        "card": "T-315", "spec": "S-795", "ran_at": datetime.now(timezone.utc).isoformat(),
        "judge_interval": {"from": eval_weeks[0], "to": eval_weeks[-1], "weeks": nw},
        "events": {
            "codes": len(ev_rows), "tag_codes": len(tag), "delist_codes": len(dlist),
            "matched": int(sum(r["in_universe"] for r in ev_rows)),
            "unmatched": int(sum(1 for r in ev_rows if not r["in_universe"])),
            "match_rules": dict(Counter(r["match_rule"] for r in ev_rows)),
            "event_symbols_in_universe": len(ev_day),
        },
        "universe": {"kind_coin": len(coin), "with_prices": len(universe),
                     "price_range": [alld[0], alld[-1]], "monday_grid": len(grid)},
        "panel": {"total_samples": len(S["sym"]), "missing": dict(n_missing),
                  "per_week": week_stats,
                  "n_weeks_with_pos": int(sum(1 for w in week_stats if w.get("pos", 0) > 0)),
                  "median_universe": float(np.median([w["n"] for w in week_stats if w.get("n")])),
                  "median_pos": float(np.median([w["pos"] for w in week_stats if "pos" in w])),
                  "total_pos": int(yv.sum())},
        "arms": {"auc_knn": auc_knn, "auc_base": auc_base, "gap": auc_knn - auc_base,
                 "auc_knn_K20": auc(yv, knn_desc[20]), "auc_knn_K100": auc(yv, knn_desc[100]),
                 "auc_base_desc": {str(kk): None for kk in K_DESC},
                 "n_eval": int(len(yv)), "n_pos": int(yv.sum())},
        "a": {"auc_knn": auc_knn, "p_upper": p_a, "p_method": p_a_method, "n_null": int(len(null)),
              "null_mean": float(null.mean()), "null_p95": float(np.percentile(null, 95)),
              "pass": bool(auc_knn >= 0.70 and p_a <= 0.01)},
        "b": {"gap": auc_knn - auc_base, "ci95": ci, "n_boot": 1000,
              "boot_mean": float(diffs.mean()), "boot_p_gt0": float((diffs > 0).mean()),
              "pass": bool((auc_knn - auc_base) >= 0.02 and ci[0] > 0)},
        "c": {"halves": halves,
              "pass": bool(halves["h1"]["auc_knn"] >= 0.65 and halves["h2"]["auc_knn"] >= 0.65
                           and halves["h1"]["gap"] > 0 and halves["h2"]["gap"] > 0)},
        "d": {"knn_top10": dist(mk), "base_top10": dist(mb),
              "gap_mean_pp": (dist(mk)["mean_pp"] - dist(mb)["mean_pp"]) if len(mk) and len(mb) else None,
              "pass": bool(len(mk) > 0 and dist(mk)["mean_pp"] <= -3.0
                           and len(mb) > 0 and (dist(mk)["mean_pp"] - dist(mb)["mean_pp"]) <= -1.0)},
        "fingerprints": {"daily": fp, "events": ev_fp},
        "event_examples": ev_examples,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    res["verdict"] = "PASS" if all(res[k]["pass"] for k in ("a", "b", "c", "d")) else "FAIL"
    json.dump(res, open(os.path.join(RESEARCH, "t315_results.json"), "w"), ensure_ascii=False, indent=2)
    json.dump({"per_week": week_stats, "events": ev_rows,
               "sample_total": len(S["sym"]), "universe": len(universe)},
              open(os.path.join(RESEARCH, "t315_panel.json"), "w"), ensure_ascii=False, indent=2)
    with open(os.path.join(RESEARCH, "t315_events.csv"), "w") as f:
        w = csv.DictWriter(f, fieldnames=["code", "event_day", "source", "tag_d0", "delist_d0",
                                          "matched_symbol", "match_rule", "pair_kind", "in_universe"])
        w.writeheader()
        for r in ev_rows:
            w.writerow(r)
    print("判定:", res["verdict"], json.dumps({k: res[k] for k in ("a", "b", "c", "d")}, ensure_ascii=False)[:900], flush=True)


if MODE == "probe":
    probe()
if MODE == "kinds":
    os.makedirs(CACHE, exist_ok=True)
    kinds()
if MODE == "fetch":
    fetch()
if MODE == "run":
    run()
