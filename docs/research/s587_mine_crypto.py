"""S-587 挖掘(加密横截面)—— 发现段 2020-01 → 2022-12,留出段 2023-01 → 2026-09(先预注册再跑一次)。

用法:python3 docs/research/s587_mine_crypto.py <crypto_daily 目录> [输出 json] [--holdout] [--top=50]
宇宙:每周按当时市值取前 N(去掉稳定币 / 包装币 / 低波动 —— 过去 26 周年化波动 < 15% 的视为类稳定币)。
信号(第 t 周收盘可知):r1 r2 r4 r13 r26、hi52(收盘 / 52 周最高)、vol13、beta52(对 BTC)、size(对数市值)、
supply13(流通量 13 周变化 = 市值 / 价格 之比的变化 —— 解锁 / 增发的稀释)。
统计同 S-586:每周 Spearman IC,平稳块自助 t(块长 = h);另报 BTC 过去 26 周 > 0 / ≤ 0 两种状态、前后两半。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from s584_world50_weekly_mom import fridays, weekly_closes  # noqa: E402
from s586_mine_world50 import boot_t, spearman  # noqa: E402

DISCOVERY = ("2020-01-01", "2022-12-31")
HOLDOUT = ("2023-01-01", "2026-09-25")
HORIZONS = (1, 2, 4, 13)
SIGNALS = ("r1", "r2", "r4", "r13", "r26", "hi52", "vol13", "beta52", "size", "supply13", "combo")
#: combo = 事先定死的等权合成:−秩(vol13) − 秩(supply13) + 秩(size),在当周宇宙内算秩(S-587 预注册前加入,发现段也报)
WRAPPED = {"WBTC", "WETH", "STETH", "WSTETH", "CBBTC", "RETH", "WEETH", "EETH", "TBTC", "BTCB", "CBETH", "METH", "EZETH",
           "RSETH", "LBTC", "SOLVBTC", "CLBTC", "BUIDL", "USDT", "USDC", "DAI", "USDE", "SUSDE", "FDUSD", "PYUSD", "USDS",
           "USD1", "TUSD", "USDD", "FRAX", "RLUSD", "USDTB", "USDF", "USDG", "BFUSD", "XAUT", "PAXG", "JITOSOL", "MSOL",
           "BNSOL", "JUPSOL", "OUSG", "USYC", "BENJI", "WBETH", "SAVAX", "OSETH", "SFRXETH", "FIGR_HELOC"}


def main(dir_: str, out_path: Optional[str] = None, holdout: bool = False, top: int = 50) -> dict[str, Any]:
    window = HOLDOUT if holdout else DISCOVERY
    p = json.loads((Path(dir_) / "panel.json").read_text())
    grid = fridays("2019-06-07", "2026-10-16")
    syms = [s for s in p["price"] if s.upper() not in WRAPPED]
    P = np.array([[x if x else np.nan for x in weekly_closes(p["dates"], p["price"][s], grid)] for s in syms], dtype=float)
    C = np.array([[x if x else np.nan for x in weekly_closes(p["dates"], p["mcap"][s], grid)] for s in syms], dtype=float)
    n, T = P.shape
    bi = syms.index("BTC")
    lr = np.full_like(P, np.nan)
    lr[:, 1:] = np.log(P[:, 1:] / P[:, :-1])
    sig: dict[str, np.ndarray] = {}
    for k in (1, 2, 4, 13, 26):
        a = np.full_like(P, np.nan)
        a[:, k:] = P[:, k:] / P[:, :-k] - 1
        sig[f"r{k}"] = a
    hi = np.full_like(P, np.nan)
    v13 = np.full_like(P, np.nan)
    v26 = np.full_like(P, np.nan)
    beta = np.full_like(P, np.nan)
    sup = np.full_like(P, np.nan)
    with np.errstate(all="ignore"):
        units = C / P
        sup[:, 13:] = units[:, 13:] / units[:, :-13] - 1
        for t in range(T):
            if t >= 13:
                w = lr[:, t - 12: t + 1]
                v13[:, t] = np.where(np.isfinite(w).sum(axis=1) >= 10, np.nanstd(w, axis=1, ddof=1) * math.sqrt(52), np.nan)
            if t >= 26:
                w = lr[:, t - 25: t + 1]
                v26[:, t] = np.where(np.isfinite(w).sum(axis=1) >= 20, np.nanstd(w, axis=1, ddof=1) * math.sqrt(52), np.nan)
            if t >= 52:
                hi[:, t] = P[:, t] / np.nanmax(P[:, t - 51: t + 1], axis=1)
                b = lr[bi, t - 51: t + 1]
                for i in range(n):
                    x = lr[i, t - 51: t + 1]
                    ok = np.isfinite(x) & np.isfinite(b)
                    if ok.sum() >= 40 and b[ok].var() > 0:
                        beta[i, t] = np.cov(x[ok], b[ok])[0, 1] / b[ok].var(ddof=1)
    sig.update({"hi52": hi, "vol13": v13, "beta52": beta, "size": np.log(C), "supply13": sup})
    btc = P[bi]
    res: dict[str, Any] = {"window": window, "top": top, "symbols": n, "signals": {}}
    for h in HORIZONS:
        fwd = np.full_like(P, np.nan)
        fwd[:, : T - h] = P[:, h:] / P[:, : T - h] - 1
        for sname in SIGNALS:
            ics, states, sizes = [], [], []
            for t in range(T - h):
                g = grid[t]
                if not (window[0] <= g <= window[1]) or (not holdout and grid[t + h] > window[1]):
                    continue
                m = C[:, t]
                ok = np.isfinite(m) & np.isfinite(P[:, t]) & (v26[:, t] >= 0.15)
                if ok.sum() < 20:
                    continue
                cut = np.sort(m[ok])[::-1][min(top, ok.sum()) - 1]
                uni = ok & (m >= cut)
                if sname == "combo":
                    parts = [sig["vol13"][uni, t], sig["supply13"][uni, t], sig["size"][uni, t]]
                    okc = np.all([np.isfinite(x) for x in parts], axis=0)
                    x = np.full(int(uni.sum()), np.nan)
                    if okc.sum() >= 10:
                        rk = [np.argsort(np.argsort(v[okc])) / (okc.sum() - 1) for v in parts]
                        x[okc] = -rk[0] - rk[1] + rk[2]
                    ic = spearman(x, fwd[uni, t])
                else:
                    ic = spearman(sig[sname][uni, t], fwd[uni, t])
                if ic is None:
                    continue
                ics.append(ic)
                sizes.append(int(uni.sum()))
                up = t >= 26 and np.isfinite(btc[t]) and np.isfinite(btc[t - 26]) and btc[t] > btc[t - 26]
                states.append("up" if up else "down")
            if not ics:
                continue
            mean, tstat = boot_t(ics, h)
            half = len(ics) // 2
            res["signals"][f"{sname}|h{h}"] = {
                "n": len(ics), "ic": mean, "t": tstat, "avg_names": float(np.mean(sizes)),
                "ic_first_half": float(np.mean(ics[:half])), "ic_second_half": float(np.mean(ics[half:])),
                "ic_up": float(np.mean([x for x, s in zip(ics, states) if s == "up"])) if "up" in states else None,
                "ic_down": float(np.mean([x for x, s in zip(ics, states) if s == "down"])) if "down" in states else None,
                "n_down": states.count("down")}
    if out_path:
        Path(out_path).write_text(json.dumps(res, ensure_ascii=False, indent=1))
    return res


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    top = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--top=")), 50))
    r = main(args[0], args[1] if len(args) > 1 else None, "--holdout" in sys.argv, top)
    print("window", r["window"], "top", r["top"], "symbols", r["symbols"])
    rows = sorted(r["signals"].items(), key=lambda kv: -abs(kv[1]["t"]) if math.isfinite(kv[1]["t"]) else 0)
    for k, v in rows:
        f = lambda x: f"{x:+.3f}" if x is not None else "  nan"
        print(f"{k:12s} n {v['n']:4d} names {v['avg_names']:.0f}  IC {v['ic']:+.4f}  t {v['t']:+5.2f}  halves {f(v['ic_first_half'])}/{f(v['ic_second_half'])}  "
              f"up {f(v['ic_up'])}  down {f(v['ic_down'])} (n {v['n_down']})")
