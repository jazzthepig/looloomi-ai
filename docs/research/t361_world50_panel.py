"""T-361 —— World50 回放用的月度面板,从 Mac 研究目录的 w50_daily/(close.json + mcap.json)重建。

原 T-099 的面板是 Supabase 导出的原始文本(在私有仓库,本机不可读)。这里用同一套语义重建:
  ret[symbol]  = 每月最后一个有价日的复权收盘 / 上月最后一个有价日的复权收盘 − 1
  mcap[季末月] = 该季末前 14 天内最后一个周点的市值(与 world50_mcap_weekly 同口径)
  cls          = crypto / metal / benchmark / equity

用法:python3 docs/research/t361_world50_panel.py
产物:Mac 研究目录 w50_daily/panel_t361.json + world50_replay_t361.json
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

R = Path("/Volumes/CometCloudAI/cometcloud-local/research/w50_daily")
CRYPTO = {"BTC", "ETH", "XRP", "BNB", "SOL"}
BENCH = {"ACWI", "AGG", "QQQ", "SPY"}
METALS = {"XAUUSD", "XAGUSD", "XPTUSD"}


def month_list(first: str, last: str) -> list[str]:
    y0, m0 = int(first[:4]), int(first[5:7])
    y1, m1 = int(last[:4]), int(last[5:7])
    out, y, m = [], y0, m0
    while (y, m) <= (y1, m1):
        out.append(f"{y}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def build() -> dict:
    c = json.loads((R / "close.json").read_text())
    dates = c["dates"]
    close = c["close"]
    mk = json.loads((R / "mcap.json").read_text())
    months = month_list("2015-01", "2026-09")
    ret: dict[str, list] = {}
    for sym, vals in close.items():
        per: dict[str, float] = {}
        for d, v in zip(dates, vals):
            if v is None:
                continue
            per[d[:7]] = float(v)
        row: list = []
        prev = None
        for m in months:
            v = per.get(m)
            row.append(None if (v is None or prev is None or prev <= 0) else v / prev - 1.0)
            if v is not None:
                prev = v
        if any(x is not None for x in row):
            ret[sym] = row
    mcap: dict[str, dict[str, float]] = {m: {} for m in months if m[5:] in ("03", "06", "09", "12")}
    for sym, pts in mk.items():
        for m in mcap:
            y, mm = int(m[:4]), int(m[5:7])
            y2, m2 = (y + 1, 1) if mm == 12 else (y, mm + 1)
            e = dt.date(y2, m2, 1) - dt.timedelta(days=1)
            lo = e - dt.timedelta(days=14)
            best = None
            for ds, v in pts:
                try:
                    d = dt.date.fromisoformat(ds)
                except ValueError:
                    continue
                if lo <= d <= e and v:
                    best = float(v)
            if best is not None:
                mcap[m][sym] = best
    cls = {k: ("crypto" if k in CRYPTO else "metal" if k in METALS else "benchmark" if k in BENCH else "equity") for k in ret}
    return {"months": months, "ret": ret, "mcap": mcap, "cls": cls}


if __name__ == "__main__":
    panel = build()
    p_out = R / "panel_t361.json"
    p_out.write_text(json.dumps(panel))
    print("panel:", len(panel["ret"]), "条收益序列 ·", sum(len(v) for v in panel["mcap"].values()), "个季末市值点 →", p_out)
    import t099_world50_replay as T099
    out = R / "world50_replay_t361.json"
    rep = T099.main(str(p_out), str(out))
    # 回放的报告里没有逐月收益(只有 stats 汇总),这里把 EWxMom 的逐月收益序列也落盘
    arms = T099.run_arm("EWxMom", panel["months"], panel["ret"],
                        {m: {k: float(v) for k, v in snap.items() if v} for m, snap in panel["mcap"].items()},
                        panel["cls"], {k: T099.closes_from_returns(v) for k, v in panel["ret"].items()})
    rep["arms"]["EWxMom"]["months"] = arms["months"]
    rep["arms"]["EWxMom"]["ret"] = [float(x) for x in arms["ret"]]
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str))
    print("window", rep["window"], "months", rep["months"])
    for a, s in rep["arms"].items():
        print(a, {k: s[k] for k in ("cagr", "vol", "max_dd_monthly", "avg_eff_n", "annual_turnover")})
    for b, s in rep["benchmarks"].items():
        print("bench", b, {k: s.get(k) for k in ("cagr", "vol", "max_dd_monthly", "why")})
