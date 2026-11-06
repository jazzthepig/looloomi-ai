#!/usr/bin/env python3
"""T-266 指纹探针:定位 `feature_restricted` 为什么对不上 T-263 的 b9986ac…62dce。

候选解释只有两种,本脚本把两种分开:
  (1) 行数/列集口径差 —— T-263 哈希的是 2053 行(合并前)还是 2052 行(合并后)?列集是 59 还是今天的 71?
  (2) 值变了 —— 物化视图每小时刷新、滚动窗口列会变,同一列集在同一日期上的值可能已经不同。
      判据:把 T-263 报告里的每列「有值天数 / 缺值率 / 起始 / 截止」与今天实测逐列对比;
      只要有一列对不上,(2) 成立,不需要再看哈希。

只读库、只读缓存;不改库、不改代码。
"""
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import t266_recompute as T  # noqa: E402  (复用读库/口径常量)

T263_FP = T.T263_FP_FEATURE
MD = "/Users/sbb/Projects/looloomi-ai/docs/research/T-263_joint_model_v2.md"


def fp(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def main() -> None:
    keys = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "t266_keys_t263.json")))
    ks = set(keys)

    fm = T.load_features()                       # 今天的原始行(窗口内全部)
    perp = T.load_perp()
    px = {r["d"]: float(r["c"]) for r in perp}

    raw = [[r["d"], r.get("f") or {}] for r in fm]
    raw59 = [[d, {k: v for k, v in f.items() if k in ks}] for d, f in raw]

    seen, joined = set(), []
    for r in fm:
        d = r["d"]
        if d not in px or d in seen:
            continue
        seen.add(d)
        joined.append([d, r.get("f") or {}])
    joined59 = [[d, {k: v for k, v in f.items() if k in ks}] for d, f in joined]

    # 模型真正用到的行:目标需要 d+30 行价格 ⇒ 样本止于 SAMPLE_END。
    # 指纹若覆盖到今天(视图每小时刷新、尾部行每天变),就会与上一轮不同,而模型行不变。
    dates, X, y, r30, months, rows, pxd = T.build_sample(keys)
    sample_end = max(dates)
    model_raw = [[d, f] for d, f in raw if d <= sample_end]
    model_raw59 = [[d, {k: v for k, v in f.items() if k in ks}] for d, f in model_raw]
    model_joined = [[d, f] for d, f in joined if d <= sample_end]
    model_joined59 = [[d, {k: v for k, v in f.items() if k in ks}] for d, f in model_joined]

    # 「稠密」候选:每行都带上全部 59 个键(缺的补 None)。
    # 模型里 f.get(k) 对「键缺失」与「键存在但为 null」都读到 None ⇒ 模型数字一样,
    # 但 json.dumps 出来的串不同 ⇒ 指纹会变。这一条能区分「值变了」与「键的稠密度变了」。
    ks_sorted = sorted(ks)
    joined_dense = [[d, {k: f.get(k) for k in ks_sorted}] for d, f in joined]
    raw_dense = [[d, {k: f.get(k) for k in ks_sorted}] for d, f in raw]
    model_dense = [[d, {k: f.get(k) for k in ks_sorted}] for d, f in joined if d <= sample_end]

    cands = {
        "raw_rows_all_cols": fp(raw),
        "raw_rows_59cols": fp(raw59),
        "joined_rows_all_cols": fp(joined),
        "joined_rows_59cols": fp(joined59),
        "model_rows_all_cols": fp(model_joined),
        "model_rows_59cols": fp(model_joined59),
        "raw_upto_sample_end_all_cols": fp(model_raw),
        "raw_upto_sample_end_59cols": fp(model_raw59),
        "joined_rows_59cols_dense": fp(joined_dense),
        "raw_rows_59cols_dense": fp(raw_dense),
        "model_rows_59cols_dense": fp(model_dense),
    }
    # 每行 jsonb 键数分布(今天的视图):稠密 or 稀疏
    kc = {}
    for d, f in joined:
        kc[len(f)] = kc.get(len(f), 0) + 1
    out_extra = {"sample_end": sample_end, "n_model_rows": len(model_joined),
                 "n_rows_after_sample_end": len(joined) - len(model_joined),
                 "per_row_nkeys_distribution": dict(sorted(kc.items()))}
    out = {
        "n_raw_rows": len(raw),
        "n_joined_rows": len(joined),
        "raw_date_min": raw[0][0], "raw_date_max": raw[-1][0],
        "joined_date_min": joined[0][0], "joined_date_max": joined[-1][0],
        "t263_feature_fingerprint": T263_FP,
        "candidates": cands,
        "matches": {k: (v == T263_FP) for k, v in cands.items()},
        "n_keys_in_view_today": len(raw[0][1]),
        **out_extra,
    }

    # ---- (2) 值变了吗:逐列覆盖度对比 T-263 报告的表 ----
    md_txt = open(MD).read()
    pat = re.compile(r"^\|\s*\d+\s*\|\s*`([^`]+)`\s*\|\s*(\S+)\s*\|\s*(\d+)\s*/\s*(\d+)\s*\|\s*([\d.]+)\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|",
                     re.M)
    md_cov = {m.group(1): {"nonnull": int(m.group(3)), "total": int(m.group(4)),
                           "miss": float(m.group(5)), "start": m.group(6), "end": m.group(7)}
              for m in pat.finditer(md_txt)}

    today = {}
    for d, f in raw:
        for k in ks:
            v = f.get(k)
            if v is not None and v == v:
                e = today.setdefault(k, {"n": 0, "first": d, "last": d})
                e["n"] += 1
                e["first"] = min(e["first"], d)
                e["last"] = max(e["last"], d)

    diffs = []
    for k, m in md_cov.items():
        t = today.get(k, {"n": 0, "first": None, "last": None})
        row = {"key": k,
               "md_nonnull": m["nonnull"], "today_nonnull": t["n"],
               "md_total": m["total"], "today_total": len(raw),
               "md_start": m["start"], "today_start": t["first"],
               "md_end": m["end"], "today_end": t["last"]}
        row["differs"] = bool(m["nonnull"] != t["n"] or m["start"] != t["first"] or m["end"] != t["last"])
        diffs.append(row)
    out["n_cols_compared"] = len(diffs)
    out["n_cols_differing"] = sum(1 for r in diffs if r["differs"])
    out["cols_differing"] = [r for r in diffs if r["differs"]][:20]

    print(json.dumps(out, ensure_ascii=False, indent=1))
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "t266_fp_probe.json"), "w") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
