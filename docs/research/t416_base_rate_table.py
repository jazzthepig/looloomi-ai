"""T-416:把 T-408(S-881 那 8 张基率表)按 S-882「每张基率表必须自带对照组」重出,再判一次那 1 格「站住」的是信号还是基率。

T-408 报:8 格测过、1 格报「站住」(BO20|线上·主流领),整条序列平移零分布 n = 100、cell 中位 1 / q95 2 / p_cell_ge_real = 0.86;
crowd 7 格测过、3 格报「站住」,但 p_crowd_ge_real = 0.0 里有两行逐位同数、一行 n = 9 / pf = 99.0(退化)。
问题:那 8 张表是各自手搓的、**没有并排的对照组**(S-882 同一个病:不带条件的全部样本 + 只满足一半条件的样本都没有,常态会被读成形态)。

口径(全部写死在本文件里;不引 T-408 的读数当结论,自己从库里重算,并核一遍能不能复现它):
  样本   一张票 = 一次进场(D 日收盘判、D + 1 开盘进、8% 止损、28 天、一次进满;走法与 S-879 / S-881 同一套)
  宇宙   分方向:多头宇宙 = BO20 触发票 + EVERY5 日历票;空头宇宙 = BD20 触发票 + EVERY5 日历票
  条件组 触发(BO20 突破 / BD20 跌破)且状态格 = 该格
  对照组 base_rate_table 强制至少一个半条件组(S-882);这里给三组 + 它自动加的「全部样本」
        触发_其它状态 —— 只满足「触发」那一半(状态是别的格子)
        状态_日历同格 —— 只满足「状态」那一半(同格同方向的每 5 天日历票;= T-408 的 base)
        状态格_全部票 —— 该状态格里的全部票(触发 + 日历)
  结局   win(净收益 > 0)/ loss / stopped(被打止损)/ r_ge_1(打出过一个止损单位的盈利)
  零分布 整条状态序列循环平移 ≥ 180 天(apparatus.circular_shift)→ 每个格「条件组 − 对照组」差的零分布
          p = apparatus.p_upper(实际差, 零分布)(单侧:实际差偏大才算显著;带 +1 修正)
  判定   「差值过线」且「p 过线」才算有信号:差值 > 0 且 p ≤ 0.05(两个门都要过)
  敏感性 状态标签挪一天(用 D − 1 的状态而不是 D 的)重判一遍(同日派生量的纪律)

用法(仓库根目录):
    nohup python3 docs/research/t416_base_rate_table.py > docs/research/t416_run.txt 2>&1 &
写 docs/research/t408_base_rate_table.json
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys
import urllib.parse
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    sys.exit("需要 SUPABASE_URL / SUPABASE_KEY")

OUT = os.path.join(HERE, "t408_base_rate_table.json")
T408 = os.path.join(HERE, "s881_results.json")
P_GATE = 0.05            # p 的门
N_NULL = 200             # 零分布抽样次数(平移 ≥ 180 天)
SEED = 4160
MIN_SHIFT = 180          # 平移下限(天):S-864 / S-866 的规矩
TINY_N = 20              # 退化判据:票数小于此数
HUGE_PAYOFF = 20.0       # 退化判据:盈亏比大于此数(99.0 = 一张没亏)


def _load(name, path):
    sp = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


apparatus = _load("apparatus", os.path.join(ROOT, "src", "data", "evaluation", "apparatus.py"))
S881 = _load("s881", os.path.join(HERE, "s881_setup_mining.py"))

CELLS = S881.CELLS
CROWD = S881.CROWD
LEAD_KEY = S881.LEAD_KEY
Z_CUT = S881.Z_CUT
SPLIT = S881.SPLIT
END = S881.END
T = S881.T
G = S881.G


# ── 取数(带总行数核对;每页 1000 行 + order=)─────────────────────────────────
def fetch_all(path: str, params: dict) -> tuple[list, int | None]:
    base = URL.rstrip("/") + "/rest/v1/" + path
    out, off, total = [], 0, None
    while True:
        h = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}
        if off == 0:
            h["Prefer"] = "count=exact"
        q = urllib.parse.urlencode({**params, "limit": 1000, "offset": off})
        req = urllib.request.Request(base + "?" + q, headers=h)
        with urllib.request.urlopen(req, timeout=300) as r:
            rows = json.loads(r.read())
            cr = r.headers.get("Content-Range")
        if off == 0 and cr and "/" in cr:
            tail = cr.rsplit("/", 1)[-1]
            if tail.isdigit():
                total = int(tail)
        out += rows
        if len(rows) < 1000:
            break
        off += 1000
    if total is not None and len(out) != total:
        raise SystemExit(f"{path}: 抓到 {len(out)} 行,库里 {total} 行 —— 不算数")
    return out, total


def load_state():
    """状态格 + 人群读数(与 T-408 同一口径:面板离 200 日线 × 谁在领 / 四个持仓读数的按时点 z)。"""
    rows, total = fetch_all("feature_matrix_daily", {"select": "d,f", "d": "gte.2019-01-01", "order": "d.asc"})
    z = {dt.date.fromisoformat(k): v for k, v in S881.FK.pit_vectors(rows).items()}
    raw = {dt.date.fromisoformat(str(r["d"])[:10]): (r.get("f") or {}) for r in rows}
    j = S881.FK.KEYS.index(LEAD_KEY)
    cell = {}
    for d, v in z.items():
        x = raw.get(d, {}).get("dist_200")
        if x is not None and v[j] is not None:
            cell[d] = ("线下" if float(x) < 0 else "线上") + "·" + ("主流领" if v[j] > 0 else "二线领")
    crowd = {}
    for k in CROWD:
        i = S881.FK.KEYS.index(k)
        crowd[k] = {d: ("lo" if v[i] < -Z_CUT else "hi" if v[i] > Z_CUT else "mid") for d, v in z.items() if v[i] is not None}
    return cell, crowd, total


def load_prices():
    data = {}
    for a in T.ASSETS:
        rows, total = fetch_all("ohlcv_daily", {"select": "trade_date,open,high,low,close", "symbol": f"eq.{a}",
                                                "source": "eq.binance_hist", "trade_date": "gte.2018-06-01",
                                                "order": "trade_date.asc"})
        rows = [r for r in rows if all(r.get(k) is not None for k in ("open", "high", "low", "close"))]
        days = [dt.date.fromisoformat(str(r["trade_date"])[:10]) for r in rows]
        data[a] = (days, *({d: float(r[k]) for d, r in zip(days, rows)} for k in ("open", "high", "low", "close")))
        print("loaded", a, len(days), "of", total, flush=True)
    return {a: ([d for d in v[0] if d <= END], *v[1:]) for a, v in data.items()}


# ── 样本 ──────────────────────────────────────────────────────────────────────
def build_samples(tk: dict, cell: dict, crowd: dict) -> list:
    """一张票 = 一个样本。cell = 状态格标签;crowd = 四个持仓读数当天的高/低/中。"""
    out = []
    for (trig, side), rows in tk.items():
        for D, t in rows:
            out.append({"d": D, "trig": trig, "side": side, "cell": cell.get(D),
                        "crowd": {k: crowd.get(k, {}).get(D) for k in CROWD},
                        "pnl": float(t["pnl"]), "r": float(t["r"]), "stopped": bool(t["stopped"]),
                        "days": int(t["days"]), "t": t})
    return out


OUTCOMES = {
    "win": lambda s: s["pnl"] > 0,
    "loss": lambda s: s["pnl"] < 0,
    "stopped": lambda s: bool(s["stopped"]),
    "r_ge_1": lambda s: s["r"] >= 1.0,
}
PRIMARY = "win"
CTRL_ALL = "全部样本"


def controls_for(trig: str, cn: str):
    """三组对照:两个「只满足一半条件」的组 + 一个该状态格的全票组。"""
    def trig_other(s):
        return s["trig"] == trig and s["cell"] != cn

    def state_calendar(s):
        return s["trig"] == "EVERY5" and s["cell"] == cn

    def cell_all(s):
        return s["cell"] == cn

    return {"触发_其它状态": trig_other, "状态_日历同格": state_calendar, "状态格_全部票": cell_all}


def table_for(universe: list, trig: str, cn: str) -> dict:
    def condition(s):
        return s["trig"] == trig and s["cell"] == cn

    return apparatus.base_rate_table(universe, OUTCOMES, condition, controls_for(trig, cn))


def rate(rec: dict, outcome: str = PRIMARY) -> float | None:
    return (rec.get(outcome) or {}).get("rate")


def diff(a: dict, b: dict, outcome: str = PRIMARY) -> float | None:
    ra, rb = rate(a, outcome), rate(b, outcome)
    return None if ra is None or rb is None else round(ra - rb, 6)


def shift_cell(cell: dict, rng, min_shift: int = MIN_SHIFT) -> dict:
    """整条状态序列循环平移一个随机偏移(≥ min_shift 天);apparatus.circular_shift 保证偏移不为 0 且不贴边。"""
    ds = sorted(cell)
    labels = [cell[d] for d in ds]
    rolled = apparatus.circular_shift(labels, rng, block=1, min_shift=min_shift)
    return {d: l for d, l in zip(ds, rolled)}


def with_cell(rows: list, cellmap: dict) -> list:
    """把样本的状态格标签换成另一张(平移后的)标签表。"""
    return [{**s, "cell": cellmap.get(s["d"])} for s in rows]


def mean_stats(rows: list) -> dict:
    return G.summ([s["t"] for s in rows])


# ── 主体 ──────────────────────────────────────────────────────────────────────
def main():
    cell, crowd, n_state_rows = load_state()
    print("state rows", n_state_rows, "cell days", len(cell), flush=True)
    data = load_prices()
    tk = S881.tickets(data)
    samples = build_samples(tk, cell, crowd)
    print("tickets", {str(k): len(v) for k, v in tk.items()}, flush=True)

    universe = {1: [s for s in samples if s["side"] == 1], -1: [s for s in samples if s["side"] == -1]}

    # 复现核对:自己的管线能不能把 T-408 的读数算出来(算不出来 ⇒ 后面都不算数)
    t408 = json.load(open(T408)) if os.path.exists(T408) else None
    repro = {}
    if t408:
        for row in t408["cells"]:
            trig, cn = row["setup"].split("|")
            side = 1 if trig == "BO20" else -1
            cond = [s for s in universe[side] if s["trig"] == trig and s["cell"] == cn]
            base = [s for s in universe[side] if s["trig"] == "EVERY5" and s["cell"] == cn]
            mine = {"full": mean_stats(cond), "disc": mean_stats([s for s in cond if s["d"] <= SPLIT]),
                    "hold": mean_stats([s for s in cond if s["d"] > SPLIT]),
                    "base_disc": mean_stats([s for s in base if s["d"] <= SPLIT]),
                    "base_hold": mean_stats([s for s in base if s["d"] > SPLIT])}
            fields = {}
            for k, v in mine.items():
                theirs = row.get(k) or {}
                same = all(abs(float(v.get(f, 0)) - float(theirs.get(f, 0))) < 1e-9 for f in
                           ("n", "mean_pct", "payoff", "win", "stopped_at_a_loss"))
                fields[k] = {"mine": v, "t408": theirs, "same": bool(same)}
            repro[row["setup"]] = {"fields": fields, "all_same": all(x["same"] for x in fields.values())}
        print("repro", {k: v["all_same"] for k, v in repro.items()}, flush=True)

    # 8 个形态格:每格一张自带对照组的基率表
    cells_out = []
    seed_i = 0
    for trig, side in (("BO20", 1), ("BD20", -1)):
        for cn in CELLS:
            univ = universe[side]
            tab = table_for(univ, trig, cn)
            cond = tab["condition"]
            ds = {g: diff(cond, rec) for g, rec in tab.items() if g not in ("condition", "all")}
            ds[CTRL_ALL] = diff(cond, tab["all"])

            # 零分布:整条状态序列平移 ≥ 180 天,每次重算这一个格的差
            nulls, ps, pcts = {}, {}, {}
            for g in ds:
                seed_i += 1

                def fn(rng, trig=trig, cn=cn, side=side, g=g):
                    sh = shift_cell(cell, rng)
                    t2 = table_for(with_cell(universe[side], sh), trig, cn)
                    return diff(t2["condition"], t2["all" if g == CTRL_ALL else g])

                try:
                    nulls[g] = apparatus.null_distribution(fn, N_NULL, SEED + seed_i, actual=ds[g])
                except apparatus.NoOpNull as ex:
                    print("NoOpNull", trig, cn, g, ex, flush=True)
                    nulls[g] = None
                ps[g] = (apparatus.p_upper(ds[g], nulls[g]) if nulls[g] is not None and ds[g] is not None else None)
                pcts[g] = (apparatus.percentile_of(ds[g], nulls[g]) if nulls[g] is not None and ds[g] is not None else None)

            five = {"cond_rate": rate(cond), "all_rate": rate(tab["all"]),
                    "diff": ds.get(CTRL_ALL), "p": ps.get(CTRL_ALL), "n": cond["n"]}
            verdict = ("不可算" if five["diff"] is None or five["p"] is None else
                       ("有信号" if five["diff"] > 0 and five["p"] <= P_GATE else "基率"))
            cal_diff, cal_p = ds.get("状态_日历同格"), ps.get("状态_日历同格")
            strict = ("不可算" if cal_diff is None or cal_p is None else
                      ("有信号" if (five["diff"] > 0 and five["p"] <= P_GATE and cal_diff > 0 and cal_p <= P_GATE)
                       else "基率"))
            cells_out.append({
                "setup": f"{trig}|{cn}", "trig": trig, "side": side, "cell": cn,
                "five": five, "diff_vs_control": ds, "p_vs_control": ps, "percentile_vs_control": pcts,
                "p_bonferroni_8cells": (round(min(1.0, five["p"] * 8), 4) if five["p"] is not None else None),
                "calendar_control": {"diff": cal_diff, "p": cal_p},
                "verdict": verdict, "verdict_strict": strict,
                "table": tab,
                "mean_stats": {"condition": mean_stats([s for s in univ if s["trig"] == trig and s["cell"] == cn]),
                               "状态_日历同格": mean_stats([s for s in univ if s["trig"] == "EVERY5" and s["cell"] == cn]),
                               "状态格_全部票": mean_stats([s for s in univ if s["cell"] == cn]),
                               "触发_其它状态": mean_stats([s for s in univ if s["trig"] == trig and s["cell"] != cn]),
                               "全部样本": mean_stats(univ)},
                "disc_hold": {
                    "condition_disc": mean_stats([s for s in univ if s["trig"] == trig and s["cell"] == cn and s["d"] <= SPLIT]),
                    "condition_hold": mean_stats([s for s in univ if s["trig"] == trig and s["cell"] == cn and s["d"] > SPLIT]),
                    "calendar_disc": mean_stats([s for s in univ if s["trig"] == "EVERY5" and s["cell"] == cn and s["d"] <= SPLIT]),
                    "calendar_hold": mean_stats([s for s in univ if s["trig"] == "EVERY5" and s["cell"] == cn and s["d"] > SPLIT])},
            })
            print("CELL", f"{trig}|{cn}", json.dumps(five, ensure_ascii=False), "| diff",
                  json.dumps(ds, ensure_ascii=False), "| p", json.dumps(ps, ensure_ascii=False), "|", verdict, strict, flush=True)

    # 敏感性:状态标签挪一天(用 D − 1 的状态而不是 D 的)
    cell_prev = {}
    for d in sorted(cell):
        p = d - dt.timedelta(days=1)
        if p in cell:
            cell_prev[d] = cell[p]
    for s in samples:
        s["cell_prev"] = cell_prev.get(s["d"])
    sens = []
    for trig, side in (("BO20", 1), ("BD20", -1)):
        for cn in CELLS:
            univ = universe[side]
            cond = [s for s in univ if s["trig"] == trig and s["cell_prev"] == cn]
            base = [s for s in univ if s["trig"] == "EVERY5" and s["cell_prev"] == cn]
            cr = round(float(np.mean([s["pnl"] > 0 for s in cond])), 4) if cond else None
            br = round(float(np.mean([s["pnl"] > 0 for s in base])), 4) if base else None
            sens.append({"setup": f"{trig}|{cn}", "cond_rate": cr, "calendar_rate": br,
                         "n_cond": len(cond), "n_calendar": len(base),
                         "diff": round(cr - br, 4) if cr is not None and br is not None else None})
    print("SENS", json.dumps(sens, ensure_ascii=False), flush=True)

    # 退化核对:T-408 报「站住」的那几行(1 格 + 3 格 crowd)是不是退化样本
    degen = []
    holds_rows = []
    if t408:
        holds_rows += [{"setup": x["setup"], "crowd": None, "row": x} for x in t408["cells"] if x["holds"]]
        holds_rows += [{"setup": x["setup"], "crowd": x["crowd"], "row": x} for x in t408["crowd_holds"]]
    sigs = {}
    for hr in holds_rows:
        trig, cn = hr["setup"].split("|")
        side = 1 if trig == "BO20" else -1
        parent = [s for s in universe[side] if s["trig"] == trig and s["cell"] == cn]
        if hr["crowd"]:
            k, bucket = hr["crowd"].rsplit(":", 1)
            sub = [s for s in parent if s["crowd"].get(k) == bucket]
        else:
            sub = parent
        sig = tuple(sorted((s["d"].isoformat(), round(s["pnl"], 10)) for s in sub))
        sigs.setdefault(sig, []).append(f"{hr['setup']}|{hr['crowd']}")
        st = mean_stats(sub)
        flags = []
        if len(sub) < TINY_N:
            flags.append(f"票数极少(n={len(sub)} < {TINY_N})")
        if st.get("payoff", 0) >= HUGE_PAYOFF:
            flags.append(f"盈亏比异常大(pf={st.get('payoff')})")
        if hr["crowd"] and parent and len(sub) >= len(parent):
            flags.append(f"人群读数这一条没有剔掉任何票(子集 = 母集,n={len(sub)}/{len(parent)})")
        # 逐段也查一遍:T-408 的「站住」要求发现段与留出段都站得住,一段退化就不算数
        seg = {}
        for seg_name, rows_seg in (("disc", [s for s in sub if s["d"] <= SPLIT]),
                                   ("hold", [s for s in sub if s["d"] > SPLIT])):
            sst = mean_stats(rows_seg)
            sflags = []
            if len(rows_seg) < TINY_N:
                sflags.append(f"{seg_name} 段票数极少(n={len(rows_seg)} < {TINY_N})")
            if sst.get("payoff", 0) >= HUGE_PAYOFF:
                sflags.append(f"{seg_name} 段盈亏比异常大(pf={sst.get('payoff')})")
            seg[seg_name] = {"n": len(rows_seg), "stats": sst, "flags": sflags}
            flags += sflags
        degen.append({"setup": hr["setup"], "crowd": hr["crowd"], "n": len(sub), "parent_n": len(parent),
                      "kept_fraction": round(len(sub) / len(parent), 3) if parent else None,
                      "stats": st, "segments": seg,
                      "t408_row": {k: hr["row"].get(k) for k in ("full", "disc", "hold")},
                      "flags": flags, "degenerate": bool(flags)})
    for sig, names in sigs.items():
        if len(names) > 1:
            for d in degen:
                me = f"{d['setup']}|{d['crowd']}"
                if me in names:
                    others = " / ".join(n for n in names if n != me)
                    d["flags"].append(f"与另一行逐位同数(同一批票):{others}")
                    d["degenerate"] = True
    print("DEGEN", json.dumps([{k: d[k] for k in ("setup", "crowd", "n", "flags")} for d in degen], ensure_ascii=False), flush=True)

    result = {
        "card": "T-416",
        "what": "T-408(S-881)那 8 张基率表按 S-882「每张基率表必须自带对照组」重出,并判一次那 1 格「站住」的是信号还是基率",
        "method": {
            "sample": "一张票 = 一次进场(D 日收盘判、D + 1 开盘进、8% 止损、28 天、一次进满;走法同 S-879/S-881)",
            "universe": "分方向:多头 = BO20 触发票 + EVERY5 日历票;空头 = BD20 触发票 + EVERY5 日历票",
            "condition": "触发(BO20 突破 / BD20 跌破)且状态格 = 该格",
            "controls": "触发_其它状态 / 状态_日历同格(= T-408 的 base)/ 状态格_全部票 / 全部样本(base_rate_table 自动加)",
            "outcomes": list(OUTCOMES), "primary_outcome": PRIMARY,
            "null": f"整条状态序列循环平移 ≥ {MIN_SHIFT} 天(apparatus.circular_shift),每格每对照 {N_NULL} 次,差 = 条件组 − 对照组",
            "p": f"apparatus.p_upper(实际差, 零分布)(单侧,带 +1 修正);门 = 差 > 0 且 p ≤ {P_GATE}",
            "apparatus": "base_rate_table / circular_shift / null_distribution / p_upper / percentile_of",
            "state_rows": n_state_rows,
        },
        "reproduce_t408": repro,
        "cells": cells_out,
        "sensitivity_state_prev_day": sens,
        "degeneracy_check": degen,
        "verdict": {
            "n_cells": len(cells_out),
            "n_signal": sum(1 for c in cells_out if c["verdict"] == "有信号"),
            "n_base_rate": sum(1 for c in cells_out if c["verdict"] == "基率"),
            "n_signal_strict": sum(1 for c in cells_out if c["verdict_strict"] == "有信号"),
            "holds_rows_checked": len(degen),
            "n_degenerate_holds_rows": sum(1 for d in degen if d["degenerate"]),
        },
    }
    with open(OUT, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("WROTE", OUT, flush=True)
    print("VERDICT", json.dumps(result["verdict"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
