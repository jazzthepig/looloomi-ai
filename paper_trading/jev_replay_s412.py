"""S-412 — Jev 当 Trader Tom 的 3.4 年历史回放(预注册见 REFUTATION_LEDGER §S-412)。

    python3 -m paper_trading.jev_replay_s412 --backend mech   离线自检:Jev 臂用机械答案,必须与机械 Tom 完全一致
    python3 -m paper_trading.jev_replay_s412 --backend jev    真实 Jev;需要 shell 里有 JEV_API_KEY

四个臂:H0 持有 · T3(每周 + 不动带)· 机械 Tom · Jev Tom。组合规则和换手限制见 `hl_book.py`。
Jev 回答按请求体哈希缓存在 `paper_trading/state/jev_replay_s412/`,重跑不重复计费。
调用失败即中止,不补默认值。
"""
from __future__ import annotations

# S-402 bootstrap(同 spec_runner / jev_smoke):以脚本路径运行时也能 import paper_trading.*
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parent.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import argparse
import math
import os
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from paper_trading import hl_book as hb

STATE_DIR = _ROOT / "paper_trading" / "state"
START = pd.Timestamp("2023-05-15")          # 周一;HL 真实资金费从 2023-05-12 起


class FakeJev:
    """离线自检用:从匿名状态里的特征重算机械代理,返回确定性的 Jev 形状回答。
    模式无法从匿名状态得到(需要知道哪个是 BTC),由调用方在调用前注入。"""

    def __init__(self):
        self.mode = "neutral"
        self.calls = 0
        self.input_tokens = 0

    def evaluate(self, state: dict, questions: dict) -> dict:
        ans = {}
        for a, f in state["assets"].items():
            m = hb.mechanical_answers({"X": f})
            ans[f"{a}__trend_confirmed"] = {"type": "noul", "noul": float(m.trend_confirmed["X"])}
            ans[f"{a}__crowded"] = {"type": "noul", "noul": float(m.crowded["X"])}
            ans[f"{a}__capitulation"] = {"type": "noul", "noul": float(m.capitulation["X"])}
        ans["book_mode"] = {"type": "choice", "choice": self.mode, "confidence": 1.0}
        self.calls += 1
        return {"answers": ans}


def simulate(px, fd, backend: str, client, max_new_calls: int):
    days = px.index[px.index >= START]
    mondays = [d for d in days if d.weekday() == 0]
    arms = ["H0_hold", "T3_weekly", "MECH_tom", "JEV_tom"] if backend != "none" else ["H0_hold", "T3_weekly", "MECH_tom"]
    W = {a: pd.DataFrame(np.nan, index=days, columns=px.columns) for a in arms}
    N = pd.Series(np.nan, index=days)
    book = {a: {} for a in arms}                 # coin -> {"w", "px"}
    log = []
    agree = {k: [] for k in ("trend_confirmed", "crowded", "capitulation", "mode")}
    fires = {k: [0, 0] for k in ("trend_confirmed", "crowded", "capitulation")}
    rng = random.Random(412)
    for t in mondays:
        feats = hb.features_at(px, fd, t)
        if not feats:
            continue
        N.loc[t] = len(feats)
        mech = hb.mechanical_answers(feats)
        for a in arms:
            cur = {c: v["w"] for c, v in book[a].items()}
            bstate = {c: {"w": v["w"], "ret_since": px[c].loc[t] / v["px"] - 1} for c, v in book[a].items()}
            if a == "H0_hold":
                new = {c: 1.0 for c in feats}
            elif a == "T3_weekly":
                new = hb.apply_turnover_limits({c: hb.t3_base(f) for c, f in feats.items()}, cur)
            elif a == "MECH_tom":
                new = hb.apply_turnover_limits(hb.tom_targets(feats, mech, bstate), cur)
            else:
                if isinstance(client, FakeJev):
                    client.mode = mech.mode
                if backend == "jev" and client.calls >= max_new_calls:
                    raise RuntimeError(f"已达本次调用上限 {max_new_calls},中止(缓存已保存,可续跑)")
                ja = hb.jev_answers(client, feats, bstate, rng)
                for k in ("trend_confirmed", "crowded", "capitulation"):
                    for c in feats:
                        agree[k].append(getattr(ja, k)[c] == getattr(mech, k)[c])
                        fires[k][0] += getattr(ja, k)[c]
                        fires[k][1] += getattr(mech, k)[c]
                agree["mode"].append(ja.mode == mech.mode)
                new = hb.apply_turnover_limits(hb.tom_targets(feats, ja, bstate), cur)
                log.append({"d": t.date().isoformat(), "jev_mode": ja.mode, "mech_mode": mech.mode,
                            **{f"w_{c}": round(v, 3) for c, v in new.items()}})
            for c in px.columns:
                W[a].loc[t, c] = new.get(c, 0.0)
            book[a] = {c: {"w": w, "px": px[c].loc[t]} for c, w in new.items() if w != 0}
    return {a: w.ffill() for a, w in W.items()}, N.ffill(), agree, fires, log


