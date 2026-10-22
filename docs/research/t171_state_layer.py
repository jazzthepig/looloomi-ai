"""S-669: CIS v2 状态层只是描述 —— 标签稳定性 + 预测力检验(两段都报)。

预注册原文在台账 REFUTATION_LEDGER.md「S-669」一节(2026-10-22 04:26 UTC,写于对任何状态标签算任何收益之前)。
标签定义、两段切分、判法全部照抄,一字不改;实现只在「怎么落成代码」上有自由度,自由度都写在下面注释里。

宇宙(S-669 数据节「CIS 现有宇宙(加密 25 + 传统 33)+ World50 美股挂牌」):
  加密 25 = src/data/cis/cis_provider.py:CRYPTO_ASSETS 的键
  传统 33 = 同文件 US_EQUITIES/BONDS/COMMODITIES/FX/REAL_ESTATE/EM_EQUITY 六个 dict 的键
  World50 美股挂牌 = world50_mcap_weekly(source=shares_x_close_v3)最后一个**满编**快照日按 mcap_usd
             取前 50(select_members 的 n=50 口径),再按卡上写的「不带 . 后缀的 key」留下美股挂牌部分。
             快照是每周的,最后几天是增量写入的残缺行(实测 2026-09-25 只有 11 个 key),所以取最近的满编日。

价格:加密 asset_mcap_daily(source=coingecko_pro_market_chart) / 传统 ohlcv_daily(source=eodhd)。
资金费: funding_history(venue=binance_perp)按 funding_time[:10] 当日平均。
FNG / VIX: macro_daily 的 series=fng / series=vix(列名实测为 series,d,value)。

只用 publishable key,读,全量缓存到 <root>/research/t171/。用法:
    python3 docs/research/t171_state_layer.py [--root /Volumes/CometCloudAI/cometcloud-local]
"""
from __future__ import annotations

import json
import math
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv \
    else "/Volumes/CometCloudAI/cometcloud-local"
CACHE = os.path.join(ROOT, "research", "t171")
os.makedirs(CACHE, exist_ok=True)
sys.path.insert(0, REPO)

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_KEY", "")
if not URL or not KEY:
    raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY,退出(不要读 .env)")
HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY}

# ---- S-669 的时间窗(原文「2023-01 → 2026-09」)----
WIN_START, WIN_END = "2023-01-01", "2026-09-30"
# 价格要多取一段给 SMA200 预热;200 个交易日前推 ≈ 320 自然日,取 2022-01-01 起
FETCH_START = "2022-01-01"
SEG_A = ("2023-01-01", "2024-06-30")   # 段一
SEG_B = ("2024-07-01", "2026-09-30")   # 段二

CRYPTO25 = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "DOT", "NEAR", "SUI",
            "APT", "HYPE", "ARB", "OP", "POL", "STRK", "UNI", "AAVE", "LDO", "PENDLE",
            "LINK", "INJ", "TIA", "ONDO", "SKY"]
TRAD33 = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "XLF",
          "TLT", "IEF", "SHY", "TIP", "HYG", "LQD", "GLD", "SLV", "USO", "UNG", "CPER",
          "DBA", "UUP", "FXE", "FXY", "FXI", "VNQ", "IYR", "VNQI", "EEM", "VWO", "INDA", "EWZ"]

# 标签常量 —— 名字一字照抄 S-669,值只是代码里的标识
T_UP, T_DOWN, T_FLAT = "上升", "下降", "震荡"
M_STRONG, M_WEAK, M_MID = "强", "弱", "中"
C_HOT, C_COLD, C_NORM = "拥挤", "冷清", "正常"
S_GREED, S_FEAR, S_NEUT = "贪婪", "恐惧", "中性"
S_TENSE, S_CALM = "紧张", "平静"


