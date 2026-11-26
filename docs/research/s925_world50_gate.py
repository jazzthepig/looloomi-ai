"""S-925:模拟 —— World50 从 12-31 起执行「链上可持有 + 成交额下限」,指数会变成什么样。研究用,不进任何账。

只量**代价**(门槛之后还像不像「世界前 50 大资产」);可持有本身是 World50 的定义(Jazz 10-14),不在这里判。

- 数据:公司 = `world50_mcap_weekly`(source `shares_x_close_v3`,价 = 市值 / 股数,美元),加密 = `asset_mcap_daily`,
  黄金 = XAUUSD 收盘 × 可投资存量(`world50_data.metal_mcap_usd`);每月取月内最后一个点。与前向账本同源。
- 规则:回放的核原样(`t099_world50_replay.run_arm` → `world50.select_members`:12 月按市值重选、缓冲 40 / 60、
  季末重设权重、季内漂移、成本 10 / 20 bp);EW 与 EW×Mom;2015-12 → 2026-09。
- 资格(只改「谁能进排名」):G0 = 现规则;G1 = 链上可持有(`world50_onchain_forms` 10-14 → 11-17 的 21 次快照里出现过);
  G2 = G1 + 链上 24 小时成交额(各形式相加)21 次快照的中位数 ≥ 10 万美元。加密与黄金天然可持有,两道都免。
  **今天的链上状态倒着用到 2015**(有意:量的是「门槛之后的指数和原来差多远」,不是「当年买得到什么」)。
- 12-31 预演:最新一个月的市值、上一期成分 = 10-28 的 50 个,按 G0 / G1 / G2 各重选一次。

`ONCHAIN_MEDIAN_VOL_USD` 是 2026-11-26 从 `world50_onchain_forms` 量出来的冻结表(那张表 lane 读不到;S-925 写的就是这一份)。

用法(仓库根目录):
    python3 docs/research/s925_world50_gate.py --selftest
    python3 docs/research/s925_world50_gate.py --from-json monthly.json     # {key: {"YYYY-MM": [mcap 或 null, 价 或 null]}}
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from src.data.universe.world50 import CANDIDATES, rank_by_mcap, select_members  # noqa: E402
from src.data.universe.world50_data import metal_mcap_usd  # noqa: E402

_sp = importlib.util.spec_from_file_location("t099", os.path.join(HERE, "t099_world50_replay.py"))
T = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(T)

OUT = "docs/research/s925_results.json"
FLOOR_USD = 100_000
ARMS = ("EW", "EWxMom")
MEMBERS_1028 = ("XAUUSD,NVDA,AAPL,GOOGL,MSFT,AMZN,TSM,META,AVGO,BTC,TSLA,MU,005930.KO,LLY,BRK-B,AMD,000660.KO,JPM,WMT,V,ASML,XOM,JNJ,INTC,"
                "688825.SHG,TCEHY,MA,ABBV,PLTR,601939.SHG,CSCO,ORCL,COST,CVX,BAC,LRCX,AMAT,CAT,KO,MRK,ROG.SW,601288.SHG,DELL,HSBC,1398.HK,PG,"
                "GE,UNH,ARM,ETH").split(",")
#: 2026-11-26 量:world50_onchain_forms 10-14 → 11-17(21 次快照),同一公司各链上形式的 24 小时成交额相加,取 21 次的中位数(美元)
ONCHAIN_MEDIAN_VOL_USD = {
    "XAUUSD": 322606307, "NVDA": 90274185, "GOOGL": 42182080, "MU": 41569112, "TSLA": 35648710, "META": 24388137, "000660.KO": 22026235,
    "AAPL": 20221960, "AMZN": 19168817, "INTC": 16049948, "MSFT": 12324402, "AMD": 12152435, "PLTR": 7138189, "ORCL": 4056673,
    "AVGO": 3800351, "COST": 3789622, "MRVL": 3563583, "BABA": 3357428, "NFLX": 3002876, "TSM": 2804079, "KO": 2785392, "LLY": 2728089,
    "XAGUSD": 2467819, "WDC": 1732042, "QCOM": 1705966, "DELL": 1659306, "JPM": 1603091, "MCD": 1570800, "ASML": 1519648, "XOM": 1359837,
    "IBM": 1344356, "STX": 1291866, "SHOP": 1188324, "UBER": 1168564, "ARM": 1089320, "CVX": 952327, "ADBE": 902581, "WMT": 877722,
    "AMAT": 848640, "CRM": 803318, "NVO": 798464, "CRWD": 782947, "MA": 604523, "ACN": 600812, "BA": 584932, "UNH": 573973, "ANET": 571204,
    "GEV": 562151, "LRCX": 557753, "PBR": 524618, "COP": 488481, "NOW": 469556, "GS": 405714, "PFE": 379546, "CSCO": 302970, "ETN": 246205,
    "BAC": 209788, "DIS": 177937, "ISRG": 165216, "GE": 162489, "PANW": 158651, "BLK": 157058, "TXN": 156067, "AMGN": 154194, "CAT": 151513,
    "PG": 130964, "PEP": 130379, "ABT": 101397, "BRK-B": 61507, "TCEHY": 54442, "ABBV": 27994, "BP": 22851, "CMCSA": 18620, "HD": 16694,
    "LIN": 15449, "JNJ": 13782, "BKNG": 13635, "DHR": 11314, "RIO": 9776, "VLO": 9307, "KLAC": 8004, "FTNT": 7042, "RTX": 4435, "SONY": 4403,
    "V": 2812, "MO": 2292, "NVS": 1472, "MPC": 1187, "DE": 1107, "UL": 1057, "IBKR": 1029, "MS": 917, "TMUS": 543, "SAN": 470, "TMO": 403,
    "SCHW": 385, "CB": 375, "XPTUSD": 349, "MRK": 283, "PGR": 223, "PM": 181, "BUD": 114, "NEE": 104, "AZN": 99, "SAP": 58, "WFC": 50,
    "VZ": 48, "VRTX": 38, "SCCO": 33, "TM": 30, "BTI": 30, "C": 29, "T": 25, "TJX": 17, "SHEL": 11, "WELL": 11, "UNP": 6, "PLD": 1}
CLS = {c.key: c.cls for c in CANDIDATES}


def eligible(key: str, gate: str) -> bool:
    if gate == "G0" or CLS.get(key) in ("crypto", "metal"):
        return True
    if key not in ONCHAIN_MEDIAN_VOL_USD:
        return False
    return gate == "G1" or ONCHAIN_MEDIAN_VOL_USD[key] >= FLOOR_USD


def build(monthly: dict) -> tuple:
    """月度面板 → 回放核的输入:months、rets(月价格收益)、mcap_q(季末市值,只含候选)、closes。"""
    keys = [k for k in monthly if k in CLS and k not in ("XAGUSD", "XPTUSD")]
    months = sorted({m for k in keys for m in monthly[k]})
    rets = {}
    for k in keys:
        px = [monthly[k].get(m, [None, None])[1] for m in months]
        rets[k] = [None] + [(b / a - 1) if a and b and a > 0 else None for a, b in zip(px, px[1:])]
    mcap_q = {}
    for m in months:
        snap = {}
        for k in keys:
            v = monthly[k].get(m)
            if not v:
                continue
            mc = metal_mcap_usd("XAUUSD", v[1]) if k == "XAUUSD" and v[1] else v[0]
            if mc and mc > 0:
                snap[k] = float(mc)
        mcap_q[m] = snap
    closes = {k: T.closes_from_returns(v) for k, v in rets.items()}
    return months, rets, mcap_q, closes


def gated(mcap_q: dict, gate: str) -> dict:
    return {m: {k: v for k, v in s.items() if eligible(k, gate)} for m, s in mcap_q.items()}


def members_by_december(months, mcap_q) -> dict:
    """每年 12 月的重选结果(与 run_arm 同一个缓冲规则),用来量 G0 / G 的成分重合。"""
    out, prev = {}, []
    for m in months:
        if m[5:] == "12" and T.FIRST_SELECTION <= m <= T.LAST_MONTH:
            prev = [k for k in select_members(rank_by_mcap(mcap_q.get(m, {})), previous=prev, n=50)]
            out[m] = prev
    return out


def compare(base: list, other: list) -> dict:
    d = np.array(other) - np.array(base)
    return {"te_ann": round(float(d.std(ddof=1) * math.sqrt(12)), 4), "diff_ann": round(float(d.mean() * 12), 4)}


def preview(monthly: dict, month: str) -> dict:
    snap = {}
    for k, pts in monthly.items():
        if k not in CLS or k in ("XAGUSD", "XPTUSD") or month not in pts:
            continue
        mc, px = pts[month]
        mc = metal_mcap_usd("XAUUSD", px) if k == "XAUUSD" and px else mc
        if mc and mc > 0:
            snap[k] = mc
    out = {}
    for g in ("G0", "G1", "G2"):
        s = {k: v for k, v in snap.items() if eligible(k, g)}
        prev = [k for k in MEMBERS_1028 if eligible(k, g)]
        out[g] = select_members(rank_by_mcap(s), previous=prev, n=50)
    out["out_G1_vs_G0"] = [k for k in out["G0"] if k not in out["G1"]]
    out["in_G1_vs_G0"] = [k for k in out["G1"] if k not in out["G0"]]
    out["out_G2_vs_G0"] = [k for k in out["G0"] if k not in out["G2"]]
    out["in_G2_vs_G0"] = [k for k in out["G2"] if k not in out["G0"]]
    out["G0_vs_1028_out"] = [k for k in MEMBERS_1028 if k not in out["G0"]]
    out["G0_vs_1028_in"] = [k for k in out["G0"] if k not in MEMBERS_1028]
    out["not_rankable_1028"] = [k for k in MEMBERS_1028 if k not in snap]
    return out


def run(monthly: dict, preview_month: str) -> dict:
    months, rets, mcap_q, closes = build(monthly)
    res = {"months": [months[0], months[-1]], "arms": {}, "overlap": {}}
    series = {}
    for g in ("G0", "G1", "G2"):
        mq = gated(mcap_q, g)
        for a in ARMS:
            r = T.run_arm(a, months, rets, mq, CLS, closes)
            series[(g, a)] = r["ret"]
            st = T.stats(r["ret"])
            res["arms"][f"{g}|{a}"] = {k: st.get(k) for k in ("cagr", "vol", "max_dd_monthly", "calmar")} | {"annual_turnover": round(float(r["annual_turnover"]), 2)}
        if g != "G0":
            dec0, decg = members_by_december(months, mcap_q), members_by_december(months, mq)
            res["overlap"][g] = {m: len(set(dec0[m]) & set(decg[m])) for m in dec0}
    for g in ("G1", "G2"):
        for a in ARMS:
            res["arms"][f"{g}|{a}"]["vs_G0"] = compare(series[("G0", a)], series[(g, a)])
    te = res["arms"]["G2|EW"]["vs_G0"]["te_ann"]
    res["verdict"] = {"te_G2_EW": te, "advice": "G2" if te <= 0.03 else ("G1" if te <= 0.05 else "separate_book")}
    res["preview"] = preview(monthly, preview_month)
    res["preview_month"] = preview_month
    return res


def synthetic() -> dict:
    rng = np.random.default_rng(925)
    months = [f"{y}-{m:02d}" for y in range(2015, 2027) for m in range(1, 13)][:141]
    keys = [k for k in CLS if k not in ("XAGUSD", "XPTUSD")][:90] + ["XAUUSD", "BTC"]
    out = {}
    for i, k in enumerate(keys):
        px, mc = 100.0, 1e11 * (1 + i % 30)
        pts = {}
        for m in months:
            g = math.exp(rng.normal(0.006, 0.07))
            px, mc = px * g, mc * g
            pts[m] = [None if k == "XAUUSD" else mc, px if k != "XAUUSD" else 1500 + 10 * len(pts)]
        out[k] = pts
    return out


if __name__ == "__main__":
    selftest = "--selftest" in sys.argv
    if selftest:
        monthly = synthetic()
        pm = "2026-09"
    else:
        monthly = json.load(open(sys.argv[sys.argv.index("--from-json") + 1]))
        pm = max(m for k in monthly for m in monthly[k])
    out = run(monthly, pm)
    print("WINDOW", json.dumps(out["months"]), "| preview month", pm, flush=True)
    for k, v in out["arms"].items():
        print("ARM", k, json.dumps(v), flush=True)
    for g, ov in out["overlap"].items():
        print("OVERLAP", g, json.dumps(ov), flush=True)
    pv = out["preview"]
    print("PREVIEW", json.dumps({k: pv[k] for k in pv if k not in ("G0", "G1", "G2")}, ensure_ascii=False), flush=True)
    print("VERDICT", json.dumps(out["verdict"]), flush=True)
    if selftest:
        assert eligible("BTC", "G2") and eligible("XAUUSD", "G2") and not eligible("005930.KO", "G1") and eligible("ABBV", "G1") and not eligible("ABBV", "G2")
        # G0 的 EW 与回放核直接跑的一样(没有换掉核)
        months, rets, mcap_q, closes = build(monthly)
        r0 = T.run_arm("EW", months, rets, mcap_q, CLS, closes)
        assert out["arms"]["G0|EW"]["cagr"] == T.stats(r0["ret"])["cagr"]
        assert all(len(v) == 50 for v in (pv["G0"], pv["G1"], pv["G2"]))
        print("SELFTEST OK")
    else:
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1, default=str)
        print("WROTE", OUT)
