"""S-877:哪些维度带着「该拿哪些策略」的信息 —— 把 T × L 里的 L 轴逐个换成向量的 56 个键,用**已经站住的那套做法**量。

S-875 / S-876:向量邻域 + 之后 60 天 + 每月选一次,这套做法连在 T × L 自己的两个轴上都不行(2 维的连续版落在安慰剂 12 分位)——
坏的是做法,不是向量。站住的做法是:**状态按天、按阈值切成格子,策略看状态内的收益,逐月向前重算名单**(S-871 / S-873)。
这里就用它挖维度:状态 = 「线上 / 线下」×「键 k 高 / 低」(高低 = k 当天的按时点 z 是否 > 0);每个 k 报
  均值 / 波动、比「只看线上 / 线下」多多少、前后两半各自多多少、以及**只平移 k 这条轴**的安慰剂分位(T 轴不动 —— 量的是 k 在趋势之外的增量)。
预期、选法与后果写在台账 S-877(先登记,后计算)。结果逐键追加到 `s877_progress.jsonl`,中断后重跑会接着做。

用法(仓库根目录):
    python3 docs/research/s877_axis_mining.py --selftest
    nohup python3 docs/research/s877_axis_mining.py > docs/research/s877_run.txt 2>&1 &     # 约 45 分钟;写 s877_results.json
    python3 docs/research/s877_axis_mining.py --keys k1,k2 --drop-strategies style_ --tag nostyle   # 复核:只跑几个键、面板去掉某些策略
                                                                                                    # (写 s877_results_nostyle.json,不续跑)
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
_argv, sys.argv = sys.argv, [sys.argv[0], "--rules", "v2"]
_sp = importlib.util.spec_from_file_location("s869", os.path.join(HERE, "s869_strategy_state.py"))
M = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(M)
sys.argv = _argv
_fp = importlib.util.spec_from_file_location("fused_knn", os.path.join(ROOT, "src", "data", "state", "fused_knn.py"))
FK = importlib.util.module_from_spec(_fp)
_fp.loader.exec_module(FK)

OUT, PROG = "docs/research/s877_results.json", "docs/research/s877_progress.jsonl"
N_PLACEBO, SEED, MIN_SHIFT = 60, 877, 180
PCT_LINE = 0.95


def states_for(t_axis: dict, hi: dict) -> dict:
    """{日: {'T','L','R','W'}} —— 借 S-869 的 T × L 机器:把「k 低」放在 L=抽、「k 高」放在 L=注;R / W 填常数。"""
    return {d: {"T": t_axis[d], "L": "注" if hi[d] else "抽", "R": "升", "W": "好"} for d in t_axis if d in hi}


def book(states: dict, panel: dict, scaled: dict) -> dict:
    return M.walk(states, M.month_tables(states, panel), scaled, M.G2, "cond")["series"]


def halves(series: dict) -> tuple[float, float]:
    ds = sorted(series)
    mid = ds[len(ds) // 2]
    return (M.perf({d: series[d] for d in ds if d <= mid}).get("ratio", 0.0), M.perf({d: series[d] for d in ds if d > mid}).get("ratio", 0.0))


def shift_axis(hi: dict, k: int) -> dict:
    ds = sorted(hi)
    v = [hi[d] for d in ds]
    return {d: v[(i - k) % len(ds)] for i, d in enumerate(ds)}


def one_key(name: str, t_axis: dict, hi: dict, panel: dict, scaled: dict, base: dict, rng, n_placebo: int) -> dict:
    st = states_for(t_axis, hi)
    s = book(st, panel, scaled)
    r, (h1, h2) = M.perf(s).get("ratio", 0.0), halves(s)
    n = len(hi)
    pl = np.array([M.perf(book(states_for(t_axis, shift_axis(hi, int(k))), panel, scaled)).get("ratio", 0.0)
                   for k in rng.integers(MIN_SHIFT, n - MIN_SHIFT, n_placebo)])
    return {"key": name, "n_days": len(st), "share_high": round(float(np.mean(list(hi.values()))), 3), "ratio": round(float(r), 3),
            "minus_T_only": round(float(r - base["ratio"]), 3), "half1_minus_T": round(float(h1 - base["h1"]), 3), "half2_minus_T": round(float(h2 - base["h2"]), 3),
            "placebo_pct": round(float((pl < r).mean()), 3), "placebo_median": round(float(np.median(pl)), 3),
            "passes": bool((pl < r).mean() >= PCT_LINE and h1 > base["h1"] and h2 > base["h2"])}


def run(t_axis: dict, axes: dict, panel: dict, n_placebo: int = N_PLACEBO, resume: bool = False) -> dict:
    scaled = M._scaled(panel)
    t_only = M.walk({d: {"T": t_axis[d], "L": "注", "R": "升", "W": "好"} for d in t_axis},
                    M.month_tables({d: {"T": t_axis[d], "L": "注", "R": "升", "W": "好"} for d in t_axis}, panel), scaled, M.T_LEVEL, "cond")["series"]
    b1, b2 = halves(t_only)
    base = {"ratio": float(M.perf(t_only).get("ratio", 0.0)), "h1": float(b1), "h2": float(b2)}
    done = {}
    if resume and os.path.exists(PROG):
        for line in open(PROG, encoding="utf-8"):
            row = json.loads(line)
            done[row["key"]] = row
    rng = np.random.default_rng(SEED)
    rows = []
    for name, hi in axes.items():
        seed_draw = rng.integers(0, 2 ** 31)                              # 每个键一颗固定的种子:续跑与一次跑完的数相同
        if name in done:
            rows.append(done[name])
            continue
        row = one_key(name, t_axis, hi, panel, scaled, base, np.random.default_rng(int(seed_draw)), n_placebo)
        rows.append(row)
        if resume:
            with open(PROG, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print("KEY", json.dumps(row, ensure_ascii=False), flush=True)
    rows.sort(key=lambda x: -x["placebo_pct"])
    return {"T_only": base, "n_keys": len(rows), "n_pass": sum(r["passes"] for r in rows), "n_pct_ge_95": sum(r["placebo_pct"] >= PCT_LINE for r in rows),
            "expected_by_chance_pct_ge_95": round(len(rows) * (1 - PCT_LINE), 1), "keys": rows, "n_strategies": len(panel)}


def load_live():
    sp = importlib.util.spec_from_file_location("s851", os.path.join(HERE, "s851_watch_base_rate.py"))
    S = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(S)
    rows = S.get("feature_matrix_daily", {"select": "d,f", "d": "gte.2019-01-01", "order": "d.asc"})
    z = {dt.date.fromisoformat(k): v for k, v in FK.pit_vectors(rows).items()}
    raw = {dt.date.fromisoformat(str(r["d"])[:10]): (r.get("f") or {}) for r in rows}
    t_axis = {d: ("线下" if float(f["dist_200"]) < 0 else "线上") for d, f in raw.items() if f.get("dist_200") is not None}
    axes = {}
    for j, k in enumerate(FK.KEYS):
        if k == "dist_200":
            continue
        axes[k] = {d: bool(v[j] > 0) for d, v in z.items() if v[j] is not None and d in t_axis}
    axes["REF:stable_supply_30d_raw_sign"] = {d: bool(float(f["stable_supply_30d"]) >= 0) for d, f in raw.items()
                                             if f.get("stable_supply_30d") is not None and d in t_axis}      # = 原来的 L 轴;应接近 1.0
    return t_axis, {k: v for k, v in axes.items() if len(v) >= 1500}


def synthetic():
    rng = np.random.default_rng(SEED)
    states, panel = M.synthetic()
    days = sorted(states)
    t_axis = {d: states[d]["T"] for d in days}
    # useful:把 L 当成第二轴,并让一条策略只在「线上 × L=注」有超额;noise:与收益无关的持续二元序列
    lsig = {d: states[d]["L"] == "注" for d in days}
    one = dt.timedelta(days=1)
    def mu(d):                                                             # 线上·注 好、线上·抽 坏、线下 无:只看线上 / 线下 看不出来
        p = states.get(d - one, {})
        return 0.0 if p.get("T") != "线上" else (0.009 if lsig.get(d - one) else -0.007)
    panel["needs_both"] = {d: float(rng.normal(mu(d), 0.02)) for d in days[1:]}
    noise, cur = {}, True
    for d in days:
        cur = (not cur) if rng.random() < 1 / 60 else cur
        noise[d] = cur
    return t_axis, {"useful": lsig, "noise": noise}, panel


if __name__ == "__main__":
    selftest = "--selftest" in sys.argv
    if selftest:
        t_axis, axes, panel = synthetic()
        out = run(t_axis, axes, panel, n_placebo=20)
        rows = {r["key"]: r for r in out["keys"]}
        # 四格比两格学得慢(每格要攒够五段),所以前一半会吃亏;有用的轴在后一半必须赢过「只看线上 / 线下」,且比噪声轴更靠前
        assert rows["useful"]["half2_minus_T"] > 0 and rows["useful"]["placebo_pct"] >= rows["noise"]["placebo_pct"], rows
        assert rows["useful"]["ratio"] > rows["noise"]["ratio"], rows
        print("T_ONLY", json.dumps(out["T_only"]), "| useful", rows["useful"]["ratio"], rows["useful"]["placebo_pct"], "| noise", rows["noise"]["ratio"], rows["noise"]["placebo_pct"])
        print("SELFTEST OK")
    else:
        t_axis, axes = load_live()
        panel, _ = M.load_panel()
        arg = lambda name: sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None      # noqa: E731
        if arg("--keys"):
            want = arg("--keys").split(",")
            axes = {k: v for k, v in axes.items() if k in want}
        if arg("--drop-strategies"):
            pre = tuple(arg("--drop-strategies").split(","))
            panel = {k: v for k, v in panel.items() if not k.startswith(pre)}
        tag = arg("--tag")
        if tag:
            OUT = f"docs/research/s877_results_{tag}.json"
        out = run(t_axis, axes, panel, resume=not tag)
        print("T_ONLY", json.dumps(out["T_only"]), flush=True)
        print("SUMMARY", json.dumps({k: out[k] for k in ("n_keys", "n_pass", "n_pct_ge_95", "expected_by_chance_pct_ge_95", "n_strategies")}), flush=True)
        for r in out["keys"][:12]:
            print("TOP", json.dumps(r, ensure_ascii=False), flush=True)
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
        print("WROTE", OUT)