def pnl(w: pd.DataFrame, n: pd.Series, px: pd.DataFrame, fd: pd.DataFrame) -> tuple[pd.Series, dict]:
    r = px.pct_change().reindex(w.index)
    held = w.shift(2)
    nn = n.shift(2)
    spot = held.clip(lower=0, upper=1)
    perp = held - spot
    cost = spot.diff().abs() * hb.COST_SPOT + perp.diff().abs() * hb.COST_PERP
    fund = perp * fd.reindex(w.index).fillna(0)
    net = (held * r.fillna(0) - cost.fillna(0) - fund).sum(axis=1) / nn
    net = net[nn.notna()]
    yrs = len(net) / 365
    extra = {"turnover_yr": (held.diff().abs().sum(axis=1) / nn).sum() / yrs,
             "cost_yr": (cost.sum(axis=1) / nn).sum() / yrs,
             "fund_yr": (fund.sum(axis=1) / nn).sum() / yrs,
             "gross": (held.abs().sum(axis=1) / nn).mean()}
    return net, extra


def stats(x: pd.Series) -> dict:
    nav = (1 + x).cumprod()
    return {"total": nav.iloc[-1] - 1, "cagr": nav.iloc[-1] ** (365 / len(x)) - 1,
            "sharpe": x.mean() / x.std() * math.sqrt(365), "maxdd": (nav / nav.cummax() - 1).min()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["none", "mech", "jev"], default="mech")
    ap.add_argument("--cache", default=str(STATE_DIR / "hl_cache"))
    ap.add_argument("--max-new-calls", type=int, default=400)
    a = ap.parse_args()

    cache = Path(a.cache)
    hb.fetch_hl(cache)
    px, fd = hb.load_hl(cache)

    out_dir = STATE_DIR / "jev_replay_s412"
    out_dir.mkdir(parents=True, exist_ok=True)
    if a.backend == "jev":
        key = os.environ.get("JEV_API_KEY")
        if not key or not key.isascii() or len(key) < 16:
            print("✗ JEV_API_KEY 未设置或形状不对", file=sys.stderr)
            return 1
        client = hb.JevClient(out_dir / "jev_cache.jsonl", key)
    elif a.backend == "mech":
        client = FakeJev()
    else:
        client = None

    W, N, agree, fires, log = simulate(px, fd, a.backend, client, a.max_new_calls)

    print(f"\n══ S-412 · {START.date()} → {px.index[-1].date()} · 后端={a.backend} ══")
    print(f"{'':12s} {'总收益':>8s} {'CAGR':>7s} {'Sharpe':>7s} {'MaxDD':>7s} {'换手/年':>7s} {'成本/年':>7s} {'资金费/年':>8s} {'平均总仓位':>9s}   "
          + " ".join(f"{y:>6d}" for y in range(2023, 2027)))
    series = {}
    for arm, w in W.items():
        net, ex = pnl(w, N, px, fd)
        series[arm] = net
        s = stats(net)
        yrs = []
        for y in range(2023, 2027):
            xy = net[net.index.year == y]
            yrs.append(f"{xy.mean() / xy.std() * math.sqrt(365):6.2f}" if len(xy) > 60 else "   nan")
        print(f"{arm:12s} {s['total']:8.1%} {s['cagr']:7.1%} {s['sharpe']:7.2f} {s['maxdd']:7.1%} "
              f"{ex['turnover_yr']:7.2f} {ex['cost_yr']:7.2%} {ex['fund_yr']:8.2%} {ex['gross']:9.2f}   " + " ".join(yrs))

    if "JEV_tom" in W:
        dec = W["JEV_tom"].index.weekday == 0
        j = W["JEV_tom"][dec].stack()
        m = W["MECH_tom"][dec].stack()
        t3 = W["T3_weekly"][dec].stack()
        print(f"\n周度仓位相关:Jev vs 机械 Tom = {j.corr(m):.2f} · Jev vs T3 = {j.corr(t3):.2f}")
        print("与机械代理的一致率:", {k: round(float(np.mean(v)), 2) for k, v in agree.items() if v})
        print("触发次数 Jev / 机械:", {k: tuple(v) for k, v in fires.items()})
        if a.backend == "jev":
            print(f"本次新调用 {client.calls} 次 · input_tokens {client.input_tokens} · "
                  f"约 ${client.input_tokens * 0.042 / 1e6:.4f}")
        pd.DataFrame(log).to_csv(out_dir / f"decisions_{a.backend}.csv", index=False)
        if a.backend == "mech":
            same = np.allclose(W["JEV_tom"].fillna(0).values, W["MECH_tom"].fillna(0).values)
            print("自检:Jev 臂 ≡ 机械 Tom" if same else "✗ 自检失败:Jev 臂与机械 Tom 不一致")
            return 0 if same else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
