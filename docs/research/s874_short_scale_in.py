"""S-874:空单「远止损 + 逆势分批加仓」的模拟 —— Jazz 2026-11-15 的写法,先看全貌再定默认值(T-370)。

Jazz:「空单的止损线要由当期波动率而定,base 就是 −25%,随波动率反向调整。进入观察、反转之前市场情绪会冲得很猛,
这个时候反而不可以止损,而是需要再加仓。」预期、选法与后果写在台账 S-874(先登记,后计算)。只描述 + 一条事前写死的选法。

一张空票(占「满仓名义」的比例计盈亏;D 日收盘判、D + 1 开盘进第一笔):
  止损距离  dist = clip(BASE × (σ_ref / σ)^γ, 8%, 60%);σ = ATR14 / 收盘,σ_ref = 此前 365 天 σ 的中位数
            γ = +1「反向」:波动大 ⇒ 止损更近(Jazz 原话的字面);γ = 0 固定;γ = −1 常见写法:波动大 ⇒ 更远
  加仓      A0 一次进满;A2 两笔各半(进场价、+dist/2);A3 三笔各 1/3(进场价、+dist/3、+2dist/3);A3w 三笔 20% / 30% / 50%(越冲越多)
            价格涨到那一档才成交(跳空越过按开盘价);全部仓位共用一条止损线 = 第一笔进场价 × (1 + dist)
  止盈      T0 不设;T15 价格跌到已成交均价之下 15% ⇒ 平一半、止损移到均价、不再加仓
  到期      28 / 56 / 84 天
  同一根日线里既碰加仓档又碰止损 ⇒ 先加后止损(最坏的顺序)。资金费不计;现货日线代替永续。
进场日三组(BTC / ETH 各自):all 每隔 5 天(没有判断);cell 周线坏且在 200 日线下的每段第一天(S-865 那一组);
  drain 面板「线下 · 稳定币抽」状态里每隔 5 天(S-871:做空的长处所在的状态;标签 = s866_cells.json)。
对照:R8 / R12 = 固定 8% / 12%、一次进满 —— R8 · 28 天必须与 S-865 的 K3 + X0 逐项相同(脚本自己核)。

用法(仓库根目录):
    python3 docs/research/s874_short_scale_in.py --selftest
    python3 docs/research/s874_short_scale_in.py            # 写 docs/research/s874_results.json
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import itertools
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
_sp = importlib.util.spec_from_file_location("s865", os.path.join(HERE, "s865_ticket_forms.py"))
T = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(T)

OUT = "docs/research/s874_results.json"
END = dt.date(2026, 11, 13)
SPLIT = dt.date(2022, 12, 31)                       # 发现段 ≤ 这一天;留出段在它之后,选法不碰
BASES, GAMMAS, HORIZONS = (0.15, 0.20, 0.25, 0.30, 0.35), (1, 0, -1), (28, 56, 84)
SCHEMES = {"A0": ((0.0,), (1.0,)), "A2": ((0.0, 0.5), (0.5, 0.5)), "A3": ((0.0, 1 / 3, 2 / 3), (1 / 3, 1 / 3, 1 / 3)),
           "A3w": ((0.0, 1 / 3, 2 / 3), (0.2, 0.3, 0.5))}
TPS = {"T0": None, "T15": 0.15}
DIST_MIN, DIST_MAX, SIG_WIN, SIG_MIN_OBS = 0.08, 0.60, 365, 180
MIN_N, MIN_PAYOFF, WORST_FLOOR = 20, 2.0, -0.35      # 选法的三道门(台账 S-874)


def sigma_ref(days, atr, c) -> dict:
    """D → (σ, 此前 SIG_WIN 天 σ 的中位数);不足 SIG_MIN_OBS 个 ⇒ 没有。只用 D 及以前。"""
    sig = [(atr[d] / c[d]) if d in atr and c[d] else None for d in days]
    out = {}
    for i, d in enumerate(days):
        w = [x for x in sig[max(0, i - SIG_WIN):i] if x]
        if sig[i] and len(w) >= SIG_MIN_OBS:
            out[d] = (sig[i], float(np.median(w)))
    return out


def ticket(days, o, h, l, c, idx, D, dist, scheme: str, H: int, tp):
    i = idx[D] + 1
    if i + H >= len(days):
        return None
    fracs, ws = SCHEMES[scheme]
    e0 = o[days[i]]
    stop = e0 * (1 + dist)
    levels = [e0 * (1 + dist * f) for f in fracs]
    fills, k, rem, half, pnl = [(e0, ws[0])], 1, 1.0, False, 0.0
    for j in range(i, i + H + 1):
        d = days[j]
        op, hi, lo = o[d], h[d], l[d]
        while k < len(levels) and hi >= levels[k]:                       # 先加(最坏的顺序)
            fills.append((max(op, levels[k]), ws[k]))
            k += 1
        if hi >= stop:
            px = max(op, stop)
            pnl += sum(rem * w * (e - px) / e for e, w in fills)
            return {"pnl": pnl, "days": j - i + 1, "stopped": pnl < 0, "deployed": sum(w for _, w in fills), "half": half}
        if tp and not half:
            avg = sum(e * w for e, w in fills) / sum(w for _, w in fills)
            tgt = avg * (1 - tp)
            if lo <= tgt:
                pnl += sum(0.5 * w * (e - tgt) / e for e, w in fills)
                rem, half, stop, k = 0.5, True, avg, len(levels)
    cl = c[days[i + H]]
    pnl += sum(rem * w * (e - cl) / e for e, w in fills)
    return {"pnl": pnl, "days": H + 1, "stopped": False, "deployed": sum(w for _, w in fills), "half": half}


def summ(ts: list) -> dict:
    if not ts:
        return {"n": 0}
    p = np.array([t["pnl"] for t in ts])
    win, loss = p[p > 0], p[p < 0]
    payoff = 0.0 if not len(win) else (99.0 if not len(loss) else float(win.mean() / abs(loss.mean())))
    return {"n": int(len(p)), "mean_pct": round(float(p.mean()) * 100, 2), "median_pct": round(float(np.median(p)) * 100, 2),
            "worst_pct": round(float(p.min()) * 100, 2), "best_pct": round(float(p.max()) * 100, 2), "win": round(float((p > 0).mean()), 3),
            "payoff": round(payoff, 2), "stopped_at_a_loss": round(float(np.mean([t["stopped"] for t in ts])), 3),
            "deployed": round(float(np.mean([t["deployed"] for t in ts])), 3), "mean_days": round(float(np.mean([t["days"] for t in ts])), 1)}


def drain_days(days, labels: dict) -> list:
    ok = [d for d in days if d >= T.START and (labels.get(d) or {}).get("T") == "线下" and (labels.get(d) or {}).get("L") == "抽"]
    return ok[::T.EVERY_N]


def run(data: dict, labels: dict, reference: dict | None = None) -> dict:
    tickets: dict = {}                                                   # (form, group, H) → [(asset, D, ticket)]
    refs: dict = {}
    repro = []
    for a in T.ASSETS:
        days, o, h, l, c = data[a]
        idx = {d: i for i, d in enumerate(days)}
        atr = T.atr14(days, o, h, l, c)
        sr = sigma_ref(days, atr, c)
        groups = {"all": T.entry_days(days, c, -1, "all"), "cell": T.entry_days(days, c, -1, "cell"), "drain": drain_days(days, labels)}
        for g, sig in groups.items():
            sig = [D for D in sig if D in atr]
            for H in HORIZONS:
                for name, dist in (("R8", 0.08), ("R12", 0.12)):
                    ts = [(a, D, t) for D in sig if (t := ticket(days, o, h, l, c, idx, D, dist, "A0", H, None))]
                    refs.setdefault((name, g, H), []).extend(ts)
                    if name == "R8" and H == 28 and g in ("all", "cell") and reference is not None:
                        mine, ref = summ([t for _, _, t in ts]), reference["table"].get(f"{a}|short|{g}|H28", {}).get("K3+X0", {})
                        same = all(mine.get(k) == ref.get(k) for k in ("n", "mean_pct", "median_pct", "worst_pct", "win"))
                        repro.append({"slice": f"{a}|{g}", "ok": bool(same), "mine": {k: mine.get(k) for k in ("n", "mean_pct", "worst_pct")},
                                      "s865": {k: ref.get(k) for k in ("n", "mean_pct", "worst_pct")}})
                for base, gam, sch, tpn in itertools.product(BASES, GAMMAS, SCHEMES, TPS):
                    form = f"B{int(base * 100)}|g{gam:+d}|{sch}|{tpn}"
                    ts = []
                    for D in sig:
                        if gam == 0:
                            dist = base
                        elif D in sr:
                            dist = float(np.clip(base * (sr[D][1] / sr[D][0]) ** gam, DIST_MIN, DIST_MAX))
                        else:
                            continue
                        t = ticket(days, o, h, l, c, idx, D, dist, sch, H, TPS[tpn])
                        if t:
                            ts.append((a, D, t))
                    tickets.setdefault((form, g, H), []).extend(ts)
    out = {"reproduces_s865": {"ok": bool(repro) and all(r["ok"] for r in repro), "checks": repro} if reference is not None else None,
           "table": {}, "references": {}}
    for (form, g, H), ts in tickets.items():
        out["table"][f"{form}|{g}|H{H}"] = {"full": summ([t for _, _, t in ts]), "disc": summ([t for _, D, t in ts if D <= SPLIT]),
                                            "hold": summ([t for _, D, t in ts if D > SPLIT]),
                                            "by_asset": {a: summ([t for x, _, t in ts if x == a]) for a in T.ASSETS}}
    for (name, g, H), ts in refs.items():
        out["references"][f"{name}|{g}|H{H}"] = {"full": summ([t for _, _, t in ts]), "disc": summ([t for _, D, t in ts if D <= SPLIT]),
                                                 "hold": summ([t for _, D, t in ts if D > SPLIT])}
    # ── 事前写死的选法:drain 组、发现段;三道门;按均值排 ─────────────────────────────────────────
    cand = [(k, v) for k, v in out["table"].items() if "|drain|" in k and v["disc"].get("n", 0) >= MIN_N
            and v["disc"]["payoff"] >= MIN_PAYOFF and v["disc"]["worst_pct"] / 100 >= WORST_FLOOR]
    cand.sort(key=lambda kv: -kv[1]["disc"]["mean_pct"])
    hold_rank = sorted((k for k in out["table"] if "|drain|" in k and out["table"][k]["hold"].get("n", 0) >= 5),
                       key=lambda k: -out["table"][k]["hold"]["mean_pct"])
    pos = {k: i for i, k in enumerate(hold_rank)}
    out["selection"] = {"n_forms_drain": sum(1 for k in out["table"] if "|drain|" in k), "n_candidates": len(cand),
                        "top": [{"form": k, "disc": v["disc"], "hold": v["hold"], "full": v["full"],
                                 "hold_rank_pct": round(pos[k] / max(1, len(hold_rank) - 1), 3) if k in pos else None,
                                 "same_form_on_all": out["table"].get(k.replace("|drain|", "|all|"), {}).get("full")} for k, v in cand[:8]]}
    # ── 边际:每个旋钮各取值在 drain 组上的平均(全样本;看形状,不选) ─────────────────────────────────
    marg = {}
    for k, v in out["table"].items():
        if "|drain|" not in k or not v["full"].get("n"):
            continue
        b, gm, sch, tpn, _, hh = k.split("|")
        for knob, val in (("base", b), ("gamma", gm), ("scheme", sch), ("tp", tpn), ("H", hh)):
            marg.setdefault(knob, {}).setdefault(val, []).append(v["full"])
    out["marginals_drain"] = {knob: {val: {m: round(float(np.mean([x[m] for x in rows])), 3) for m in ("mean_pct", "worst_pct", "win", "payoff", "stopped_at_a_loss", "deployed")}
                                     for val, rows in vals.items()} for knob, vals in marg.items()}
    return out


def synthetic_labels(data: dict) -> dict:
    days, o, h, l, c = data[T.ASSETS[0]]
    lab = {}
    for i, d in enumerate(days):
        if i >= 200:
            below = c[d] < float(np.mean([c[x] for x in days[i - 199:i + 1]]))
            lab[d] = {"T": "线下" if below else "线上", "L": "抽" if (i // 90) % 2 == 0 else "注"}
    return lab


if __name__ == "__main__":
    selftest = "--selftest" in sys.argv
    if selftest:
        data = T.synthetic()
        labels, ref = synthetic_labels(data), T.run(data)
    else:
        data = {a: ([d for d in v[0] if d <= END], *v[1:]) for a, v in T.load_live().items()}
        daily = json.load(open(os.path.join(HERE, "s866_cells.json"), encoding="utf-8"))["daily"]
        labels = {dt.date.fromisoformat(k): {"T": v["T"], "L": v["L"]} for k, v in daily.items()}
        rp = os.path.join(HERE, "s865_results.json")
        ref = json.load(open(rp)) if os.path.exists(rp) else None
    out = run(data, labels, ref)
    print("REPRODUCES_S865", json.dumps(out["reproduces_s865"], ensure_ascii=False) if ref is not None else "没核(同目录下没有 s865_results.json)", flush=True)
    if not selftest and (out["reproduces_s865"] is None or not out["reproduces_s865"]["ok"]):
        print("STOP: R8 · 28 天与 S-865 的 K3 + X0 不同(或没有对照文件)—— 不往下报")
        sys.exit(2)
    for k in sorted(out["references"]):
        if "|H28" in k or "|drain|" in k:
            print("REF", k, json.dumps(out["references"][k]["full"], ensure_ascii=False), flush=True)
    for knob, vals in out["marginals_drain"].items():
        for val, m in vals.items():
            print("MARGINAL", knob, val, json.dumps(m, ensure_ascii=False), flush=True)
    print("SELECTION", out["selection"]["n_candidates"], "candidates of", out["selection"]["n_forms_drain"], flush=True)
    for t in out["selection"]["top"]:
        print("TOP", t["form"], "| disc", json.dumps(t["disc"], ensure_ascii=False), "| hold", json.dumps(t["hold"], ensure_ascii=False),
              "| hold_rank_pct", t["hold_rank_pct"], "| on_all", json.dumps(t["same_form_on_all"], ensure_ascii=False), flush=True)
    if selftest:
        assert out["reproduces_s865"]["ok"], out["reproduces_s865"]
        tb = out["table"]
        k0, k3 = "B25|g+0|A0|T0|all|H28", "B25|g+0|A3|T0|all|H28"
        assert tb[k0]["full"]["deployed"] == 1.0 and tb[k3]["full"]["deployed"] < 1.0, "分批的平均已用仓位应小于一次进满"
        assert tb[k3]["full"]["worst_pct"] >= tb[k0]["full"]["worst_pct"] - 1e-9, "分批进,最坏一张的亏损不该比一次进满更大"
        assert tb[k0]["full"]["worst_pct"] >= -25.0 - 6.0, "固定 25% 止损:最坏一张应在 −25% 附近(合成数据有跳空)"
        assert len(out["table"]) == len(BASES) * len(GAMMAS) * len(SCHEMES) * len(TPS) * 3 * len(HORIZONS)
        # 不偷看:截断数据后,到期日在截断点之前的票一模一样
        a = T.ASSETS[0]
        days, o, h, l, c = data[a]
        cut = days[len(days) * 2 // 3]
        dz = [d for d in days if d <= cut]
        ix, iz = {d: i for i, d in enumerate(days)}, {d: i for i, d in enumerate(dz)}
        Ds = [D for D in T.entry_days(days, c, -1, "all") if D + dt.timedelta(days=95) <= cut][:60]
        assert Ds and all(ticket(days, o, h, l, c, ix, D, 0.25, "A3w", 84, 0.15) == ticket(dz, o, h, l, c, iz, D, 0.25, "A3w", 84, 0.15) for D in Ds)
        print("SELFTEST OK")
    else:
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
        print("WROTE", OUT)
