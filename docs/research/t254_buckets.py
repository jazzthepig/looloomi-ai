"""T-254 —— R-v2 的 R 从哪种市场里来(只报不判)。

票集 = T-251 的 40% 名义上限档**实际成交**的票(回放,窗口 2020-07-01 → 2026-11-04)。
按**开票日 d 收盘可知**的四个市场状态分组:
  ① ③ 敞口(0/1)     —— `src.data.signals.tom.trade_path` 本地复算(生产核,只 import)
  ② ⓪ phase         —— `cycle_vector_daily`.phase(normal / turning / none)
  ③ majors 200 日线  —— T-251 的 gate(level > 200 日均线;above / below)
  ④ DVOL 一年分位三档 —— Deribit DVOL 30d,开票日在过去 252 个交易日里的百分位 → low/mid/high

每组报:n、R 合计/均值/中位、胜率、最大连亏(按开票日排序的连续负 R 最长段)。
零信号对照:把分组标签在票之间随机置换 1,000 次(`apparatus.null_distribution`,基种子 254),
报每组 R 均值在零分布里的分位。S-665:主口径用开票日 d,再挪一天(entry 日)判一次。

用法:python3 docs/research/t254_buckets.py     (写 t254_results.json + T-254_rv2_regime_buckets.md)
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import t251_gross_cap as T251  # noqa: E402  —— T-251 的扫描器/模拟器,口径完全一致
from src.data.evaluation.apparatus import null_distribution, percentile_of  # noqa: E402
from src.data.signals.tom import trade_path  # noqa: E402  —— ③ 的规则核,生产代码

T252C = Path("/Volumes/CometCloudAI/cometcloud-local/research/t252")
T254C = Path("/Volumes/CometCloudAI/cometcloud-local/research/t254_cache")
D_FROM, D_TO = dt.date(2020, 7, 1), dt.date(2026, 11, 4)   # 与 T-251 完全一致(它跑于 11-05)
CAP_FRAC = 0.40
SEED = 254
N_PERM = 1000
TOM_WARM_FROM = "2024-01-01"
SHORT = {"BTC": 0.5, "ETH": 0.5}   # executor.SLEEVES
DVOL_WIN = 252                    # 一年 = 252 个交易日


def load_json(p: Path):
    return json.loads(p.read_text())


def dser(rows, key="d", val=None):
    out = {}
    for r in rows:
        v = r.get(val or key)
        if v is None:
            continue
        out[pd.Timestamp(str(r[key])[:10])] = float(v)
    return pd.Series(out).sort_index()


# ────────────────────────────────────────────────────────────── DVOL(Deribit)
def fetch_dvol() -> dict:
    f = T254C / "dvol_btc.json"
    if f.exists():
        return load_json(f)
    out: dict[str, float] = {}
    url = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
    for y in range(2020, 2027):
        s = int(dt.datetime(y, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
        e = int(dt.datetime(y, 12, 31, tzinfo=dt.timezone.utc).timestamp() * 1000)
        try:
            d = json.loads(urllib.request.urlopen(
                f"{url}?currency=BTC&resolution=1D&start_timestamp={s}&end_timestamp={e}", timeout=180).read())
        except Exception as ex:                                   # noqa: BLE001
            print(f"[dvol] {y} 抓取失败:{ex}", file=sys.stderr)
            continue
        for row in d.get("result", {}).get("data", []):
            day = dt.datetime.fromtimestamp(row[0] / 1000, dt.timezone.utc).strftime("%Y-%m-%d")
            out[day] = float(row[4])
        print(f"[dvol] {y}: 累计 {len(out)} 行", file=sys.stderr, flush=True)
        time.sleep(0.4)
    T254C.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out))
    return out


# ────────────────────────────────────────────────────────────── ③ 敞口(复算)
def exposure_from(px: dict[str, pd.Series], start: str | None) -> pd.Series:
    """生产核 `tom.trade_path` 复算 ③ 的加密腿敞口(0..1)。start=None ⇒ 2019 起全史。"""
    gs = {}
    for sym, s in px.items():
        ss = s if start is None else s[s.index >= pd.Timestamp(start)]
        g = trade_path(ss, "rally", 0.0, exit_mode="l20", vol=True)
        gs[sym] = g.clip(0.0, 1.0)
    idx = gs["BTC"].index.intersection(gs["ETH"].index)
    return sum(SHORT[sym] * gs[sym].reindex(idx) for sym in gs).sort_index()


# ────────────────────────────────────────────────────────────── 分组统计
def max_losing_streak(rs: list[float]) -> int:
    best = cur = 0
    for r in rs:
        cur = cur + 1 if r < 0 else 0
        best = max(best, cur)
    return best


def group_stats(tk: list[dict]) -> dict:
    """tk: 已排序(按开票日)的票;只统计有 r 的。"""
    rs = [t["r"] for t in tk if t.get("r") is not None]
    if not rs:
        return {"n": 0}
    arr = np.array(rs, dtype=float)
    return {
        "n": int(arr.size),
        "sum_r": round(float(arr.sum()), 4),
        "mean_r": round(float(arr.mean()), 4),
        "med_r": round(float(np.median(arr)), 4),
        "win_pct": round(100.0 * float((arr > 0).mean()), 1),
        "max_losing_streak": max_losing_streak(rs),
        "r_dist": {"min": round(float(arr.min()), 4), "p25": round(float(np.percentile(arr, 25)), 4),
                   "p75": round(float(np.percentile(arr, 75)), 4), "max": round(float(arr.max()), 4)},
    }


def perm_null_pct(labels: list[str], rs: list[float], group: str, actual: float | None,
                  stat: str = "mean") -> dict:
    """把分组标签在票之间随机置换 N_PERM 次,报该组统计量在零分布里的分位。

    置换 = 在全部票里随机抽与该组同样多的位置,取这些票的 R —— 等价于把组标签随机重分配。
    """
    idxs = [i for i, l in enumerate(labels) if l == group]
    if not idxs or actual is None:
        return {"null_pct": None, "note": "组内无票"}
    if len(idxs) < 2:
        return {"null_pct": None, "note": "组内 n<2 —— 置换不改变该组统计量(必然 NoOpNull)"}

    def draw(rng):
        pick = rng.choice(len(rs), size=len(idxs), replace=False)
        vals = [rs[i] for i in pick]
        return float(np.mean(vals)) if stat == "mean" else float(np.median(vals))

    try:
        null = null_distribution(draw, N_PERM, SEED, actual=float(actual))
    except Exception as ex:                                       # noqa: BLE001
        return {"null_pct": None, "note": f"NoOpNull:{ex}"}
    return {"null_pct": round(float(percentile_of(float(actual), null)), 4),
            "null_mean": round(float(np.mean(null)), 4), "null_sd": round(float(np.std(null)), 4),
            "note": f"置换标签 1000 次({stat});分位 ≥ 0.95 = 该组{stat}高于 95% 的置换结果"}


def main() -> None:
    print("[1/6] 读 T-251 缓存(不重抓)…", flush=True)
    pairs, style, bars, uni = T251.fetch_all()
    gate = T251.load_gate(style)
    print(f"  宇宙 {len(uni)} 个符号,gate {len(gate)} 天", flush=True)

    # majors level 与 200 日均线(与 load_gate 同一个口径),用来算「离 200 日线多远」
    _rows = [x for x in style if x.get("ret") is not None and x["ret"] > -0.95]
    _rows.sort(key=lambda x: x["d"])
    _lvl, _cur = [], 1.0
    for x in _rows:
        _cur *= (1.0 + x["ret"])
        _lvl.append(_cur)
    _ma200 = {}
    for i, x in enumerate(_rows):
        w = _lvl[max(0, i - 199):i + 1]
        _ma200[x["d"]] = (sum(w) / len(w)) if len(w) >= 200 else None
    _dist = {}
    for i, x in enumerate(_rows):
        m = _ma200[x["d"]]
        _dist[x["d"]] = None if not m else round(_lvl[i] / m - 1.0, 6)

    print("[2/6] 回放 T-251 的票源…", flush=True)
    tickets, stopped, hole_days, guard = T251.scan(bars, gate, D_FROM, D_TO)
    sim = T251.simulate(tickets, bars, gate, CAP_FRAC)
    taken = sim["taken"]
    tk = sorted([t for t in tickets if t["tid"] in taken and t.get("r") is not None],
                key=lambda t: (t["signal_d"], t["symbol"]))
    print(f"  全部票 {len(tickets)},40% 档成交 {len(taken)},有 R 的 {len(tk)}", flush=True)

    print("[3/6] ③ 敞口复算 + 校验…", flush=True)
    px_btc = dser(load_json(T252C / "asset_mcap_BTC.json"), "d", "price")
    px_eth = dser(load_json(T252C / "asset_mcap_ETH.json"), "d", "price")
    exp_full = exposure_from({"BTC": px_btc, "ETH": px_eth}, None)
    exp_live = exposure_from({"BTC": px_btc, "ETH": px_eth}, TOM_WARM_FROM)
    expdec = load_json(T252C / "exposure_decision.json")
    validation = []
    for r in expdec:
        d = str(r["d"])[:10]
        pub = r.get("rule_exposure")
        if pub is None:
            continue
        rf = exp_full.get(pd.Timestamp(d))
        rl = exp_live.get(pd.Timestamp(d))
        validation.append({
            "d": d, "published": float(pub),
            "recon_full": None if rf is None else round(float(rf), 6),
            "recon_live": None if rl is None else round(float(rl), 6),
            "match_full": rf is not None and abs(float(rf) - float(pub)) < 1e-6,
            "match_live": rl is not None and abs(float(rl) - float(pub)) < 1e-6})
    print(f"  校验 {sum(v['match_full'] for v in validation)}/{len(validation)} 相符(2019 起)",
          f" / {sum(v['match_live'] for v in validation)}/{len(validation)}(2024 起)", flush=True)

    print("[4/6] ⓪ phase / DVOL…", flush=True)
    cyc = load_json(T252C / "cycle.json")
    phase = {str(r["d"])[:10]: r.get("phase") for r in cyc}
    dvol_raw = fetch_dvol()
    dvol = pd.Series(dvol_raw).sort_index()
    dvol.index = pd.to_datetime(dvol.index)
    print(f"  DVOL {len(dvol)} 行,{dvol.index[0].date()} → {dvol.index[-1].date()}", flush=True)

    def dvol_tercile(day: str) -> str:
        try:
            ts = pd.Timestamp(day)
        except Exception:                                           # noqa: BLE001
            return "no_data"
        if ts < dvol.index[0]:
            return "no_dvol_history"
        w = dvol.loc[(dvol.index <= ts)].iloc[-DVOL_WIN:]
        if len(w) < DVOL_WIN:
            return "insufficient_history"
        v = float(w.iloc[-1])
        pct = ((w < v).sum() + 0.5 * (w == v).sum()) / len(w)
        return "low" if pct < 1 / 3 else ("mid" if pct < 2 / 3 else "high")

    # ── 分组标签(两个口径:base = 开票日 d;shift1 = entry 日) ─────────────────
    def labels_for(day_of: str):
        out = []
        for t in tk:
            d = t[day_of]
            e = exp_full.get(pd.Timestamp(d))
            el = exp_live.get(pd.Timestamp(d))
            e0 = None if e is None else (0 if abs(float(e)) < 1e-9 else 1)
            e0l = None if el is None else (0 if abs(float(el)) < 1e-9 else 1)
            g = gate.get(d)
            dst = _dist.get(d)
            if dst is None:
                mdist = "na"
            elif dst > 0.05:
                mdist = "far_above(>5%)"
            elif dst > 0.0:
                mdist = "near_above(0~5%)"
            else:
                mdist = "at_or_below(<=0%)"
            out.append({
                "tid": t["tid"], "symbol": t["symbol"], "signal_d": t["signal_d"],
                "entry_d": t["entry_d"], "r": t["r"], "exit_reason": t.get("exit_reason"),
                "exp3": "na" if e0 is None else str(e0),
                "exp3_live": "na" if e0l is None else str(e0l),
                "exp3_val": None if e is None else round(float(e), 4),
                "phase": phase.get(d) or "none",
                "maj200": "na" if g is None else ("above" if g else "below"),
                "maj_dist": mdist,
                "maj_dist_val": dst,
                "dvol": dvol_tercile(d),
            })
        return out

    base = labels_for("signal_d")
    shift1 = labels_for("entry_d")
    rs = [x["r"] for x in base]

    print("[5/6] 分组 + 零信号对照…", flush=True)
    VARS = [("exp3", "③ 敞口(0/1)"), ("exp3_live", "③ 敞口(2024 起口径,敏感度)"),
            ("phase", "⓪ phase"),
            ("maj200", "majors 200 日线"), ("dvol", "DVOL 一年分位(三档)"),
            ("maj_dist", "majors 离 200 日线的距离(补充档)")]

    def build(rows: list[dict], label: str):
        res = {"basis": label, "n_tickets": len(rows), "vars": {}}
        for vname, vlabel in VARS:
            groups = defaultdict(list)
            for x in rows:
                groups[str(x[vname])].append(x)
            tab, nulls = {}, {}
            for g in sorted(groups):
                st = group_stats(groups[g])
                tab[g] = st
                st["thin"] = bool(st["n"] < 15)
                labs = [str(x[vname]) for x in rows]
                nulls[g] = {
                    "mean": perm_null_pct(labs, rs, g, st.get("mean_r"), stat="mean"),
                    "median": perm_null_pct(labs, rs, g, st.get("med_r"), stat="median"),
                }
            res["vars"][vname] = {"label": vlabel, "groups": tab, "null": nulls}
        # 交叉表:③ 敞口 × majors 200 日线(majors 距离版)
        for key, second in (("cross_exp3_x_maj200", "maj200"), ("cross_exp3_x_maj_dist", "maj_dist")):
            cross = defaultdict(list)
            for x in rows:
                cross[(str(x["exp3"]), str(x[second]))].append(x)
            res[key] = {f"{a}|{b}": group_stats(v) for (a, b), v in sorted(cross.items())}
        return res

    res = {
        "as_of": "2026-11-06",
        "ticket_set": {
            "source": "T-251 回放(t251_gross_cap.scan + simulate)",
            "window": [D_FROM.isoformat(), D_TO.isoformat()],
            "cap_frac": CAP_FRAC,
            "n_tickets_total": len(tickets),
            "n_tickets_taken_40pct": len(taken),
            "n_tickets_with_r": len(tk),
            "n_tickets_total_30pct": None,
        },
        "exposure_reconstruction": {
            "method": "src.data.signals.tom.trade_path(bear='rally', exit_mode='l20', vol=True),clip[0,1],BTC/ETH 各 0.5",
            "price_source": "asset_mcap_daily.price(T-252 缓存)",
            "validation": validation,
            "sensitivity": "主口径 exp_full(2019 起);exp_live(2024-01-01 起)见 vars.exp3_live",
        },
        "basis_base": build(base, "开票日 d 收盘(信号日)"),
        "basis_shift1": build(shift1, "挪一天(entry 日)—— S-665"),
        "thin_rule": "n < 15 的格子标 thin",
        "null_rule": f"分组标签在 {len(tk)} 张票之间随机置换 {N_PERM} 次,基种子 {SEED}(每组 seed=254+组序)",
    }
    res["ticket_set"]["n_tickets_total_30pct"] = len(
        [t for t in tickets if t["tid"] in T251.simulate(tickets, bars, gate, 0.30)["taken"]])

    # 稳健性:R 的右尾会不会单独驱动均值
    _rr = np.array(rs, dtype=float)
    _srt = np.sort(_rr)[::-1]
    res["robustness"] = {
        "n": int(_rr.size),
        "sum_r": round(float(_rr.sum()), 4),
        "mean_r": round(float(_rr.mean()), 4),
        "median_r": round(float(np.median(_rr)), 4),
        "max_r": round(float(_rr.max()), 4),
        "p95_r": round(float(np.percentile(_rr, 95)), 4),
        "mean_r_ex_top1": round(float(_srt[1:].mean()), 4),
        "mean_r_ex_top3": round(float(_srt[3:].mean()), 4),
        "share_of_sum_from_top3": round(float(_srt[:3].sum() / _rr.sum()), 4) if _rr.sum() else None,
        "top3_tickets": [{"tid": x["tid"], "signal_d": x["signal_d"], "r": x["r"],
                          "exp3": x["exp3"], "phase": x["phase"], "dvol": x["dvol"]}
                         for x in sorted(base, key=lambda z: -(z["r"] or 0))[:3]],
        "note": "R 的右尾(少数大赢家)对均值的影响;均值分位与中位分位并列看",
    }

    Path("docs/research/t254_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(f"  写 docs/research/t254_results.json", flush=True)

    # ── 报告 ────────────────────────────────────────────────────────────────
    L = []
    A = L.append
    A("# T-254 —— R-v2 的 R 从哪种市场里来(只报不判)\n")
    A("> **只报不判**:这是为将来的闸门预注册准备的**基率**,不构成任何策略结论、没有 SHIP 判定。")
    A("> 真钱名义上限 2026-11-05 由 Jazz 改到 40%(8f982807);本卡只回答「这些票的 R 落在哪种市场状态里」。\n")
    A("## 0. 票集与口径\n")
    A("| 项 | 值 |")
    A("|---|---|")
    A(f"| 票源 | T-251 回放(`t251_gross_cap.scan` + `simulate`),窗口 {D_FROM} → {D_TO} |")
    A(f"| 名义上限档 | {CAP_FRAC:.0%} |")
    A(f"| 全部票 | {len(tickets)} 张 |")
    A(f"| **40% 档实际成交** | **{len(taken)} 张**(有 R 的 {len(tk)} 张) |")
    A(f"| 30% 档实际成交 | {res['ticket_set']['n_tickets_total_30pct']} 张(对照) |")
    A("| 分组变量取值时点 | 主口径 = **开票日 d 收盘**;另报**挪一天**(entry 日)—— S-665 |")
    A("| ③ 敞口 | `tom.trade_path` 本地复算(生产核,只 import),权重 BTC/ETH 各 0.5 |")
    A("| ③ 价源 | `asset_mcap_daily.price`(T-252 缓存) |")
    A(f"| ③ 校验 | {sum(v['match_full'] for v in validation)}/{len(validation)} 与已落表 `exposure_decision_daily` 逐日相符(2019 起口径) |")
    A("| ⓪ phase | `cycle_vector_daily`.phase |")
    A("| majors 200 日线 | T-251 的 gate(majors/cap level > 200 日均线) |")
    A("| DVOL | Deribit 30d DVOL,开票日在过去 252 个交易日的百分位 → low/mid/high |")
    A(f"| 零信号对照 | 标签在 {len(tk)} 张票之间置换 {N_PERM} 次,基种子 {SEED} |")
    A("")
    A("### 0a. 两个结构性事实(先看,再看表)\n")
    A("1. **majors 200 日线这一格是退化的**:它同时是 R-v2 的**信号闸门**"
      "(`sig_at` 要求 `gate_open`),所以 145 张票**全部**落在 `above`,这一格没有区分度。"
      "想拿它当闸门变量,得先查「闸门关着的日子信号长什么样」—— 那不在本卡范围。"
      "作为替代,补了一张**离 200 日线的距离**分档(`maj_dist`),在票集内有区分度。")
    A("2. **R 的右尾很重**(见 0b):任何以「组均值」为口径的读数都要同时看中位数与置换分位。\n")
    A("### 0b. 稳健性:R 的右尾\n")
    rb = res["robustness"]
    A("| 项 | 值 |")
    A("|---|---|")
    A(f"| n | {rb['n']} |")
    A(f"| R 合计 | {rb['sum_r']} |")
    A(f"| R 均值 | {rb['mean_r']} |")
    A(f"| R 中位 | {rb['median_r']} |")
    A(f"| 最大 R | {rb['max_r']} |")
    A(f"| p95 R | {rb['p95_r']} |")
    A(f"| 均值(去掉最大 1 张) | {rb['mean_r_ex_top1']} |")
    A(f"| 均值(去掉最大 3 张) | {rb['mean_r_ex_top3']} |")
    A(f"| 前 3 张占 R 合计 | {rb['share_of_sum_from_top3']} |")
    A("")
    A("| 最大 R 的 3 张票 | 开票日 | R | ③ 敞口 | ⓪ phase | DVOL |")
    A("|---|---|---|---|---|---|")
    for t in rb["top3_tickets"]:
        A(f"| {t['tid']} | {t['signal_d']} | {t['r']} | {t['exp3']} | {t['phase']} | {t['dvol']} |")
    A("")
    for basis, blk in (("basis_base", res["basis_base"]), ("basis_shift1", res["basis_shift1"])):
        A(f"## {'1' if basis == 'basis_base' else '2'}. {blk['basis']} —— 分组表\n")
        for vname, vlabel in VARS:
            v = blk["vars"][vname]
            A(f"### {vlabel}(`{vname}`)\n")
            A("| 组 | n | R 合计 | R 均值 | R 中位 | 胜率 % | 最大连亏 | thin | 均值分位 | 中位分位 |")
            A("|---|---|---|---|---|---|---|---|---|---|")
            for g, st in v["groups"].items():
                if not st.get("n"):
                    A(f"| {g} | 0 | — | — | — | — | — | — | — | — |")
                    continue
                nu = v["null"].get(g, {})
                pm = (nu.get("mean") or {}).get("null_pct")
                pmd = (nu.get("median") or {}).get("null_pct")
                note = (nu.get("mean") or {}).get("note") or ""
                A(f"| {g} | {st['n']} | {st['sum_r']} | {st['mean_r']} | {st['med_r']} | {st['win_pct']} | "
                  f"{st['max_losing_streak']} | {'thin' if st['thin'] else ''} | "
                  f"{pm if pm is not None else (note or '—')} | {pmd if pmd is not None else '—'} |")
            A("")
        for ck, ctitle in (("cross_exp3_x_maj200", "交叉表:③ 敞口 × majors 200 日线"),
                           ("cross_exp3_x_maj_dist", "交叉表:③ 敞口 × majors 离 200 日线的距离")):
            A(f"### {ctitle}\n")
            A("| ③ 敞口 | 第二组 | n | R 合计 | R 均值 | 胜率 % | 最大连亏 |")
            A("|---|---|---|---|---|---|---|")
            for k, st in res[basis][ck].items():
                a, b = k.split("|")
                if not st.get("n"):
                    A(f"| {a} | {b} | 0 | — | — | — | — |")
                else:
                    A(f"| {a} | {b} | {st['n']} | {st['sum_r']} | {st['mean_r']} | "
                      f"{st['win_pct']} | {st['max_losing_streak']} |")
            A("")
    Path("docs/research/T-254_rv2_regime_buckets.md").write_text("\n".join(L))
    print("  写 docs/research/T-254_rv2_regime_buckets.md", flush=True)
    print("[6/6] 完成", flush=True)


if __name__ == "__main__":
    main()
