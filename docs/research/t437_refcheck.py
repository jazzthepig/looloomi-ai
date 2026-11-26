"""T-437 归因实验:用 Seth 的参考实现(T-436 的 s916_jazz_4h_rules.py)跑我自己的 4h 缓存。

目的:把「我的盲复算 vs Seth 的 T-436」这 24 格差异拆成 ①数据差异 ②实现口径差异。
做法:不重写任何规则,直接 import 参考实现,喂我抓的 bars 缓存 —— 于是输出的每一格都是
     「Seth 的逻辑 + 我的数据」。把它与 ①Seth 的数据 + Seth 的逻辑(s916_results.json)
     和 ②我的数据 + 我的逻辑(s916_blind_results_hl.json)分别对账。

产物:docs/research/t437_refcheck.json
      docs/research/t437_refcheck.md
用法:python3 docs/research/t437_refcheck.py
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

CACHE = "/Volumes/CometCloudAI/cometcloud-local/research/t437/bars4h.json"
SETHA = "/Volumes/CometCloudAI/cometcloud-local/research/t437_s916_results_lanea.json"   # Seth 的 T-436 结果
MINE_A = os.path.join(HERE, "s916_blind_results.json")     # 我的口径 A(收盘口径)
MINE_B = os.path.join(HERE, "s916_blind_results_hl.json")  # 我的口径 B(高低价口径)
OUT_JSON = os.path.join(HERE, "t437_refcheck.json")
OUT_MD = os.path.join(HERE, "t437_refcheck.md")
REF_LOCAL = os.path.join(HERE, "_s916_ref.py")             # 参考实现的本地副本(不提交)


def load_ref():
    """参考实现:优先本地副本,否则从 origin/lane-a/T-436 现取(不落仓库)。"""
    path = REF_LOCAL
    if not os.path.exists(path):
        fd, path = tempfile.mkstemp(suffix="_s916_ref.py")
        with os.fdopen(fd, "w") as f:
            src = subprocess.run(
                ["git", "-C", os.path.abspath(os.path.join(HERE, "..", "..")),
                 "show", "origin/lane-a/T-436:docs/research/s916_jazz_4h_rules.py"],
                capture_output=True, text=True, check=True).stdout
            f.write(src)
    spec = importlib.util.spec_from_file_location("s916_ref", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def bars_from_cache(raw: dict) -> dict:
    """我的缓存 [[ts,o,h,l,c]] → 参考实现要的 {t:[datetime], o,h,l,c}。"""
    out = {}
    for sym, rows in raw["symbols"].items():
        t = [dt.datetime.fromtimestamp(int(r[0]), dt.timezone.utc) for r in rows]
        out[sym] = {"t": t,
                    "o": np.array([r[1] for r in rows], float),
                    "h": np.array([r[2] for r in rows], float),
                    "l": np.array([r[3] for r in rows], float),
                    "c": np.array([r[4] for r in rows], float)}
    return out


def load_cell():
    spec = importlib.util.spec_from_file_location("s881", os.path.join(HERE, "s881_setup_mining.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.load_live()[1]


def idx(rows):
    return {(r["rule"], r["cell"]): r for r in rows}


def main():
    X = load_ref()
    bars = bars_from_cache(json.load(open(CACHE)))
    cell = load_cell()

    tk, bl = {r: [] for r in X.RULES}, {1: [], -1: []}
    for sym, b in bars.items():
        ind = X.indicators(b)
        for r in X.RULES:
            tk[r] += X.tickets(b, ind, r)
        for side in (1, -1):
            bl[side] += X.baseline(b, ind, side)
    rows = X.scan(tk, bl, cell)

    his = idx(json.load(open(SETHA))["rows"])
    mine_b = idx(json.load(open(MINE_B))["rows"])
    mine_a = idx(json.load(open(MINE_A))["rows"])

    out_rows, lines = [], []
    lines += ["# T-437 归因:参考实现跑我的数据 vs 参考实现跑他的数据 vs 我的实现跑我的数据", "",
              f"- 参考实现 + 我的缓存:站得住 {sum(1 for r in rows if r['holds'])}/24",
              f"- 参考实现 + 他的数据(s916_results.json):站得住 {json.load(open(SETHA))['n_holds']}/24",
              f"- 我的实现 + 我的缓存(口径 B,高低价):站得住 {sum(1 for r in json.load(open(MINE_B))['rows'] if r['holds'])}/24",
              f"- 我的实现 + 我的缓存(口径 A,收盘):站得住 {sum(1 for r in json.load(open(MINE_A))['rows'] if r['holds'])}/24",
              "",
              "| 规则 | 格 | 参考+我 n(发现/留出) | 参考+他 n | 我的口径B n | 参考+我 均值R | 参考+他 均值R | 我的口径B 均值R | 站得住(参/他/我B) |",
              "|---|---|---|---|---|---|---|---|---|"]
    n_ref_his = n_ref_mine = 0
    for r in rows:
        key = (r["rule"], r["cell"])
        h, mb = his.get(key), mine_b.get(key)
        ha = mine_a.get(key)
        holds_ref, holds_his = bool(r["holds"]), bool(h["holds"]) if h else None
        holds_mb = bool(mb["holds"]) if mb else None
        n_ref_his += int(holds_ref == holds_his)
        n_ref_mine += int(holds_ref == holds_mb)
        out_rows.append({
            "rule": r["rule"], "cell": r["cell"],
            "ref_mine": {"n_disc": r["disc"].get("n", 0), "n_hold": r["hold"].get("n", 0),
                         "mean_disc": r["disc"].get("mean_r"), "mean_hold": r["hold"].get("mean_r"),
                         "holds": holds_ref},
            "ref_his": {"n_disc": h["disc"].get("n", 0) if h else None, "n_hold": h["hold"].get("n", 0) if h else None,
                        "mean_disc": h["disc"].get("mean_r") if h else None,
                        "mean_hold": h["hold"].get("mean_r") if h else None,
                        "holds": holds_his},
            "mine_b": {"n_disc": mb["disc"]["n"] if mb else None, "n_hold": mb["hold"]["n"] if mb else None,
                       "mean_disc": mb["disc"]["mean_R"] if mb else None,
                       "mean_hold": mb["hold"]["mean_R"] if mb else None,
                       "holds": holds_mb},
            "mine_a": {"n_disc": ha["disc"]["n"] if ha else None, "n_hold": ha["hold"]["n"] if ha else None,
                       "mean_disc": ha["disc"]["mean_R"] if ha else None,
                       "mean_hold": ha["hold"]["mean_R"] if ha else None,
                       "holds": bool(ha["holds"]) if ha else None},
        })
        lines.append(
            f"| {r['rule']} | {r['cell']} | {r['disc'].get('n',0)}/{r['hold'].get('n',0)} | "
            f"{h['disc'].get('n',0) if h else '-'}/{h['hold'].get('n',0) if h else '-'} | "
            f"{mb['disc']['n'] if mb else '-'}/{mb['hold']['n'] if mb else '-'} | "
            f"{r['disc'].get('mean_r')}/{r['hold'].get('mean_r')} | "
            f"{h['disc'].get('mean_r') if h else '-'}/{h['hold'].get('mean_r') if h else '-'} | "
            f"{mb['disc']['mean_R'] if mb else '-'}/{mb['hold']['mean_R'] if mb else '-'} | "
            f"{'HOLDS' if holds_ref else '-'}/{'HOLDS' if holds_his else '-'}/{'HOLDS' if holds_mb else '-'} |")

    lines += ["", f"参考实现 + 我的数据 vs 参考实现 + 他的数据:站得住判定一致 {n_ref_his}/24"
                  f"(⇒ 数据差异对结论的影响)", "",
              f"参考实现 + 我的数据 vs 我的实现 + 我的数据:站得住判定一致 {n_ref_mine}/24"
              f"(⇒ 剩下的全是实现口径差异)", ""]
    open(OUT_MD, "w").write("\n".join(lines) + "\n")
    json.dump({"built_at": dt.datetime.now(dt.timezone.utc).isoformat(),
               "ref_on_my_data": {"n_holds": sum(1 for r in rows if r["holds"]), "rows": out_rows},
               "ref_vs_his_holds_agree": n_ref_his,
               "ref_vs_mine_b_holds_agree": n_ref_mine},
              open(OUT_JSON, "w"), ensure_ascii=False, indent=1)
    for o in out_rows:
        if not (o["ref_mine"]["holds"] == o["ref_his"]["holds"] == o["mine_b"]["holds"]):
            print("DIFF", o["rule"], o["cell"], o["ref_mine"], o["ref_his"], o["mine_b"])
    print("ref+my holds", sum(1 for r in rows if r["holds"]),
          "| ref+his holds", json.load(open(SETHA))["n_holds"],
          "| my(B) holds", sum(1 for r in json.load(open(MINE_B))["rows"] if r["holds"]))
    print("agree ref-vs-his", n_ref_his, "/24 | agree ref-vs-mineB", n_ref_mine, "/24")
    print("WROTE", OUT_JSON, OUT_MD)


if __name__ == "__main__":
    main()
