#!/usr/bin/env python3
"""T-364 / S-841 —— 跨资产趋势袖套(SPY / EEM / GLD / TLT / USO,可多可空,不含加密)
按 S-835 的准入标准 (i)–(iv) 判一次。

预注册:REFUTATION_LEDGER.md 的「## S-841 —」一节(Seth,2026-11-13 06:04 UTC)——
规则、数据拼接、判据、零信号对照一字照做。装配/叠加口径照 T-363 返工后的
docs/research/t363_admission_table.py(A_aug = A_base + w·r − w·r_cash;统计量写死)。

只读 ohlcv_daily;不入库;不改规则;只算一次。

用法:
  python3 t364_cross_asset_trend.py --fetch-only    # 只抓数,打印每个 (symbol, source) 的行数与日期范围
  python3 t364_cross_asset_trend.py                 # 全流程,结果落 t364_results.json / T-364_*.md
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import urllib.parse
import urllib.request
import warnings
from collections import OrderedDict

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
R = "/Volumes/CometCloudAI/cometcloud-local/research/"

import t310_slots as T310                                          # noqa: E402
from src.data.evaluation import apparatus as ap                    # noqa: E402
from src.data.universe import flex_alloc as fa                     # noqa: E402

T310.UM = R + "s681/_um_daily.jsonl"
T310.STYLE = R + "t156/_style.json"

OUT_JSON = os.path.join(HERE, "t364_results.json")
OUT_MD = os.path.join(HERE, "T-364_cross_asset_trend.md")
CACHE_CSV = R + "t364_ohlcv_cache.csv"
CACHE_META = R + "t364_ohlcv_cache_meta.json"

# ── S-841 写死的量(不调参)────────────────────────────────────────────────────
SYMS = ["SPY", "EEM", "GLD", "TLT", "USO"]
YF_START = pd.Timestamp("2015-07-13")      # yfinance(未复权)段起点
YF_END = pd.Timestamp("2022-08-30")        # yfinance 段终点
EOD_START = pd.Timestamp("2022-08-31")     # eodhd(复权)段起点
OVERLAP = (pd.Timestamp("2022-09-01"), pd.Timestamp("2026-06-30"))   # 量「复权 − 未复权」年化差的重叠段
LOOKBACK = 252                             # 信号:过去 252 个交易日收益的符号
VOL_WIN = 60                               # 仓位:过去 60 个交易日的年化波动
TARGET_VOL = 0.10                          # 目标年化波动
N_ASSETS = 5                               # 仓位 = 符号 × (10% ÷ vol) ÷ 5
GROSS_CAP = 2.0                            # 袖子毛敞口上限
COST_BP = 5.0                              # 每单位换手 5 bp
TRADING_DAYS = 252                         # 年化用的每年交易日数

# ── S-835 准入标准(统计量写死)────────────────────────────────────────────────
START = pd.Timestamp("2021-10-11")         # 账户起点(t342_daily.csv / S-834 口径)
TARGET_RC = 0.10                           # 族自己的风险贡献占账户 10%
N_NULL = 200                               # (ii) 零分布:袖子日收益循环平移 200 次
SEED_NULL = 20261113                       # 种子写死
N_RANDSIGN = 200                            # 零信号对照:随机 ±1 符号 200 次
SEED_RANDSIGN = 20261113
W_FULL = (pd.Timestamp("2021-10-12"), pd.Timestamp("2026-10-30"))
W1 = (pd.Timestamp("2021-10-12"), pd.Timestamp("2024-03-31"))
W2 = (pd.Timestamp("2024-04-01"), pd.Timestamp("2026-10-30"))
FEB = ("2023-02-08", "2023-03-08")         # 账户最差 20 日(卡里点名的那段)
SRC = ["crypto", "equity", "gold", "rv2", "cash"]
RHO_LIMIT = 0.30                           # (i) 单侧 ρ < 0.30


def log(msg: str) -> None:
    print(msg, flush=True)


def _mod(name: str, path: str):
    sp = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


E1 = _mod("t352_engine", os.path.join(HERE, "t352_engine.py"))


# ── 读库(只读)───────────────────────────────────────────────────────────────
def _postgrest(path: str, params: dict):
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "apikey": os.environ["SUPABASE_KEY"],
        "Authorization": "Bearer " + os.environ["SUPABASE_KEY"],
    })
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode()), r.headers.get("Content-Range", "")


def fetch_ohlcv(force: bool = False) -> pd.DataFrame:
    """取 SPY/EEM/GLD/TLT/USO × {eodhd, yfinance} 的日线收盘。

    每页 1000 行(limit=10000 会被静默截断);翻页带 order=trade_date.asc;
    总行数用 Content-Range 的 /total 核。
    """
    if (not force) and os.path.exists(CACHE_CSV) and os.path.exists(CACHE_META):
        meta = json.load(open(CACHE_META))
        df = pd.read_csv(CACHE_CSV, parse_dates=["trade_date"])
        if meta.get("rows") == int(len(df)):
            log(f"[fetch] 用缓存 {CACHE_CSV}({len(df)} 行)")
            return df
    rows, meta = [], {}
    for s in SYMS:
        for src in ("eodhd", "yfinance"):
            off, total = 0, None
            while True:
                part, cr = _postgrest("ohlcv_daily", {
                    "select": "symbol,source,trade_date,close,asset_class",
                    "symbol": f"eq.{s}", "source": f"eq.{src}",
                    "order": "trade_date.asc", "limit": 1000, "offset": off})
                if cr and "/" in cr:
                    try:
                        total = int(cr.split("/")[-1])
                    except ValueError:
                        total = None
                for r in part:
                    r["symbol"], r["source"] = s, src
                    rows.append(r)
                off += len(part)
                if len(part) < 1000:
                    break
            got = sum(1 for r in rows if r["symbol"] == s and r["source"] == src)
            meta[f"{s}|{src}"] = {"rows": got, "total": total}
            log(f"[fetch] {s:4s} {src:10s} rows={got} total={total}")
            if total is not None and got != total:
                raise RuntimeError(f"{s}/{src} 抓取行数 {got} != Content-Range 总数 {total}")
    df = pd.DataFrame(rows)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df.to_csv(CACHE_CSV, index=False)
    meta["rows"] = int(len(df))
    json.dump(meta, open(CACHE_META, "w"), indent=1)
    return df


# ── 价格序列:分段拼接(收益不跨拼接点取比)────────────────────────────────────
class Sym:
    """一个标的的拼接序列。

    * pnl 段:≤2022-08-30 用 yfinance(未复权);≥2022-08-31 用 eodhd(复权)。
      段内取比算日收益;拼接点两侧不取比(eodhd 首日无同源前值 ⇒ 该日收益记 0)。
    * carry Δ:重叠段(2022-09 → 2026-06)的「复权 − 未复权」年化差。
      拼接点之前空头一侧每天扣 Δ/252(S-841:两边都往不利的方向取),多头一侧不加。
    * 信号用各自来源内部的 252 日收益(lookback 跨拼接点的那几个月改用能整段覆盖的来源)。
    """

    def __init__(self, s: str, df: pd.DataFrame, prefer_eodhd: bool = False):
        self.name = s
        self.prefer_eodhd = prefer_eodhd
        sub = df[df["symbol"] == s]
        self.E = (sub[sub["source"] == "eodhd"].set_index("trade_date")["close"]
                  .dropna().astype(float).sort_index())
        self.Y = (sub[sub["source"] == "yfinance"].set_index("trade_date")["close"]
                  .dropna().astype(float).sort_index())
        # 重叠段年化差
        self.carry = self._overlap_carry()
        # 拼接后的日收益(段内取比)
        self.dates = sorted(set(self.Y.index) | set(self.E.index))
        px, seg = {}, {}
        for d in self.dates:
            if prefer_eodhd and d in self.E.index:
                px[d], seg[d] = float(self.E.loc[d]), "eodhd"     # 稳健性:SPY 整段用复权源
            elif d <= YF_END and d in self.Y.index:
                px[d], seg[d] = float(self.Y.loc[d]), "yf"
            elif d >= EOD_START and d in self.E.index:
                px[d], seg[d] = float(self.E.loc[d]), "eodhd"
        self.px = pd.Series(px).sort_index()
        self.seg = pd.Series(seg).sort_index()
        r = self.px / self.px.shift(1) - 1.0
        bad = (self.seg != self.seg.shift(1)).fillna(False)
        r[bad] = 0.0                      # 拼接点不取比
        r.iloc[0] = 0.0
        self.r_pnl = r
        # 空头一侧:拼接点之前每天扣 Δ/252
        pre = self.seg == "yf"
        self.r_short = -self.r_pnl - np.where(pre, self.carry / TRADING_DAYS, 0.0)
        # 源内部的日收益(信号与波动都用它;预计算,免得每次重算 pct_change)
        self.E_ret = self.E.pct_change()
        self.Y_ret = self.Y.pct_change()
        self._sig_cache = None
        self._sig_key = None

    def _overlap_carry(self) -> float:
        """重叠段(2022-09 → 2026-06)上「复权 − 未复权」的年化差。

        **必须在两份来源的共同日期上量**(各自的首末日不同 —— 例如 yfinance 只到 2026-06-18,
        eodhd 到 2026-06-30;GLD/USO 在那 8 个交易日里走了 ±7%,用各自端点量会把 Δ 算成 ±2%)。
        """
        a, b = OVERLAP
        common = self.E.index.intersection(self.Y.index)
        common = common[(common >= a) & (common <= b)]
        if len(common) < 60:
            return float("nan")
        e = self.E.reindex(common)
        y = self.Y.reindex(common)
        re = e.pct_change().dropna()
        ry = y.pct_change().dropna()
        yrs = (common[-1] - common[0]).days / 365.25
        if yrs <= 0:
            return float("nan")
        ce = float((1 + re).prod() ** (1 / yrs) - 1)
        cy = float((1 + ry).prod() ** (1 / yrs) - 1)
        self.carry_detail = {"n_common": int(len(common)), "start": str(common[0].date()),
                              "end": str(common[-1].date()), "cagr_eodhd": ce, "cagr_yfinance": cy,
                              "ratio_first": float(e.iloc[0] / y.iloc[0]),
                              "ratio_last": float(e.iloc[-1] / y.iloc[-1])}
        return ce - cy

    def signal_at(self, d: pd.Timestamp):
        """月末 d 的信号:过去 252 个交易日收益的符号 + 60 日年化波动。
        整段 lookback 只能用同一个来源(不跨拼接点取比):优先复权源,否则未复权源。"""
        for px, ret, tag in ((self.E, self.E_ret, "eodhd"), (self.Y, self.Y_ret, "yfinance")):
            if d not in px.index:
                continue
            pos = px.index.get_loc(d)
            if pos - LOOKBACK < 0:
                continue
            start = px.index[pos - LOOKBACK]
            trail = float(px.loc[d] / px.loc[start] - 1.0)
            rr = ret.dropna().loc[:d]
            if len(rr) < 20:
                continue
            vol = float(rr.iloc[-VOL_WIN:].std(ddof=1) * np.sqrt(TRADING_DAYS))
            if not np.isfinite(vol) or vol <= 0:
                continue
            return {"trail": trail, "vol": vol, "sign": 1.0 if trail > 0 else -1.0, "src": tag}
        return None

    def signals(self, me) -> dict:
        """月末 → 信号(缓存:随机符号对照要跑 200 次,信号与波动不必重算)。"""
        if self._sig_key == len(me) and self._sig_cache is not None:
            return self._sig_cache
        out = {}
        for d in me:
            info = self.signal_at(d)
            if info is not None:
                out[d] = info
        self._sig_key = len(me)
        self._sig_cache = out
        return out


# ── 袖套:Moskowitz–Ooi–Pedersen 2012 的时序动量(S-841 写死,不调参)──────────
def build_sleeve(syms: dict, rand_sign: bool = False, long_only: bool = False,
                 seed: int = 0, drop: str = None) -> dict:
    """月末最后一个交易日调仓:信号 = 过去 252 日收益的符号;仓位 = 符号 × (10% ÷ 60 日年化波动) ÷ 5;
    毛敞口上限 2.0;持有到下个月末;每单位换手 5 bp。

    rand_sign=True 时把每月的符号换成独立 ±1 随机数(零信号对照,其余不变)。
    """
    names = [s for s in SYMS if s != drop]
    cal = None
    for s in names:
        d = syms[s].dates
        cal = d if cal is None else sorted(set(cal) & set(d))
    cal = pd.DatetimeIndex(sorted(cal))
    per = cal.to_period("M")
    me = pd.DatetimeIndex(pd.Series(cal).groupby(per).max().values)   # 每月最后一个交易日
    me_set = set(me)

    rng = np.random.default_rng(seed)
    sig_cache = {s: {} for s in names}
    for s in names:
        cached = syms[s].signals(me)
        for d, info in cached.items():
            sg = info["sign"]
            if rand_sign:
                sg = 1.0 if rng.integers(0, 2) == 0 else -1.0
            sig_cache[s][d] = (sg, info["vol"])

    pos_me = pd.DataFrame(0.0, index=me, columns=names)
    for d in me:
        raw = {}
        for s in names:
            if d not in sig_cache[s]:
                continue
            sg, vol = sig_cache[s][d]
            if long_only and sg <= 0:
                continue                      # 只多版:信号 ≤ 0 那一份空着
            raw[s] = sg * (TARGET_VOL / vol) / N_ASSETS
        gross = sum(abs(v) for v in raw.values())
        scale = GROSS_CAP / gross if gross > GROSS_CAP else 1.0
        for s, v in raw.items():
            pos_me.loc[d, s] = v * scale

    # 每日持仓:上一次(严格早于当天)的月末仓位
    pos_daily = pd.DataFrame(0.0, index=cal, columns=names)
    last = None
    for d in cal:
        if last is not None:
            pos_daily.loc[d] = pos_me.loc[last]
        if d in me_set:
            last = d

    # 每日 P&L:多头 p×r;空头 −|p|×r 再扣掉拼接点之前的纯供资成本(|p|×Δ/252)
    pnl = pd.Series(0.0, index=cal)
    contrib = {}
    for s in names:
        p = pos_daily[s]
        r = syms[s].r_pnl.reindex(cal).fillna(0.0)
        pre = (syms[s].seg.reindex(cal) == "yf").astype(float)
        carry_d = syms[s].carry / TRADING_DAYS
        leg = p * r - np.abs(np.minimum(p, 0.0)) * carry_d * pre
        pnl = pnl + leg
        contrib[s] = float(leg.sum())

    # 换手成本:每个调仓(月末)后的第一个交易日扣 5bp × 换手
    cost = pd.Series(0.0, index=cal)
    prev_pos = pd.Series(0.0, index=names)
    for i, d in enumerate(cal):
        if d not in me_set:
            continue
        new = pos_me.loc[d]
        turn = float((new - prev_pos).abs().sum())
        j = i + 1
        if j < len(cal):
            cost.iloc[j] = COST_BP / 1e4 * turn
        prev_pos = new

    ret = pnl - cost
    nav = (1 + ret).cumprod()
    nav.index.name = "d"
    return {"cal": cal, "ret": ret, "nav": nav, "pos": pos_me, "cost": cost,
            "contrib": contrib, "long_only": long_only, "drop": drop,
            "gross": pos_me.abs().sum(axis=1), "month_ends": me}


# ── 账户(S-834 口径;照 T-363 的 build_account)───────────────────────────────
def build_account() -> dict:
    d = pd.read_csv(os.path.join(HERE, "t342_daily.csv"), parse_dates=["date"]).set_index("date")
    legs_px = {"crypto": d.crypto_leg_nav_x1v, "equity": d.equity_close_acwi, "gold": d.gold_close_xauusd}
    cal = pd.date_range(d.index[0], d.index[-1], freq="D")
    cash_rate = d.cash_daily_rate.reindex(cal).ffill().fillna(0.0)
    raw, _ = T310.load_tickets()
    bars = T310.load_bars({t["symbol"] for t in raw})
    exits, _ = T310.classify_exits(raw, bars)
    TK = T310.to_engine_tickets(raw, exits)
    gate_d, _, _ = T310.load_gate()
    res = E1.simulate(TK, bars, gate_d, 0.80, equity0=630.0, risk_frac=0.0075, cap_n=10, fix=True)
    rv2 = pd.Series({pd.Timestamp(r[0]): float(r[1]) for r in res["curve"]}).sort_index().pct_change().dropna()
    df = pd.concat(legs_px, axis=1).dropna().sort_index()
    rets = df.pct_change()
    idx = [x for x in df.index if x >= START]
    tgt = pd.Series(fa.rb_weights(rets.loc[:idx[0]].iloc[1:])).reindex(list(fa.LEGS)).fillna(0.0)
    hold = tgt.copy()
    rows, nav = [], 1.0
    between = fa._between
    for i, day in enumerate(idx[1:], start=1):
        row = rets.loc[day, list(fa.LEGS)]
        prev = idx[i - 1]
        c = {k: float(hold[k] * row[k]) for k in fa.LEGS}
        cr = between(cash_rate, prev, day)
        c["cash"] = (1.0 - float(hold.sum())) * cr
        c["rv2"] = between(rv2, prev, day)
        g = sum(c.values())
        nav *= 1 + g
        hold = hold * (1 + row) / (1 + g)
        if i % 21 == 0:
            new = pd.Series(fa.rb_weights(rets.loc[:day].iloc[1:])).reindex(list(fa.LEGS)).fillna(0.0)
            cost = float((hold - new).abs().sum()) * 20 / 1e4
            nav *= 1 - cost
            c["cost"] = -cost
            hold = new.copy()
        rows.append({"d": day, **c, "cash_ret": cr, "acct": g + c.get("cost", 0.0), "nav": nav})
    C = pd.DataFrame(rows).set_index("d").fillna(0.0)
    core = d.core_nav_1_cap_pit24.reindex(C.index).pct_change().fillna(0.0)
    return {"C": C, "idx": idx, "core": core, "rv2": rv2, "cal": cal, "core_daily": d}


def account_stats(C: pd.DataFrame) -> dict:
    Cm = pd.DataFrame({k: C[k].resample("M").sum() for k in SRC})
    Am = (1 + C["acct"]).resample("M").prod() - 1
    rc = {k: float(np.cov(Cm[k], Am)[0, 1] / Am.var()) for k in SRC}
    tot = sum(rc.values())
    return {
        "cagr": cagr_from_daily(C["acct"]),
        "months": int(len(Am)),
        "risk_contribution": rc,
        "rv2_risk_share": rc["rv2"],
        "eff_sources": float(np.exp(-sum(x * np.log(x) for x in
                                          (np.clip(list(rc.values()), 1e-9, None) / max(tot, 1e-12))))),
        "worst_month": [str(Am.idxmin().date()), float(Am.min())],
        "Am": Am,
    }


# ── 小工具 ──────────────────────────────────────────────────────────────────
class MonthGrid:
    def __init__(self, idx: pd.DatetimeIndex):
        per = idx.to_period("M").to_numpy()
        change = np.where(per[1:] != per[:-1])[0] + 1
        self.bounds = np.concatenate([[0], change, [len(per)]])
        self.labels = [str(p) for p in pd.PeriodIndex(per, freq="M").unique()]

    def comp(self, r: np.ndarray) -> np.ndarray:
        return np.expm1(np.add.reduceat(np.log1p(r), self.bounds[:-1]))

    def summ(self, r: np.ndarray) -> np.ndarray:
        return np.add.reduceat(r, self.bounds[:-1])


def cagr_from_monthly(m: np.ndarray, years: float) -> float:
    if years <= 0 or not len(m):
        return float("nan")
    return float(np.prod(1.0 + m) ** (1.0 / years) - 1.0)


def cagr_from_daily(r: pd.Series) -> float:
    if len(r) < 2:
        return float("nan")
    yrs = (r.index[-1] - r.index[0]).days / 365.25
    if yrs <= 0:
        return float("nan")
    return float((1.0 + r).prod() ** (1.0 / yrs) - 1.0)


def max_dd(nav: pd.Series) -> float:
    return float((nav / nav.cummax() - 1.0).min())


def nav_to_account_ret(nav: pd.Series, acct_idx: list) -> pd.Series:
    """袖套净值 → 账户共同日上的日收益(两共同日之间按 flex_alloc._between 复利)。"""
    cal = pd.date_range(nav.index[0], nav.index[-1], freq="D")
    r = nav.reindex(cal).ffill().pct_change().fillna(0.0)
    out = [fa._between(r, acct_idx[i - 1], acct_idx[i]) for i in range(1, len(acct_idx))]
    return pd.Series(out, index=acct_idx[1:])


def nav_to_account_ret_fast(nav: pd.Series, acct_idx: list) -> pd.Series:
    """与 nav_to_account_ret 等价的快路径(自检 1b 逐点核过,差 < 1e-12)。

    随机符号对照要跑 200 次,每次都过一遍 fa._between(1800 次)太慢;这里用净值比。
    """
    cal = pd.date_range(nav.index[0], nav.index[-1], freq="D")
    nav_cal = nav.reindex(cal).ffill()
    a = pd.DatetimeIndex(acct_idx)
    v = nav_cal.reindex(a)
    out = v.iloc[1:].to_numpy() / v.iloc[:-1].to_numpy() - 1.0
    return pd.Series(out, index=a[1:])


def synth(rb_a, rf_a, rcash_a, w):
    """S-835 更正三的叠加口径:A_aug = A_base + w·r − w·r_cash。"""
    return rb_a + w * rf_a - w * rcash_a


# ── 一族一窗的 (i)–(iv) 的数 ───────────────────────────────────────────────
def window_metrics(acct: dict, fam_r: pd.Series, w: float, a, b, active_start=None) -> dict:
    C = acct["C"]
    idx = C.index
    m = (idx >= a) & (idx <= b)
    rb = C["acct"][m]
    rf = fam_r.reindex(idx)[m].fillna(0.0)
    rcash = C["cash_ret"].reindex(idx)[m].fillna(0.0)
    if len(rb) < 60:
        return {"ok": False, "n_days": int(len(rb))}
    g = MonthGrid(rb.index)
    rb_a, rf_a, rcash_a = rb.to_numpy(), rf.to_numpy(), rcash.to_numpy()
    ra = synth(rb_a, rf_a, rcash_a, w)
    A = g.comp(ra)
    A_base = g.comp(rb_a)
    Fw = g.summ(w * rf_a)
    Cm_base = {k: g.summ(C[k][m].to_numpy()) for k in SRC}
    Cm_base["cash"] = g.summ(C["cash"][m].to_numpy() - w * rcash_a)
    Rv2m = Cm_base["rv2"]
    labels = g.labels
    thr = float(np.quantile(A_base, 0.2)) if len(A_base) >= 5 else float("nan")
    st = A_base <= thr                      # 压力月:按 A_base 在本窗内定(S-835 更正二)

    def corr(x, y, sel=None):
        if sel is not None:
            x, y = x[sel], y[sel]
        if len(x) < 4 or np.std(x) == 0 or np.std(y) == 0:
            return float("nan")
        return float(np.corrcoef(x, y)[0, 1])

    contrib = dict(Cm_base)
    contrib["fam"] = Fw
    rc = {k: float(np.cov(v, A)[0, 1] / A.var()) for k, v in contrib.items()}
    tot = sum(rc.values())
    eff = float(np.exp(-sum((x / tot) * np.log(x / tot) for x in rc.values() if x > 0)))
    rc_base = {k: float(np.cov(g.summ(C[k][m].to_numpy()), A_base)[0, 1] / A_base.var()) for k in SRC}
    tb = sum(rc_base.values())
    eff_base = float(np.exp(-sum((x / tb) * np.log(x / tb) for x in rc_base.values() if x > 0)))

    def worst20(x):
        s = pd.Series(x, index=rb.index)
        return float(((1 + s).rolling(20).apply(np.prod) - 1).min())

    w20_base, w20_aug = worst20(rb_a), worst20(ra)
    r_no_cash = rb_a - w * rcash_a
    w20_no_cash = worst20(r_no_cash)
    cagr_no_cash = float(cagr_from_daily(pd.Series(r_no_cash, index=rb.index)))

    # (ii) 零分布:袖子日收益整体循环平移
    i0 = 0
    if active_start is not None:
        i0 = max(0, min(int(np.searchsorted(rb.index.to_numpy(), np.datetime64(active_start), side="left")),
                        len(rf_a) - 2))
    seg = rf_a[i0:]
    years = (rb.index[-1] - rb.index[0]).days / 365.25
    base_cagr = cagr_from_monthly(A_base, years)
    rng = np.random.default_rng(SEED_NULL)
    nulls = []
    for _ in range(N_NULL):
        sh = ap.circular_shift(seg, rng, block=1)
        rs = rf_a.copy()
        rs[i0:] = sh
        nulls.append(cagr_from_monthly(g.comp(synth(rb_a, rs, rcash_a, w)), years))
    actual = cagr_from_monthly(A, years)
    p_up = ap.p_upper(actual - base_cagr, [x - base_cagr for x in nulls]) if nulls else None

    c1 = [corr(Fw, A_base), corr(Fw, A_base, st), corr(Fw, Rv2m), corr(Fw, Rv2m, st)]
    c1_ok = all((v is not None) and (not np.isnan(v)) and v < RHO_LIMIT for v in c1)
    c2_ok = bool(Fw.mean() > 0) and (p_up is not None) and (p_up < 0.10)
    c3a = bool(w20_aug >= w20_base - 1e-12)
    c3b = bool(eff > eff_base)
    return {
        "ok": True, "n_days": int(len(rb)), "start": str(rb.index[0].date()), "end": str(rb.index[-1].date()),
        "months": int(len(A)), "stress_months": int(st.sum()), "stress_threshold": thr,
        "w": float(w),
        "cagr_base": float(base_cagr), "cagr_aug": float(actual),
        "dcagr_pp": float(100 * (actual - base_cagr)),
        "cagr_no_cash": cagr_no_cash, "dcagr_vs_no_cash_pp": float(100 * (actual - cagr_no_cash)),
        "worst20_no_cash": float(w20_no_cash),
        "p_upper": float(p_up) if p_up is not None else None,
        "null_mean": float(np.mean(nulls)), "null_sd": float(np.std(nulls)),
        "corr_acct_base_full": c1[0], "corr_acct_base_stress": c1[1],
        "corr_rv2_full": c1[2], "corr_rv2_stress": c1[3],
        "corr_acct_aug_full": corr(Fw, A), "corr_acct_aug_stress": corr(Fw, A, st),
        "mean_monthly_contrib_pct": float(Fw.mean() * 100),
        "total_contrib_pct": float(Fw.sum() * 100),
        "rc": {k: round(v, 4) for k, v in rc.items()}, "rc_fam": float(rc["fam"]),
        "eff_sources": eff, "eff_sources_base": eff_base,
        "worst20_base": w20_base, "worst20_aug": w20_aug,
        "worst20_delta_pp": float(100 * (w20_aug - w20_base)),
        "fam_vol_ann": float(np.std(rf_a) * np.sqrt(365)), "fam_cagr": cagr_from_daily(pd.Series(rf_a, index=rb.index)),
        "i_ok": bool(c1_ok), "ii_ok": bool(c2_ok), "iii_ok": bool(c3a and c3b),
        "i_corr_values": [float(v) for v in c1],
        "pattern": [bool(c1_ok), bool(c2_ok), bool(c3a and c3b)],
    }


def size_family(acct: dict, fam_r: pd.Series) -> dict:
    """二分:调到族自己的边际风险贡献 = 叠加后账户月度方差的 10%(S-835 更正三)。资金倍数上限 w = 1。"""
    C = acct["C"]
    rb = C["acct"]
    rf = fam_r.reindex(C.index).fillna(0.0)
    rcash = C["cash_ret"].reindex(C.index).fillna(0.0)
    g = MonthGrid(rb.index)
    rb_a, rf_a, rcash_a = rb.to_numpy(), rf.to_numpy(), rcash.to_numpy()

    def rc_at(w):
        ra = synth(rb_a, rf_a, rcash_a, w)
        A = g.comp(ra)
        Fw = g.summ(w * rf_a)
        if A.var() == 0:
            return float("nan")
        return float(np.cov(Fw, A)[0, 1] / A.var())

    grid = np.linspace(0.0, 1.0, 201)
    vals = [rc_at(x) for x in grid]
    ok = [(x, v) for x, v in zip(grid, vals) if not np.isnan(v)]
    cross = None
    for i in range(len(ok) - 1):
        if ok[i][1] <= TARGET_RC <= ok[i + 1][1]:
            cross = (ok[i][0], ok[i + 1][0])
            break
    if cross is None:
        return {"w": None, "w_used": 1.0, "feasible": False, "reachable": False,
                "rc_at_w1": rc_at(1.0), "rc_max": ok[-1][1],
                "note": "尺寸不可行:资金倍数需 > 1"}
    lo, hi = cross
    for _ in range(60):
        mid = (lo + hi) / 2
        if rc_at(mid) < TARGET_RC:
            lo = mid
        else:
            hi = mid
    w = (lo + hi) / 2
    return {"w": float(w), "w_used": float(w), "feasible": True, "reachable": True,
            "rc_at_w": rc_at(w), "rc_at_w1": rc_at(1.0), "rc_max": ok[-1][1]}


# ── 主流程 ──────────────────────────────────────────────────────────────────
def main() -> None:
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("--fetch-only", action="store_true")
    ap_.add_argument("--refetch", action="store_true")
    a = ap_.parse_args()

    log("=== ① 数据(只读 ohlcv_daily) ===")
    df = fetch_ohlcv(force=a.refetch)
    if a.fetch_only:
        for s in SYMS:
            for src in ("eodhd", "yfinance"):
                sub = df[(df.symbol == s) & (df.source == src)].sort_values("trade_date")
                if len(sub):
                    log(f"  {s:4s} {src:10s} n={len(sub):5d}  {sub.trade_date.min().date()} → {sub.trade_date.max().date()}"
                        f"  close {sub.close.iloc[0]} → {sub.close.iloc[-1]}")
        return

    syms = {s: Sym(s, df) for s in SYMS}
    log("  重叠段(2022-09 → 2026-06)的「复权 − 未复权」年化差:")
    carry_info = {}
    for s in SYMS:
        c = syms[s].carry
        carry_info[s] = float(c)
        log(f"    {s:4s} Δ = {c*100:+.3f} pp/年")
    data_info = {}
    for s in SYMS:
        data_info[s] = {
            "eodhd": [str(syms[s].E.index[0].date()), str(syms[s].E.index[-1].date()), int(len(syms[s].E))],
            "yfinance": [str(syms[s].Y.index[0].date()), str(syms[s].Y.index[-1].date()), int(len(syms[s].Y))],
            "carry_annualized": float(syms[s].carry),
        }

    log("=== ② 袖套(S-841 规则) ===")
    sl = build_sleeve(syms)
    cal = sl["cal"]
    log(f"  袖套日历 {cal[0].date()} → {cal[-1].date()} · {len(cal)} 个交易日 · "
        f"毛敞口中位 {sl['gross'].median():.3f} / 峰值 {sl['gross'].max():.3f}")
    nav = sl["nav"]
    PRE_A, PRE_B = pd.Timestamp("2016-08-01"), pd.Timestamp("2021-10-10")
    pre = nav[(nav.index >= PRE_A) & (nav.index <= PRE_B)]
    log(f"  袖套自己 {pre.index[0].date()} → {pre.index[-1].date()}:年化 {cagr_from_daily(pre.pct_change().dropna()):+.2%}"
        f" · 最大回撤 {max_dd(pre):+.2%}")

    log("=== ③ 账户(S-834 口径) ===")
    acct = build_account()
    C = acct["C"]
    st = account_stats(C)
    log(f"  账户 {C.index[0].date()} → {C.index[-1].date()} · {st['months']} 个月 · 年化 {st['cagr']:+.2%}"
        f" · R-v2 风险占比 {st['rv2_risk_share']:.3f} · 有效来源 {st['eff_sources']:.2f}")

    acct_idx = acct["idx"]
    fam_r = nav_to_account_ret(nav, acct_idx)

    # 自检 1:账户日连乘 = 袖子净值首尾比(差 < 1e-9)
    nav_cal = nav.reindex(pd.date_range(nav.index[0], nav.index[-1], freq="D")).ffill()
    a0, a1 = pd.Timestamp(acct_idx[0]), pd.Timestamp(acct_idx[-1])
    prod_mapped = float((1 + fam_r.reindex(C.index).fillna(0.0)).prod())
    ratio = float(nav_cal.loc[a1] / nav_cal.loc[a0])
    selfcheck_map = {"prod_mapped": prod_mapped, "nav_ratio": ratio, "diff": abs(prod_mapped - ratio)}
    # 顺带核 _between 与净值比的等价
    ref = nav_to_account_ret(nav, acct_idx)
    eq = float(np.nanmax(np.abs((ref - fam_r).abs()))) if len(ref) else 0.0
    log(f"  自检 1:连乘 {prod_mapped:.12f} vs 净值比 {ratio:.12f} · 差 {selfcheck_map['diff']:.3e}")
    log(f"  自检 1b:_between 与净值比逐点最大差 {eq:.3e}")

    # 自检 2:w = 0 ⇒ A_aug 逐日等于 A_base
    w0 = synth(C["acct"].to_numpy(), fam_r.reindex(C.index).fillna(0.0).to_numpy(),
               C["cash_ret"].to_numpy(), 0.0)
    selfcheck_w0 = float(np.max(np.abs(w0 - C["acct"].to_numpy())))

    # 自检 3:恒现金族(w 任意)⇒ A_aug 逐日等于 A_base
    cashfam = C["cash_ret"].reindex(C.index).fillna(0.0)
    wc = 0.5
    w3 = synth(C["acct"].to_numpy(), cashfam.to_numpy(), C["cash_ret"].to_numpy(), wc)
    selfcheck_cashfam = float(np.max(np.abs(w3 - C["acct"].to_numpy())))
    log(f"  自检 2:w=0 逐日最大差 {selfcheck_w0:.3e} · 自检 3:恒现金族(w={wc})逐日最大差 {selfcheck_cashfam:.3e}")

    log("=== ④ 尺寸(w 二分到风险贡献 10%) ===")
    sizing = size_family(acct, fam_r)
    w = sizing["w_used"] if sizing["w"] is None else sizing["w"]
    log(f"  w = {w:.4f}(可达={sizing['reachable']};w=1 处的风险贡献 {sizing['rc_at_w1']:.4f})")

    log("=== ⑤ (i)–(iv) 分窗 ===")
    windows = OrderedDict()
    for name, (a, b) in (("FULL", W_FULL), ("W1_2021-10-12_2024-03-31", W1), ("W2_2024-04-01_2026-10-30", W2)):
        m = window_metrics(acct, fam_r, w, a, b)
        windows[name] = m
        if m.get("ok"):
            log(f"  {name}: 年化 {m['cagr_base']*100:+.2f}% → {m['cagr_aug']*100:+.2f}% ({m['dcagr_pp']:+.2f}pp)"
                f" · p_upper {m['p_upper']} · ρ(A_base) {m['corr_acct_base_full']:+.3f}/{m['corr_acct_base_stress']:+.3f}"
                f" · ρ(R-v2) {m['corr_rv2_full']:+.3f}/{m['corr_rv2_stress']:+.3f}"
                f" · 最差20日 {m['worst20_base']*100:+.1f}% → {m['worst20_aug']*100:+.1f}%"
                f" · 有效来源 {m['eff_sources_base']:.2f}→{m['eff_sources']:.2f} · 判 {m['pattern']}")
        else:
            log(f"  {name}: 不可用({m})")

    # (iv) 两半年窗的年化贡献
    iv_ok = bool(windows["W1_2021-10-12_2024-03-31"].get("dcagr_pp", -1) > 0 and
                 windows["W2_2024-04-01_2026-10-30"].get("dcagr_pp", -1) > 0)

    log("=== ⑥ 零信号对照(随机 ±1 符号,200 次) ===")
    rng = np.random.default_rng(SEED_RANDSIGN)
    real_cagr = windows["FULL"]["cagr_aug"]
    base_cagr = windows["FULL"]["cagr_base"]
    null_cagr = []
    m = (C.index >= W_FULL[0]) & (C.index <= W_FULL[1])
    rb_a = C["acct"][m].to_numpy()
    rc_a = C["cash_ret"][m].to_numpy()
    g_full = MonthGrid(C.index[m])
    yrs = (C.index[m][-1] - C.index[m][0]).days / 365.25
    for i in range(N_RANDSIGN):
        s2 = build_sleeve(syms, rand_sign=True, seed=int(rng.integers(0, 2**31 - 1)))
        fr = nav_to_account_ret_fast(s2["nav"], acct_idx)
        rf_a = fr.reindex(C.index)[m].fillna(0.0).to_numpy()
        null_cagr.append(cagr_from_monthly(g_full.comp(rb_a + w * rf_a - w * rc_a), yrs))
        if (i + 1) % 50 == 0:
            log(f"    随机符号 {i+1}/{N_RANDSIGN} …")
    null_cagr = [x for x in null_cagr if np.isfinite(x)]
    pct_real = ap.percentile_of(real_cagr, null_cagr)
    p_up_rand = ap.p_upper(real_cagr, null_cagr)
    log(f"  随机符号 200 次:年化中位 {np.median(null_cagr)*100:+.2f}% · 真信号 {real_cagr*100:+.2f}%"
        f" · 落在第 {pct_real*100:.1f} 分位 · p_upper {p_up_rand:.4f}")

    log("=== ⑦ 只报不判 ===")
    # 袖子自己:账户窗口之前 / 逐年
    sleeve_pre = nav[(nav.index >= PRE_A) & (nav.index <= PRE_B)]
    yearly = nav.pct_change().dropna().resample("YE").apply(lambda x: (1 + x).prod() - 1)
    yearly_pre = sleeve_pre.pct_change().dropna().resample("YE").apply(lambda x: (1 + x).prod() - 1)
    # 只多版
    sl_lo = build_sleeve(syms, long_only=True)
    nav_lo = sl_lo["nav"]
    # 账户最差 20 日 与 R-v2 最差 12 个月
    feb = nav.reindex(pd.date_range(pd.Timestamp(FEB[0]), pd.Timestamp(FEB[1]), freq="D")).ffill()
    feb_ret = float(feb.iloc[-1] / feb.iloc[0] - 1)
    rv2_worst12 = st["Am"].nsmallest(12).index
    rv2_win = nav.reindex(pd.date_range(rv2_worst12.min(), rv2_worst12.max(), freq="D")).ffill()
    rv2_ret = float(rv2_win.iloc[-1] / rv2_win.iloc[0] - 1)
    # 每个资产的贡献 & 去掉最大的那个
    contrib = {k: float(v) for k, v in sl["contrib"].items()}
    top = max(contrib, key=lambda k: contrib[k])
    sl_drop = build_sleeve(syms, drop=top)
    nav_drop = sl_drop["nav"]
    pre_drop = nav_drop[(nav_drop.index >= PRE_A) & (nav_drop.index <= PRE_B)]
    # 探索性:SPY 整段用复权源(eodhd 有 2015 起的复权价;登记的拼接法对 SPY 是"能拼但更粗")
    syms_e = {s: Sym(s, df, prefer_eodhd=True) for s in SYMS}
    sl_e = build_sleeve(syms_e)
    nav_e = sl_e["nav"]
    pre_e = nav_e[(nav_e.index >= PRE_A) & (nav_e.index <= PRE_B)]
    fam_r_e = nav_to_account_ret(nav_e, acct_idx)
    sz_e = size_family(acct, fam_r_e)
    w_e = sz_e["w_used"] if sz_e["w"] is None else sz_e["w"]
    win_e = window_metrics(acct, fam_r_e, w_e, W_FULL[0], W_FULL[1])
    exploratory = {
        "spy_full_eodhd": {
            "note": "SPY 整段用 eodhd 复权源(登记口径是 2022-08-31 拼接);其余四个不变",
            "sleeve_pre_cagr": cagr_from_daily(pre_e.pct_change().dropna()),
            "sleeve_pre_maxdd": max_dd(pre_e),
            "w": w_e, "full": win_e,
        },
    }
    report_only = {
        "sleeve_pre_account": {
            "start": str(sleeve_pre.index[0].date()), "end": str(sleeve_pre.index[-1].date()),
            "cagr": cagr_from_daily(sleeve_pre.pct_change().dropna()), "max_dd": max_dd(sleeve_pre),
        },
        "sleeve_yearly_pre_account": {str(k.date()): float(v) for k, v in yearly_pre.items()},
        "sleeve_yearly_full": {str(k.date()): float(v) for k, v in yearly.items()},
        "sleeve_full": {
            "cagr": cagr_from_daily(nav.pct_change().dropna()), "max_dd": max_dd(nav),
        },
        "long_only": {
            "pre_account_cagr": cagr_from_daily(sl_lo["nav"][(sl_lo["nav"].index >= PRE_A) &
                                                             (sl_lo["nav"].index <= PRE_B)]
                                                .pct_change().dropna()),
            "full_cagr": cagr_from_daily(nav_lo.pct_change().dropna()),
            "full_max_dd": max_dd(nav_lo),
            "yearly": {str(k.date()): float(v) for k, v in
                       nav_lo.pct_change().dropna().resample("YE").apply(lambda x: (1 + x).prod() - 1).items()},
        },
        "feb_window_sleeve_ret": feb_ret,
        "rv2_worst12_window": [str(rv2_worst12.min().date()), str(rv2_worst12.max().date())],
        "rv2_worst12_sleeve_ret": rv2_ret,
        "asset_contrib": contrib,
        "top_contributor": top,
        "drop_top": {
            "cagr_pre_account": cagr_from_daily(pre_drop.pct_change().dropna()),
            "max_dd_pre_account": max_dd(pre_drop),
            "cagr_full": cagr_from_daily(nav_drop.pct_change().dropna()),
        },
    }

    res = {
        "card": "T-364", "ledger": "S-841",
        "data": {"symbols": data_info, "carry_annualized": carry_info,
                 "overlap_window": [str(OVERLAP[0].date()), str(OVERLAP[1].date())],
                 "yf_segment": [str(YF_START.date()), str(YF_END.date())],
                 "eodhd_segment": [str(EOD_START.date()), None]},
        "sleeve": {
            "cal_start": str(cal[0].date()), "cal_end": str(cal[-1].date()), "n_days": int(len(cal)),
            "gross_median": float(sl["gross"].median()), "gross_max": float(sl["gross"].max()),
            "cost_total": float(sl["cost"].sum()),
        },
        "account": {"cagr": st["cagr"], "months": st["months"], "rv2_risk_share": st["rv2_risk_share"],
                    "eff_sources": st["eff_sources"], "risk_contribution": st["risk_contribution"],
                    "worst_month": st["worst_month"],
                    "expect_cagr_pct": 35.7, "expect_rv2": 0.742,
                    "cagr_ok": bool(abs(st["cagr"] - 0.357) < 0.005),
                    "rv2_ok": bool(abs(st["rv2_risk_share"] - 0.742) < 0.005)},
        "self_checks": {
            "map_prod_vs_nav_ratio": selfcheck_map,
            "between_vs_nav_ratio_maxdiff": eq,
            "w0_maxdiff": selfcheck_w0,
            "cash_family_maxdiff": selfcheck_cashfam,
        },
        "sizing": sizing,
        "windows": windows,
        "iv_ok": iv_ok,
        "zero_signal_control": {
            "n": len(null_cagr), "real_cagr": real_cagr, "base_cagr": base_cagr,
            "null_median": float(np.median(null_cagr)), "null_mean": float(np.mean(null_cagr)),
            "null_sd": float(np.std(null_cagr)), "null_q90": float(np.quantile(null_cagr, 0.90)),
            "percentile_of_real": pct_real, "p_upper": p_up_rand,
            "above_q90": bool(real_cagr > float(np.quantile(null_cagr, 0.90))),
        },
        "report_only": report_only,
        "exploratory": exploratory,
    }
    json.dump(res, open(OUT_JSON, "w"), indent=1, default=str)
    log(f"  结果落 {OUT_JSON}")
    write_md(res)


# ── 报告 ────────────────────────────────────────────────────────────────────
def _f(x, p=3, sign=False):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{x:+.{p}f}" if sign else f"{x:.{p}f}"


def write_md(res: dict) -> None:
    w = res["windows"]
    full = w["FULL"]
    L = []
    L.append("# T-364 · S-841 跨资产趋势袖套(SPY / EEM / GLD / TLT / USO,可多可空)的准入判定\n")
    L.append("预注册:台账 `## S-841 —` 一节(Seth,2026-11-13 06:04 UTC),写于算任何数之前。"
             "装配/叠加口径照 T-363 返工后的 `t363_admission_table.py`(`A_aug = A_base + w·r − w·r_cash`)。"
             "只读 ohlcv_daily,不入库,只算一次。\n")
    L.append("## 0 · 一句话结论\n")
    pat = full["pattern"]
    verdict = "四条全过" if (all(pat) and res["iv_ok"] and res["zero_signal_control"]["above_q90"]) else "不过"
    L.append(f"**{verdict}**。(i) ρ(A_base) {full['corr_acct_base_full']:+.3f}/压力月 {full['corr_acct_base_stress']:+.3f}"
             f"、ρ(R-v2) {full['corr_rv2_full']:+.3f}/{full['corr_rv2_stress']:+.3f};"
             f"(ii) 年化贡献 {full['dcagr_pp']:+.2f}pp(p_upper {full['p_upper']});"
             f"(iii) 最差 20 日 {full['worst20_base']*100:+.1f}% → {full['worst20_aug']*100:+.1f}%、"
             f"有效来源 {full['eff_sources_base']:.2f} → {full['eff_sources']:.2f};"
             f"(iv) 两半年窗贡献 {w['W1_2021-10-12_2024-03-31']['dcagr_pp']:+.2f}pp / "
             f"{w['W2_2024-04-01_2026-10-30']['dcagr_pp']:+.2f}pp;"
             f"零信号对照:真信号落在随机符号分布的第 {res['zero_signal_control']['percentile_of_real']*100:.1f} 分位。\n")
    L.append("## 1 · 数据与拼接\n")
    L.append("| 代码 | eodhd(复权)行数与区间 | yfinance(未复权)行数与区间 | 重叠段「复权 − 未复权」年化差 |")
    L.append("|---|---|---|---|")
    for s in SYMS:
        d = res["data"]["symbols"][s]
        L.append(f"| {s} | {d['eodhd'][2]} 行 {d['eodhd'][0]} → {d['eodhd'][1]} | "
                 f"{d['yfinance'][2]} 行 {d['yfinance'][0]} → {d['yfinance'][1]} | "
                 f"{d['carry_annualized']*100:+.3f} pp/年 |")
    L.append("")
    L.append(f"拼接点 2022-08-31:之前用 yfinance(未复权),之后用 eodhd(复权);**收益各自在来源内部算,不跨拼接点取比**。"
             f"拼接点之前空头一侧每天扣 {res['data']['carry_annualized']['SPY']*100:+.3f}% 级"
             f"(各代码自己的 Δ/252),多头一侧不加。重叠段量差用 2022-09 → 2026-06。\n")
    L.append("## 2 · 账户对账与三条自检\n")
    a = res["account"]
    L.append(f"- 账户(S-834 口径):{a['months']} 个月 · 年化 {a['cagr']*100:+.2f}%(期望 35.7%·{'对上' if a['cagr_ok'] else '**没对上**'})"
             f" · R-v2 风险占比 {a['rv2_risk_share']:.3f}(期望 0.742·{'对上' if a['rv2_ok'] else '**没对上**'})"
             f" · 有效来源 {a['eff_sources']:.2f}")
    sc = res["self_checks"]
    L.append(f"- 自检 1:账户日连乘 {sc['map_prod_vs_nav_ratio']['prod_mapped']:.12f} vs 袖子净值首尾比 "
             f"{sc['map_prod_vs_nav_ratio']['nav_ratio']:.12f} · 差 {sc['map_prod_vs_nav_ratio']['diff']:.3e}"
             f"(要求 < 1e-9)")
    L.append(f"- 自检 1b:`fa._between` 与净值比逐点最大差 {sc['between_vs_nav_ratio_maxdiff']:.3e}")
    L.append(f"- 自检 2:w = 0 逐日等于 A_base,最大差 {sc['w0_maxdiff']:.3e}")
    L.append(f"- 自检 3:恒现金族(w = 0.5)逐日等于 A_base,最大差 {sc['cash_family_maxdiff']:.3e}\n")
    L.append("## 3 · 尺寸\n")
    sz = res["sizing"]
    L.append(f"w = {sz['w_used']:.4f}({'可达' if sz['reachable'] else '**尺寸不可行,按 w = 1 报**'};"
             f"w = 1 处的风险贡献 {sz['rc_at_w1']:.4f},窗口内最大可达 {sz['rc_max']:.4f};目标 10%)\n")
    L.append("## 4 · (i)–(iv) 分窗\n")
    L.append("| 窗 | 月数 | 年化 A_base → A_aug | 贡献(pp) | p_upper | ρ(贡献, A_base) 全样本/压力月 | ρ(贡献, R-v2) 全样本/压力月 | 最差 20 日 | 扣供资成本后最差 20 日 | 有效来源 | 判定 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for name in w:
        m = w[name]
        L.append(f"| {name} | {m['months']} | {m['cagr_base']*100:+.2f}% → {m['cagr_aug']*100:+.2f}% | "
                 f"{m['dcagr_pp']:+.2f} | {_f(m['p_upper'])} | {m['corr_acct_base_full']:+.3f} / {m['corr_acct_base_stress']:+.3f} | "
                 f"{m['corr_rv2_full']:+.3f} / {m['corr_rv2_stress']:+.3f} | "
                 f"{m['worst20_base']*100:+.1f}% → {m['worst20_aug']*100:+.1f}% | {m['worst20_no_cash']*100:+.1f}% | "
                 f"{m['eff_sources_base']:.2f} → {m['eff_sources']:.2f} | "
                 f"{'过' if m['pattern'][0] else '不过'}/{'过' if m['pattern'][1] else '不过'}/{'过' if m['pattern'][2] else '不过'} |")
    L.append("")
    L.append(f"(iv) 两半年窗的年化贡献都 > 0:**{'过' if res['iv_ok'] else '不过'}**\n")
    z = res["zero_signal_control"]
    L.append("## 5 · 零信号对照(随机 ±1 符号,200 次)\n")
    L.append(f"- 真信号年化(A_aug){z['real_cagr']*100:+.2f}%;随机符号分布中位 {z['null_median']*100:+.2f}%、"
             f"90 分位 {z['null_q90']*100:+.2f}%、标准差 {z['null_sd']*100:.2f}pp")
    L.append(f"- 真信号落在第 **{z['percentile_of_real']*100:.1f}** 分位(p_upper {z['p_upper']:.4f});"
             f"高于随机符号的 90 分位:**{'是' if z['above_q90'] else '否'}**\n")
    ro = res["report_only"]
    L.append("## 6 · 只报不判\n")
    L.append(f"- 袖子自己 {ro['sleeve_pre_account']['start']} → {ro['sleeve_pre_account']['end']}:"
             f"年化 {ro['sleeve_pre_account']['cagr']*100:+.2f}%、最大回撤 {ro['sleeve_pre_account']['max_dd']*100:+.2f}%")
    L.append(f"- 只多版:账户窗口之前年化 {ro['long_only']['pre_account_cagr']*100:+.2f}%、"
             f"全样本年化 {ro['long_only']['full_cagr']*100:+.2f}%、最大回撤 {ro['long_only']['full_max_dd']*100:+.2f}%")
    L.append(f"- 逐年(全样本):{json.dumps({k: round(v*100, 2) for k, v in ro['sleeve_yearly_full'].items()}, ensure_ascii=False)}")
    L.append(f"- 账户最差 20 日({FEB[0]} → {FEB[1]}):袖子弹子收益 {ro['feb_window_sleeve_ret']*100:+.2f}%")
    L.append(f"- R-v2 最差 12 个月({ro['rv2_worst12_window'][0]} → {ro['rv2_worst12_window'][1]}):袖子弹子收益 {ro['rv2_worst12_sleeve_ret']*100:+.2f}%")
    L.append(f"- 每个资产的贡献(袖套自身累计):{json.dumps({k: round(v*100, 2) for k, v in ro['asset_contrib'].items()}, ensure_ascii=False)}(%)")
    L.append(f"- 去掉贡献最大的 `{ro['top_contributor']}`:账户窗口前年化 {ro['drop_top']['cagr_pre_account']*100:+.2f}%、"
             f"最大回撤 {ro['drop_top']['max_dd_pre_account']*100:+.2f}%\n")
    ex = (res.get("exploratory") or {}).get("spy_full_eodhd")
    if ex:
        L.append("## 7 · 探索性 —— 需另立预注册、在新数据上过零信号对照\n")
        L.append(f"- SPY 整段用 eodhd 复权源(登记口径是 2022-08-31 拼接):袖套账户窗口前年化 "
                 f"{ex['sleeve_pre_cagr']*100:+.2f}%、最大回撤 {ex['sleeve_pre_maxdd']*100:+.2f}%;"
                 f"w = {ex['w']:.4f}、全窗年化贡献 {ex['full']['dcagr_pp']:+.2f}pp"
                 f"(登记口径 {full['dcagr_pp']:+.2f}pp)。**不是本卡的判定口径,只报。**\n")
    open(OUT_MD, "w").write("\n".join(L))


if __name__ == "__main__":
    main()