# ---------------------------------------------------------------- 读取层
def _page(path: str, lo: int, hi: int) -> list:
    req = urllib.request.Request(URL + "/rest/v1/" + path, headers=dict(HDR, Range=f"{lo}-{hi}"))
    try:
        return json.loads(urllib.request.urlopen(req, timeout=300).read())
    except urllib.error.HTTPError as e:
        if e.code == 416:      # Range 越界 = 没有更多行
            return []
        raise


def _page_all(path: str, cap: int = 200_000) -> list:
    out, off = [], 0
    while off < cap:
        chunk = _page(path, off, off + 999)
        if not chunk:
            break
        out += chunk
        off += 1000
    return out


def _cached(name: str, fn):
    p = os.path.join(CACHE, name)
    if os.path.exists(p):
        return json.loads(open(p).read())
    rows = fn()
    open(p, "w").write(json.dumps(rows))
    return rows


def fetch_prices(symbols: list, mcap: bool) -> dict:
    """symbol → [(date, close)] 按日期升序。mcap=True 走 asset_mcap_daily(d 列),否则 ohlcv_daily(trade_date 列)。"""
    def one(sym):
        if mcap:
            q = (f"asset_mcap_daily?select=d,price&symbol=eq.{sym}&d=gte.{FETCH_START}"
                 f"&source=eq.coingecko_pro_market_chart&order=d")
            rows = _page_all(q)
            return sym, [(r["d"], float(r["price"])) for r in rows if r.get("price") is not None]
        q = (f"ohlcv_daily?select=trade_date,close&source=eq.eodhd&symbol=eq.{sym}"
             f"&trade_date=gte.{FETCH_START}&order=trade_date")
        rows = _page_all(q)
        return sym, [(r["trade_date"], float(r["close"])) for r in rows if r.get("close") is not None]

    out = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for sym, ser in ex.map(one, symbols):
            out[sym] = sorted(ser)
    return out


def fetch_funding(symbols: list) -> dict:
    """symbol → {date: 当日平均资金费率}。funding_time 是 8 小时戳,截到日再平均。"""
    def one(sym):
        q = (f"funding_history?select=funding_time,funding_rate&venue=eq.binance_perp"
             f"&symbol=eq.{sym}&funding_time=gte.{FETCH_START}T00:00:00Z&order=funding_time")
        rows = _page_all(q, cap=20_000)
        acc = defaultdict(list)
        for r in rows:
            if r.get("funding_rate") is not None:
                acc[r["funding_time"][:10]].append(float(r["funding_rate"]))
        return sym, {d: sum(v) / len(v) for d, v in acc.items()}

    out = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for sym, d in ex.map(one, symbols):
            out[sym] = d
    return out


def fetch_macro(series: str) -> dict:
    q = f"macro_daily?select=d,value&series=eq.{series}&d=gte.{FETCH_START}&order=d"
    return {r["d"]: float(r["value"]) for r in _page_all(q) if r.get("value") is not None}


def world50_us_listed() -> tuple[list, str, int]:
    """World50(按 mcap 前 50)里不带 . 后缀的 key = 美股挂牌部分。返回 (keys, 快照日, 满编数)。"""
    q = ("world50_mcap_weekly?select=key,d,mcap_usd&source=eq.shares_x_close_v3"
         f"&d=gte.{WIN_START}&order=d,key")
    rows = _page_all(q)
    byd = defaultdict(dict)
    for r in rows:
        byd[r["d"]][r["key"]] = float(r["mcap_usd"])
    # 满编日:key 数最多的那次;若并列取最近的。快照日限定 ≤ 窗口末(WIN_END),
    # 免得用 2026-10 的成分表回看 2023-01(成分前视)。
    full_n = max(len(v) for v in byd.values())
    snap = max(d for d, v in byd.items() if len(v) == full_n and d <= WIN_END)
    ranked = sorted(byd[snap].items(), key=lambda kv: -kv[1])
    top50 = [k for k, _ in ranked[:50]]
    return sorted(k for k in top50 if "." not in k), snap, full_n


