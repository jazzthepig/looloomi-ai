"""S-868:S-865 没量的那一种 —— ATR 止损加一个上限(「2.5 × ATR,但不超过 8% / 12%」);以及 cell 组空单的盈亏按年拆。

为什么:S-865 的表里,2.5 × ATR 亏着被止损最少、但最差一张 −57%(暴跌之后 ATR 最宽);固定 8% 最差封顶、但近一半到三分之二的票
亏着出去。看到这张表的第一个问题一定是「能不能两头都要」。这里只加这一种,连同 S-865 判不了的 E4(cell 组的空单利润是不是主要来自 2022)。

**引擎不重写:** 一张票怎么走,用的就是 `s865_ticket_forms.run_ticket` —— 上限是通过把当天的 ATR 压到 `cap × 进场价 / 2.5` 传进去实现的
(于是止损 = 进场价 ± min(2.5 × ATR, cap × 进场价)),所以 K2 / K3 两行必须与 S-865 的结果逐项相同(脚本自己核,不同就停)。

只描述。预期与读法写在台账 S-868(先登记,后计算)。

用法(仓库根目录):
    python3 docs/research/s868_capped_stops.py --selftest
    python3 docs/research/s868_capped_stops.py            # 写 docs/research/s868_results.json
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_sp = importlib.util.spec_from_file_location("s865", os.path.join(HERE, "s865_ticket_forms.py"))
T = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(T)

OUT = "docs/research/s868_results.json"
CAPS = {"K4": 0.08, "K5": 0.12}            # K4 = min(2.5 ATR, 8%);K5 = min(2.5 ATR, 12%)
BY_YEAR_FORMS = (("K2", "X0"), ("K3", "X0"), ("K4", "X0"))
BY_YEAR_H = 28
END = dt.date(2026, 11, 13)                # S-865 跑的时候库里的最后一根日线;截到这里,K1 / K2 / K3 才能与那份结果逐项对


def capped_atr(days, o, atr: dict, cap: float) -> dict:
    """每个信号日 D 的 ATR 压到 cap × 进场价 / 2.5(进场价 = D + 1 的开盘)。D 是最后一天 ⇒ 没有进场价,原样留着(那张票本来也开不了)。"""
    idx = {d: i for i, d in enumerate(days)}
    out = {}
    for d, a in atr.items():
        i = idx[d] + 1
        out[d] = min(a, cap * o[days[i]] / T.ATR_MULT) if i < len(days) else a
    return out


def ticket(days, o, h, l, c, atr, atr_c, D, side, K, X, H):
    if K in CAPS:
        return T.run_ticket(days, o, h, l, c, atr_c[K], D, side, "K2", X, H)
    return T.run_ticket(days, o, h, l, c, atr, D, side, K, X, H)


def run(data: dict, reference: dict | None = None) -> dict:
    out = {"table": {}, "dominated": {}, "by_year": {}, "cap_binds_share": {}, "reproduces_s865": None}
    mismatches = []
    stops = ("K1", "K2", "K3", "K4", "K5")
    for a in T.ASSETS:
        days, o, h, l, c = data[a]
        atr = T.atr14(days, o, h, l, c)
        atr_c = {K: capped_atr(days, o, atr, cap) for K, cap in CAPS.items()}
        for side, sname in ((-1, "short"), (1, "long")):
            for kind in ("cell", "all"):
                sig = T.entry_days(days, c, side, kind)
                for K, cap in CAPS.items():
                    b = [atr_c[K][D] < atr[D] for D in sig if D in atr]
                    out["cap_binds_share"][f"{a}|{sname}|{kind}|{K}"] = round(sum(b) / len(b), 3) if b else None
                for H in T.HORIZONS:
                    key = f"{a}|{sname}|{kind}|H{H}"
                    forms = {}
                    for K in stops:
                        for X in T.EXITS:
                            ts = [t for t in (ticket(days, o, h, l, c, atr, atr_c, D, side, K, X, H) for D in sig) if t]
                            forms[f"{K}+{X}"] = T.summarise(ts, len(sig))
                    out["table"][key] = forms
                    live = {k: v for k, v in forms.items() if v.get("n", 0) >= 5}
                    out["dominated"][key] = sorted(b for b in live if any(
                        live[x]["mean_pct"] > live[b]["mean_pct"] and live[x]["worst_pct"] >= live[b]["worst_pct"] and live[x]["stopped_at_a_loss"] < live[b]["stopped_at_a_loss"]
                        for x in live if x != b))
                    if reference is not None:
                        ref = reference["table"].get(key, {})
                        mismatches += [f"{key} {f}" for f, v in forms.items() if f[:2] in ("K1", "K2", "K3") and ref.get(f) != v]
                if sname == "short" and kind == "cell":
                    for K, X in BY_YEAR_FORMS:
                        rows = {}
                        for D in sig:
                            t = ticket(days, o, h, l, c, atr, atr_c, D, side, K, X, BY_YEAR_H)
                            if t:
                                y = rows.setdefault(str(D.year), {"n": 0, "sum_pct": 0.0})
                                y["n"] += 1
                                y["sum_pct"] = round(y["sum_pct"] + t["pnl"] * 100, 2)
                        tot = sum(v["sum_pct"] for v in rows.values())
                        out["by_year"][f"{a}|{K}+{X}|H{BY_YEAR_H}"] = {"years": rows, "total_pct": round(tot, 2),
                                                                      "share_2022": (round(rows.get("2022", {}).get("sum_pct", 0.0) / tot, 3) if tot > 0 else None)}
    slices = [k for k in out["table"] if "|short|" in k]
    names = [f"{K}+{X}" for K in stops for X in T.EXITS]
    out["non_dominated_count_short"] = {f: sum(1 for k in slices if f not in out["dominated"][k]) for f in names}
    out["n_short_slices"] = len(slices)
    if reference is not None:
        out["reproduces_s865"] = {"ok": not mismatches, "n_mismatch": len(mismatches), "first": mismatches[:5]}
    return out


if __name__ == "__main__":
    selftest = "--selftest" in sys.argv
    data = T.synthetic() if selftest else {a: ([d for d in v[0] if d <= END], *v[1:]) for a, v in T.load_live().items()}
    ref = None
    if selftest:
        ref = T.run(data)
    elif os.path.exists(os.path.join(HERE, "s865_results.json")):
        ref = json.load(open(os.path.join(HERE, "s865_results.json")))
    out = run(data, ref)
    print("REPRODUCES_S865", json.dumps(out["reproduces_s865"], ensure_ascii=False) if ref is not None else "没核(同目录下没有 s865_results.json)", flush=True)
    if out["reproduces_s865"] is not None and not out["reproduces_s865"]["ok"] and not selftest:
        print("STOP: K1 / K2 / K3 与 S-865 的结果不同 —— 不往下报")
        sys.exit(2)
    print("CAP_BINDS", json.dumps(out["cap_binds_share"], ensure_ascii=False), flush=True)
    for key, forms in out["table"].items():
        print("SLICE", key, "| dominated:", ",".join(out["dominated"][key]) or "-", flush=True)
        for f, v in forms.items():
            if f[:2] in ("K2", "K3", "K4", "K5"):
                print("  ", f, json.dumps(v, ensure_ascii=False), flush=True)
    for k, v in out["by_year"].items():
        print("BY_YEAR", k, json.dumps(v, ensure_ascii=False), flush=True)
    print("NON_DOMINATED_SHORT", json.dumps(out["non_dominated_count_short"]), "of", out["n_short_slices"], flush=True)
    if selftest:
        assert out["reproduces_s865"]["ok"], out["reproduces_s865"]
        t = out["table"]
        # 合成数据的开盘带跳空(S-865 的自检同样放了 6 个点);真实现货日线开盘 = 前收,上限就是上限
        assert all(v["K4+X0"]["worst_pct"] >= -8.0 - 6.0 for k, v in t.items() if v["K4+X0"].get("n")), "8% 上限:最差一张应在 −8% 附近(跳空除外)"
        assert all(v["K5+X0"]["worst_pct"] >= -12.0 - 6.0 for k, v in t.items() if v["K5+X0"].get("n"))
        assert all(v["K4+X0"]["stopped_at_a_loss"] >= v["K2+X0"]["stopped_at_a_loss"] - 1e-9 for v in t.values() if v["K4+X0"].get("n")), "加了上限的止损只会更近,不会更远"
        assert all(v["K4+X0"]["worst_pct"] >= v["K2+X0"]["worst_pct"] - 1e-6 for v in t.values() if v["K4+X0"].get("n") and v["K2+X0"].get("n"))
        assert all(0.0 <= s <= 1.0 for s in out["cap_binds_share"].values() if s is not None)
        assert all(sum(y["n"] for y in v["years"].values()) > 0 for v in out["by_year"].values())
        print("SELFTEST OK")
    else:
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
        print("WROTE", OUT)
