"""崩盘图谱的「现在亮着哪些」—— S-675 的迹象定义在最新一天的读数(FRED 快照能算的那部分)。

只做描述,不是信号:每个迹象的提升倍数 / 分位来自三道的挖掘报告(T-185 / T-186 / T-187),是探索性的。
定义逐字照台账 S-675;经济数据先过 `available()`(发布滞后),市场价格滞后 0;按时点分位用 `expanding_pct`。
加密专属的 C1–C6 与 E4(要库里的数)由 Seth 用 SQL 补进报告,不在本文件里。
用法:python3 docs/research/crash_atlas_now.py [--fred <数据根>/research/crash_atlas/fred] [--out <json>]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crash_atlas_common as ca  # noqa: E402


def series(sid: str, fred_dir: str) -> pd.Series:
    """FRED → 能看到的那天 → 日历日(向前填最多 7 天,周频 / 月频按协议发布滞后后移)。"""
    s = ca.available(ca.load_fred(sid, fred_dir), sid)
    gap = 40 if sid == "UMCSENT" else 10
    return ca.to_calendar(s, max_gap_days=gap)


def last(s: pd.Series) -> tuple[str, float]:
    s = s.dropna()
    return s.index[-1].date().isoformat(), float(s.iloc[-1])


def price_signs(px: pd.Series) -> dict:
    """P1–P5 在一个价格序列上(交易日序列,按时点)。"""
    px = px.dropna()
    r252 = px / px.shift(252) - 1
    ext = px / px.rolling(200).mean() - 1
    vol = np.log(px).diff().rolling(20).std() * np.sqrt(252)
    hi52 = px.rolling(252).max()
    p1, p2, p3 = ca.expanding_pct(r252), ca.expanding_pct(ext), ca.expanding_pct(vol)
    d = px.index[-1].date().isoformat()
    off_hi = float(px.iloc[-1] / hi52.iloc[-1] - 1)
    above200 = bool(ext.iloc[-1] > 0)
    return {"asof": d,
            "P1": {"value": float(p1.iloc[-1]), "lit": bool(p1.iloc[-1] >= 0.9), "def": "252 日收益按时点分位 ≥ 0.9"},
            "P2": {"value": float(p2.iloc[-1]), "lit": bool(p2.iloc[-1] >= 0.9), "def": "价格 / 200 日线 − 1 分位 ≥ 0.9"},
            "P3": {"value": float(p3.iloc[-1]), "lit": bool(p3.iloc[-1] <= 0.1), "def": "20 日实现波动分位 ≤ 0.1"},
            "P4": {"value": float(p3.iloc[-1]), "lit": bool(p3.iloc[-1] >= 0.9), "def": "20 日实现波动分位 ≥ 0.9"},
            "P5": {"value": off_hi, "lit": bool(off_hi <= -0.05 and above200), "def": "离 52 周高 ≥ 5% 但仍在 200 日线上",
                   "above_200": above200}}


def macro_signs(fd: str) -> dict:
    out = {}
    dff = series("DFF", fd)
    d, v = last(dff - dff.shift(365))
    out["M1"] = {"asof": d, "value": v, "lit": v >= 1.0, "def": "联邦基金利率 12 个月升 ≥ 1pp"}
    t = series("T10Y2Y", fd)
    d, v = last(t)
    out["M2"] = {"asof": d, "value": v, "lit": v < 0, "def": "10Y − 2Y < 0"}
    inv365 = (t < 0).astype(float).rolling(366, min_periods=1).max()
    out["M3"] = {"asof": d, "value": v, "lit": bool(v > 0 and inv365.iloc[-1] > 0),
                 "def": "10Y − 2Y > 0 且过去 365 天内倒挂过", "inverted_within_365d": bool(inv365.iloc[-1] > 0)}
    d, v = last(series("NFCI", fd))
    out["M4"] = {"asof": d, "value": v, "lit": v > 0, "def": "NFCI > 0(发布滞后 5 天)"}
    b = series("BAA10Y", fd)
    d, v = last(b - b.shift(63))
    out["M5"] = {"asof": d, "value": v, "lit": v >= 0.5, "def": "Baa − 10Y 63 天升 ≥ 0.5pp"}
    vix = series("VIXCLS", fd)
    d, v = last(vix)
    out["M6"] = {"asof": d, "value": v, "lit": v < 13, "def": "VIX < 13"}
    out["M7"] = {"asof": d, "value": v, "lit": v > 30, "def": "VIX > 30"}
    d, v = last(vix / series("VXVCLS", fd))
    out["M8"] = {"asof": d, "value": v, "lit": v > 1, "def": "VIX / VXV > 1"}
    usd = series("DTWEXBGS", fd)
    p = ca.expanding_pct(usd / usd.shift(63) - 1)
    d, v = last(p)
    out["M9"] = {"asof": d, "value": v, "lit": v >= 0.9, "def": "美元广义指数 63 天变化分位 ≥ 0.9"}
    w = series("DCOILWTICO", fd)
    d, v = last(w / w.shift(126) - 1)
    out["M10"] = {"asof": d, "value": v, "lit": v >= 0.5, "def": "WTI 126 天涨 ≥ 50%"}
    bs = series("WALCL", fd)
    d, v = last(bs / bs.shift(91) - 1)
    out["M11"] = {"asof": d, "value": v, "lit": v < 0, "def": "美联储资产负债表 91 天缩(发布滞后 1 天)"}
    um = series("UMCSENT", fd)
    d, v = last(ca.expanding_pct(um))
    out["M12"] = {"asof": d, "value": v, "lit": v >= 0.8, "def": "密歇根消费者信心分位 ≥ 0.8(滞后 1 个月)"}
    ic = series("ICSA", fd)
    ic4 = ic.rolling(28, min_periods=20).mean()
    d, v = last(ic4 / ic4.shift(91) - 1)
    out["M13"] = {"asof": d, "value": v, "lit": v >= 0.15, "def": "初请 4 周均值 13 周升 ≥ 15%(发布滞后 5 天)"}
    return out


def em_signs(fd: str) -> dict:
    out = {}
    worst = None
    for sid in ("DEXKOUS", "DEXBZUS", "DEXMXUS", "DEXINUS"):
        s = series(sid, fd)
        d, v = last(s / s.shift(63) - 1)
        if worst is None or v > worst[2]:
            worst = (sid, d, v)
    out["E1"] = {"asof": worst[1], "value": worst[2], "worst": worst[0], "lit": worst[2] >= 1 / 0.9 - 1,
                 "def": "KRW / BRL / MXN / INR 任一 63 天贬 ≥ 10%(= 美元兑它涨 ≥ 11.11%,B 道协议问题 1)"}
    cn = series("DEXCHUS", fd)
    d, v = last(cn / cn.shift(21) - 1)
    out["E2"] = {"asof": d, "value": v, "lit": v >= 0.02, "def": "人民币 21 天贬 ≥ 2%"}
    d, v = last(series("VXEEMCLS", fd))
    out["E3"] = {"asof": d, "value": v, "lit": v > 30, "def": "VXEEM > 30"}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fred", default=ca.FRED_DIR)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "crash_atlas_now.json"))
    a = ap.parse_args()
    nas = ca.load_fred("NASDAQCOM", a.fred)
    res = {"nasdaq_P": price_signs(nas), "macro_M": macro_signs(a.fred), "em_E": em_signs(a.fred),
           "fred_manifest_last": {k: v.get("last") for k, v in json.load(open(os.path.join(a.fred, "manifest.json"))).items()
                                  if isinstance(v, dict)}}
    json.dump(res, open(a.out, "w"), indent=1, default=str)
    lit = [k for grp in ("nasdaq_P", "macro_M", "em_E") for k, v in res[grp].items() if isinstance(v, dict) and v.get("lit")]
    print(json.dumps({"lit": lit, **{g: {k: (round(v["value"], 4), v["lit"]) for k, v in res[g].items() if isinstance(v, dict)}
                                     for g in ("nasdaq_P", "macro_M", "em_E")}}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