# ---------------------------------------------------------------- 标签层(逐字照 S-669)
def trend_labels(closes: np.ndarray) -> list[tuple[str | None, bool]]:
    """返回 [(标签, 是否走了「历史不足 200 天 ⇒ 只用 SMA50」分支)]。
    上升 = 收盘 > SMA50 > SMA200;下降 = 收盘 < SMA50 < SMA200;其余 = 震荡。
    历史不足 200 天 ⇒ 只用 SMA50:收盘在上 / 下。窗口里有缺报价 ⇒ 该日无标签。"""
    n = len(closes)
    out = []
    for i in range(n):
        if i < 199:   # 不足 200 天 ⇒ 只用 SMA50
            if i < 49:
                out.append((None, True))
                continue
            w = closes[i - 49:i + 1]
            if not np.all(np.isfinite(w)):
                out.append((None, True))
                continue
            c, s50 = closes[i], float(w.mean())
            out.append((T_UP if c > s50 else T_DOWN, True))
        else:
            c = closes[i]
            w50 = closes[i - 49:i + 1]
            w200 = closes[i - 199:i + 1]
            if not (np.isfinite(c) and np.all(np.isfinite(w50)) and np.all(np.isfinite(w200))):
                out.append((None, False))
                continue
            s50, s200 = float(w50.mean()), float(w200.mean())
            out.append((T_UP if (c > s50 > s200) else T_DOWN if (c < s50 < s200) else T_FLAT, False))
    return out


def momentum_label(r30: float, pct: float) -> str:
    """组内 30 日收益前 20% = 强 / 后 20% = 弱 / 其余 = 中。pct = 组内分位 0..1。"""
    if pct >= 0.80:
        return M_STRONG
    if pct <= 0.20:
        return M_WEAK
    return M_MID


def crowding_label(z: float) -> str:
    return C_HOT if z > 1.0 else C_COLD if z < -1.0 else C_NORM


def sentiment_label_crypto(fng: float) -> str:
    return S_GREED if fng >= 75 else S_FEAR if fng <= 25 else S_NEUT


def sentiment_label_trad(vix: float) -> str:
    return S_TENSE if vix >= 25 else S_CALM if vix <= 15 else "VIX 中性"


# ---------------------------------------------------------------- 统计
def t_stat(xs: list[float]) -> tuple[float, int, float]:
    if len(xs) < 3:
        return float("nan"), len(xs), float("nan")
    a = np.asarray(xs, dtype=float)
    a = a[np.isfinite(a)]
    n = len(a)
    if n < 3:
        return float("nan"), n, float("nan")
    sd = float(a.std(ddof=1))
    if sd == 0:
        return float("nan"), n, float("nan")
    return float(a.mean() / (sd / math.sqrt(n))), n, float(a.mean())


