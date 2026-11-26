"""T-437 对账:口径 B(H20/L20 与结构位用高低价,与参考实现同)重跑 + 与 Seth 的 T-436 逐格对账。

用法: python3 docs/research/t437_recon.py
产物: docs/research/s916_blind_results_hl.json(口径 B 的 24 格)
      docs/research/t437_recon.md(逐格对账表)
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.insert(0, HERE)
import s916_blind as S  # noqa: E402  (只用它的函数,不重写)

CACHE = "/Volumes/CometCloudAI/cometcloud-local/research/t437/bars4h.json"
SETHA = "/Volumes/CometCloudAI/cometcloud-local/research/t437_s916_results_lanea.json"
OUT_HL = os.path.join(HERE, "s916_blind_results_hl.json")
OUT_MD = os.path.join(HERE, "t437_recon.md")


def ind_hl(bars):
    """口径 B:H20/L20 = 此前 20 根的最高/最低(高低价),结构位 = 含本根最近 10 根的最低/最高(低/高价)。"""
    ind = S.indicators(bars)
    h = pd.Series([b[2] for b in bars])
    l = pd.Series([b[3] for b in bars])
    ind["h20"] = h.rolling(20).max().shift(1).to_numpy()
    ind["l20"] = l.rolling(20).min().shift(1).to_numpy()
    ind["slo"] = l.rolling(10).min().to_numpy()
    ind["shi"] = h.rolling(10).max().to_numpy()
    return ind


def cell_map():
    spec = importlib.util.spec_from_file_location("s881", os.path.join(HERE, "s881_setup_mining.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.load_live()[1]


def build(ind_by_sym, cell):
    tk = {r["id"]: [] for r in S.RULES}
    ctrl = {1: [], -1: []}
    for s, b in ind_by_sym.items():
        for rule in S.RULES:
            t = S.run_lb(b, rule["side"]) if rule["kind"] == "LB" else S.run_br(b, rule["side"], rule["kind"] == "BRF")
            for x in t:
                x["cell"] = cell.get(x["d"] - dt.timedelta(days=1))
            tk[rule["id"]] += t
        for side in (1, -1):
            for x in S.run_ctrl(b, side):
                x["cell"] = cell.get(x["d"] - dt.timedelta(days=1))
                ctrl[side].append(x)
    rows = []
    for rule in S.RULES:
        side = rule["side"]
        for cn in S.CELLS:
            d = [t["r"] for t in tk[rule["id"]] if t["cell"] == cn and t["d"] <= S.SPLIT]
            h = [t["r"] for t in tk[rule["id"]] if t["cell"] == cn and t["d"] > S.SPLIT]
            cd = [t["r"] for t in ctrl[side] if t["cell"] == cn and t["d"] <= S.SPLIT]
            ch = [t["r"] for t in ctrl[side] if t["cell"] == cn and t["d"] > S.SPLIT]
            sd, sh = S.stats(d), S.stats(h)
            cdm = round(float(np.mean(cd)), 4) if cd else None
            chm = round(float(np.mean(ch)), 4) if ch else None
            ok_d = (sd["n"] >= S.MIN_N and sd["mean_R"] is not None and sd["mean_R"] > 0
                    and sd["payoff"] is not None and sd["payoff"] >= S.MIN_PAYOFF and cdm is not None and sd["mean_R"] > cdm)
            ok_h = (sh["n"] >= S.MIN_N and sh["mean_R"] is not None and sh["mean_R"] > 0
                    and sh["payoff"] is not None and sh["payoff"] >= S.MIN_PAYOFF and chm is not None and sh["mean_R"] > chm)
            rows.append({"rule": rule["id"], "cell": cn,
                         "disc": {**sd, "payoff": S.pf_json(sd["payoff"]), "ctrl_mean_R": cdm, "pass": bool(ok_d)},
                         "hold": {**sh, "payoff": S.pf_json(sh["payoff"]), "ctrl_mean_R": chm, "pass": bool(ok_h)},
                         "holds": bool(ok_d and ok_h)})
    return rows, {k: len(v) for k, v in tk.items()}, {k: len(v) for k, v in ctrl.items()}


def main():
    syms = json.load(open(CACHE))["symbols"]
    cell = cell_map()
    inds = {s: ind_hl(syms[s]) for s in S.SYMS if s in syms}
    rows, tkc, ctrc = build(inds, cell)
    json.dump({"card": "T-437", "variant": "口径B: H20/L20 与结构位用高低价", "rows": rows,
               "ticket_counts": tkc, "ctrl_counts": ctrc,
               "built_at": dt.datetime.now(dt.timezone.utc).isoformat()},
              open(OUT_HL, "w"), ensure_ascii=False, indent=1)

    setha = json.load(open(SETHA))
    sr = {(r["rule"], r["cell"]): r for r in setha["rows"]}
    mine = {(r["rule"], r["cell"]): r for r in rows}
    lines = ["# T-437 对账:我的盲复算 vs Seth 的 T-436(s916_results.json)", "",
             f"- 我的口径 B(`s916_blind_results_hl.json`)站得住 {sum(1 for r in rows if r['holds'])}/24;"
             f"Seth 的 {setha['n_holds']}/{setha['n_tested']}。", "",
             "| 规则 | 格 | 我的n(发现/留出) | 他的n | 我的均值R(发现/留出) | 他的均值R | 站得住(我/他) |",
             "|---|---|---|---|---|---|---|"]
    agree = 0
    ndiff = []
    for rule in S.RULES:
        for cn in S.CELLS:
            m = mine[(rule["id"], cn)]
            h = sr.get((rule["id"], cn))
            if h is None:
                continue
            hn = (h["disc"]["n"], h["hold"]["n"])
            hmn = (h["disc"]["mean_r"], h["hold"]["mean_r"])
            same = bool(m["holds"]) == bool(h["holds"])
            agree += same
            ndiff.append((rule["id"], cn, m["disc"]["n"], hn[0], m["hold"]["n"], hn[1], m["disc"]["mean_R"], hmn[0],
                          m["hold"]["mean_R"], hmn[1], m["holds"], h["holds"]))
            lines.append(f"| {rule['id']} | {cn} | {m['disc']['n']}/{m['hold']['n']} | {hn[0]}/{hn[1]} | "
                         f"{m['disc']['mean_R']}/{m['hold']['mean_R']} | {hmn[0]}/{hmn[1]} | "
                         f"{'HOLDS' if m['holds'] else '-'}/{'HOLDS' if h['holds'] else '-'} |")
    lines += ["", f"站得住名单一致 {agree}/24。", ""]
    open(OUT_MD, "w").write("\n".join(lines) + "\n")
    for r in ndiff:
        print(f"{r[0]:6s} {r[1]} | n {r[2]}/{r[4]} vs {r[3]}/{r[5]} | m {r[6]}/{r[8]} vs {r[7]}/{r[9]} | "
              f"{'HOLDS' if r[10] else '-':5s}/{'HOLDS' if r[11] else '-'} | same={r[10] == r[11]}")
    print("agree", agree, "/24 | mine holds", sum(1 for r in rows if r["holds"]), "| his holds", setha["n_holds"])
    print("ticket_counts", tkc, "ctrl", ctrc)
    print("WROTE", OUT_HL, OUT_MD)


if __name__ == "__main__":
    main()