def perm_p(xs: list[float], block: int = 20, n_boot: int = 2000, seed: int = 20261022):
    """块置换零分布的 p —— 4 周窗口重叠、自相关强,单点打乱会低估。用 apparatus 的 block_permute。

    **xs 必须按「名字优先」排列**(同一个名字的时间序列连在一起),block=20 才等于 4 周重叠期;
    若按日期优先排列,相邻点是同日的不同名字,块就打不到时间自相关上,p 会虚高。
    block 必须 < n/2,否则打乱不改变序列(装置抛 NoOpNull),这时按 n 缩 block。"""
    from src.data.evaluation.apparatus import (NoOpNull, block_permute,
                                               null_distribution, percentile_of)
    a = np.asarray([x for x in xs if math.isfinite(x)], dtype=float)
    n = len(a)
    b = min(block, max(2, n // 4))
    if n < 40 or b >= n // 2:
        return None
    obs = float(a.mean())
    try:
        null = null_distribution(lambda rng: float(np.asarray(block_permute(a, b, rng)).mean()),
                                n_boot, seed)
    except NoOpNull:
        return None
    return obs, percentile_of(obs, null)


def _shift(d: str, days: int) -> str:
    import datetime
    return (datetime.date.fromisoformat(d) + datetime.timedelta(days=days)).isoformat()


def fwd_index(cal: list[str], days: int, tol: int = 5) -> list[int | None]:
    """cal 上的第 i 行,往后 **days 个自然日** 的那行在哪(组日历上最近的一行,容差 tol 天)。

    S-669 写的是「30 日收益」和「之后 4 周」,没说是交易日还是自然日。这里统一按**自然日**:
    两组的日历密度差很多(加密 7 天/周、传统 5 天/周),按行数取会让传统的「4 周」变成 5.5 周、
    加密的「30 日」变成 30 天 —— 两组就没法比了。自然日口径下两边含义一致。"""
    import bisect
    out = []
    for d in cal:
        tgt = _shift(d, days)
        j = bisect.bisect_left(cal, tgt)
        cand = [k for k in (j - 1, j) if 0 <= k < len(cal)]
        if not cand:
            out.append(None)
            continue
        k = min(cand, key=lambda k: abs(_days(cal[k]) - _days(tgt)))
        out.append(k if abs(_days(cal[k]) - _days(tgt)) <= tol else None)
    return out


def _days(d: str) -> int:
    import datetime
    return datetime.date.fromisoformat(d).toordinal()


# ---------------------------------------------------------------- 主流程
def main() -> dict:
    res: dict = {"prereg": "S-669 (REFUTATION_LEDGER.md, 2026-10-22 04:26 UTC)",
                 "window": [WIN_START, WIN_END], "segments": [SEG_A, SEG_B]}

    w50_keys, snap, full_n = world50_us_listed()
    res["universe"] = {"crypto25": CRYPTO25, "trad33": TRAD33,
                       "world50_us_listed": w50_keys, "world50_snapshot": snap,
                       "world50_snapshot_full_keys": full_n,
                       "world50_top50_total": 50}
    print(f"[universe] crypto 25 · trad 33 · world50 快照 {snap} (满编 {full_n} key)"
          f" → 美股挂牌 {len(w50_keys)}", flush=True)

    trad_all = sorted(set(TRAD33) | set(w50_keys))

    px_crypto = _cached("px_crypto.json", lambda: fetch_prices(CRYPTO25, True))
    px_trad = _cached("px_trad.json", lambda: fetch_prices(trad_all, False))
    funding = _cached("funding.json", lambda: fetch_funding(CRYPTO25))
    fng = _cached("fng.json", lambda: fetch_macro("fng"))
    vix = _cached("vix.json", lambda: fetch_macro("vix"))

    res["data_coverage"] = {
        "crypto_prices": {s: (v[0][0], v[-1][0], len(v)) if v else None for s, v in px_crypto.items()},
        "trad_prices_missing": [s for s in trad_all if not px_trad.get(s)],
        "funding_coverage": {s: (min(d), max(d), len(d)) if d else None
                             for s, d in funding.items()},
        "fng": (min(fng), max(fng), len(fng)) if fng else None,
        "vix": (min(vix), max(vix), len(vix)) if vix else None,
    }

    # ---- 建面板:每个组一张 date × name 的 close / fwd28 表 ----
    panels = {}
    for gname, members, px, is_crypto in (("加密", CRYPTO25, px_crypto, True),
                                          ("传统", trad_all, px_trad, False)):
        # 组日历 = 组内成员日期的并集里、每个成员都有的日子太少,改用「组内成员出现次数最多的日期集合」:
        # 取各成员日期的并集,再只保留至少 50% 成员有报价的日子。
        alldates = set()
        for s in members:
            alldates |= {d for d, _ in px.get(s, [])}
        n_mem = sum(1 for s in members if px.get(s))
        need = max(2, math.ceil(n_mem * 0.5))
        # 组日历 = 至少一半成员当日有报价的日子(周五/周末错位会自然掉出去)
        counts = defaultdict(int)
        for s in members:
            for d, _ in px.get(s, []):
                counts[d] += 1
        cal = sorted(d for d in alldates if counts[d] >= need)
        cal = [d for d in cal if WIN_START <= d <= WIN_END]
        cal_idx = {d: i for i, d in enumerate(cal)}
        fpos = fwd_index(cal, 28)        # 「之后 4 周」= 28 自然日
        mpos = fwd_index(cal, -30)       # 「30 日收益」= 回看 30 自然日
        closes, fwd, r30, trend, mom, crowd = {}, {}, {}, {}, {}, {}
        for s in members:
            ser = px.get(s) or []
            dmap = dict(ser)
            row = [dmap.get(d) for d in cal]
            a = np.asarray([np.nan if v is None else v for v in row], dtype=float)
            closes[s] = a
            f = np.full(len(a), np.nan)
            for i, j in enumerate(fpos):
                if j is not None and math.isfinite(a[i]) and math.isfinite(a[j]) and a[i] > 0:
                    f[i] = a[j] / a[i] - 1.0
            fwd[s] = f
            r = np.full(len(a), np.nan)
            for i, j in enumerate(mpos):
                if j is not None and math.isfinite(a[i]) and math.isfinite(a[j]) and a[j] > 0:
                    r[i] = a[i] / a[j] - 1.0
            r30[s] = r
            trend[s] = [t for t, _ in trend_labels(a)]
            mom[s] = [None] * len(cal)
            crowd[s] = [None] * len(cal)
        panels[gname] = dict(cal=cal, members=members, closes=closes, fwd=fwd, r30=r30,
                             trend=trend, mom=mom, crowd=crowd, is_crypto=is_crypto)

    # ---- 组内横截面:动量分位 / 组等权 / 超额 ----
    for gname, P in panels.items():
        cal, mem = P["cal"], P["members"]
        ew = np.full(len(cal), np.nan)
        for i in range(len(cal)):
            vals = [P["r30"][s][i] for s in mem]
            vals = [v for v in vals if v is not None and math.isfinite(v)]
            if len(vals) >= 2:
                ew[i] = float(np.mean(vals))
        P["mom_ew_ret"] = ew
        ew_f = np.full(len(cal), np.nan)
        for i in range(len(cal)):
            vals = [P["fwd"][s][i] for s in mem]
            vals = [v for v in vals if v is not None and math.isfinite(v)]
            if len(vals) >= 2:
                ew_f[i] = float(np.mean(vals))
        P["ew_fwd"] = ew_f
        # 动量:组内按日分位(同值用平均秩,免得重复报价被排到两端)
        for i in range(len(cal)):
            xs = [(s, P["r30"][s][i]) for s in mem
                  if P["r30"][s][i] is not None and math.isfinite(P["r30"][s][i])]
            if len(xs) < 5:
                continue
            vals = np.asarray([v for _, v in xs], dtype=float)
            order = vals.argsort().argsort().astype(float)
            for j, (s, v) in enumerate(xs):
                pct = (order[j] + 0.5) / len(vals)
                P["mom"][s][i] = momentum_label(v, pct)
        # 拥挤(仅加密):7 日平均资金费的组内 z
        if P["is_crypto"]:
            fd = {}
            for s in mem:
                fm = funding.get(s) or {}
                ser = np.asarray([np.nan if d not in fm else fm[d] for d in cal], dtype=float)
                ma = np.full(len(cal), np.nan)
                for i in range(len(cal)):
                    w = ser[max(0, i - 6):i + 1]
                    w = w[np.isfinite(w)]
                    if len(w) >= 3:
                        ma[i] = float(w.mean())
                fd[s] = ma
            for i in range(len(cal)):
                xs = [(s, fd[s][i]) for s in mem if math.isfinite(fd[s][i])]
                if len(xs) < 5:
                    continue
                arr = np.asarray([v for _, v in xs], dtype=float)
                mu, sd = arr.mean(), arr.std(ddof=1)
                if sd == 0:
                    continue
                for s, v in xs:
                    P["crowd"][s][i] = crowding_label((v - mu) / sd)

    # ================= 判 ① 稳定 =================
    stab = {}
    for gname, P in panels.items():
        cal, mem = P["cal"], P["members"]
        blocks = [(i, min(i + 30, len(cal))) for i in range(0, len(cal) - 29, 30)]
        for kind in ("trend", "mom", "crowd"):
            ch, rev3, cov = [], [], []
            for s in mem:
                lab = P[kind][s]
                for i0, i1 in blocks:
                    seq = [(i, lab[i]) for i in range(i0, i1) if lab[i] is not None]
                    if len(seq) < 10:
                        continue
                    n_ch = sum(1 for k in range(1, len(seq)) if seq[k][1] != seq[k - 1][1])
                    ch.append(n_ch)
                    cov.append(len(seq))
                    # 3 天内变回:每次切换后 3 个交易日内是否回到切换前的标签
                    for k in range(1, len(seq)):
                        if seq[k][1] == seq[k - 1][1]:
                            continue
                        prev = seq[k - 1][1]
                        rev3.append(1.0 if any(seq[j][1] == prev
                                                for j in range(k, min(k + 3, len(seq)))) else 0.0)
            if not ch:
                continue
            stab[f"{gname}/{kind}"] = {
                "n_name_blocks": len(ch), "mean_changes_per_30d": round(float(np.mean(ch)), 3),
                "median_changes_per_30d": round(float(np.median(ch)), 3),
                "p90_changes_per_30d": round(float(np.percentile(ch, 90)), 3),
                "revert_within_3d": round(float(np.mean(rev3)), 4) if rev3 else None,
                "n_switches": len(rev3),
                "mean_days_covered_per_block": round(float(np.mean(cov)), 1) if cov else None,
            }
    res["stability"] = stab
    # S-669 判法:趋势标签每 30 天 ≤ 2 次 = 能展示
    res["stability_verdict"] = {}
    for k, v in stab.items():
        if k.endswith("/trend"):
            res["stability_verdict"][k] = ("能展示" if v["median_changes_per_30d"] <= 2 else "不能展示")

    # ================= 判 ② 预测(两段都报) =================
    def seg_slice(cal, a, b):
        return [i for i, d in enumerate(cal) if a <= d <= b]

    pred = {}
    for gname, P in panels.items():
        cal, mem = P["cal"], P["members"]
        for kind, labels in (("trend", [T_UP, T_DOWN, T_FLAT]),
                             ("mom", [M_STRONG, M_WEAK, M_MID]),
                             ("crowd", [C_HOT, C_COLD, C_NORM])):
            if kind == "crowd" and not P["is_crypto"]:
                continue
            for lab in labels:
                key = f"{gname}/{kind}/{lab}"
                per_seg = {}
                for sname, (a, b) in (("A", SEG_A), ("B", SEG_B)):
                    idx = seg_slice(cal, a, b)
                    xs = []          # 名字优先排列:perm_p 的块要落在同一个名字的时间轴上
                    for s in mem:
                        for i in idx:
                            if P[kind][s][i] != lab:
                                continue
                            f, e = P["fwd"][s][i], P["ew_fwd"][i]
                            if f is not None and e is not None and math.isfinite(f) and math.isfinite(e):
                                xs.append(float(f) - float(e))
                    t, n, mu = t_stat(xs)
                    pp = perm_p(xs)
                    per_seg[sname] = {"mean_excess": round(mu, 6) if mu == mu else None,
                                      "t": round(t, 3) if t == t else None, "n": n,
                                      "perm_p": (round(pp[1], 4) if pp and pp[1] is not None else None)}
                okA = per_seg["A"]["mean_excess"]
                okB = per_seg["B"]["mean_excess"]
                same_sign = (okA is not None and okB is not None and okA * okB > 0)
                tt = {s: per_seg[s]["t"] for s in ("A", "B") if per_seg[s]["t"] is not None}
                # S-669 原文「两段同号且 |t| ≥ 2」对 |t| 指哪一段有歧义,两种读法都算,不替 Seth 选:
                #   宽松 = max(|t_A|, |t_B|) ≥ 2;严格 = 两段各自 |t| ≥ 2。
                loose = bool(tt) and max(abs(x) for x in tt.values()) >= 2.0
                strict = len(tt) == 2 and all(abs(x) >= 2.0 for x in tt.values())
                per_seg["same_sign"] = same_sign
                per_seg["candidate_strict"] = bool(same_sign and strict)
                per_seg["candidate_loose"] = bool(same_sign and loose)
                per_seg["candidate"] = bool(same_sign and strict)   # 以严格为主口径
                per_seg["verdict"] = ("候选(另立预注册,不采用)" if (same_sign and strict)
                                      else "描述,不是预测")
                pred[key] = per_seg

    # 组级标签:情绪 —— 组等权 4 周收益按标签分层,以及整体无条件均值作对照
    sent = {}
    for gname, series, fn, labs in (("加密", fng, sentiment_label_crypto,
                                     [S_GREED, S_FEAR, S_NEUT]),
                                    ("传统", vix, sentiment_label_trad,
                                     [S_TENSE, S_CALM, "VIX 中性"])):
        P = panels[gname]
        cal = P["cal"]
        # 周末/假日没有 macro 行 ⇒ 沿用最近一个观测(S-669 没写,取标准做法的最近值,并在报告里说明)
        cur, filled = None, 0
        vals = []
        for d in cal:
            if d in series:
                cur = series[d]
            else:
                filled += 1
            vals.append(cur)
        uncond = [P["ew_fwd"][i] for i in range(len(cal))
                  if P["ew_fwd"][i] is not None and math.isfinite(P["ew_fwd"][i])]
        tu, nu, mu = t_stat(uncond)
        per_lab = {}
        for lab in labs:
            xs = [P["ew_fwd"][i] for i in range(len(cal)) if vals[i] is not None
                  and fn(vals[i]) == lab and P["ew_fwd"][i] is not None
                  and math.isfinite(P["ew_fwd"][i])]
            t, n, m = t_stat(xs)
            pp = perm_p(xs)
            per_lab[lab] = {"mean_ew_fwd": round(m, 6) if m == m else None,
                            "t": round(t, 3) if t == t else None, "n": n,
                            "excess_vs_uncond": round(m - mu, 6) if (m == m and mu == mu) else None,
                            "perm_p": (round(pp[1], 4) if pp and pp[1] is not None else None)}
        sent[gname] = {"uncond_mean_ew_fwd": round(mu, 6) if mu == mu else None,
                       "uncond_t": round(tu, 3) if tu == tu else None, "n": nu,
                       "macro_fill_forward_days": filled, "labels": per_lab}
    res["sentiment_group_level"] = sent

    res["prediction"] = pred

    # ---- 汇总:候选标签 ----
    res["candidates"] = [k for k, v in pred.items() if v["candidate"]]
    res["candidates_loose_reading"] = [k for k, v in pred.items() if v["candidate_loose"]]
    res["descriptive_only"] = [k for k, v in pred.items() if not v["candidate"]]
    # 置换对照能不能活下来 —— 4 周窗口重叠,n 被严重放大,naive t 靠不住
    res["survives_permutation"] = [
        k for k, v in pred.items()
        if v["candidate"] and all((v[s]["perm_p"] is not None and v[s]["perm_p"] <= 0.05)
                                  for s in ("A", "B"))]

    out = os.path.join(HERE, "t171_results.json")
    open(out, "w").write(json.dumps(res, ensure_ascii=False, indent=2))
    mroot = os.path.join(ROOT, "_reports", "absorb_input")
    os.makedirs(mroot, exist_ok=True)
    open(os.path.join(mroot, "T-171_s669_results.json"), "w").write(
        json.dumps(res, ensure_ascii=False, indent=2))
    print("→", out)
    print("候选标签:", res["candidates"] or "无")
    return res


if __name__ == "__main__":
    main()