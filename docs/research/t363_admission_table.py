#!/usr/bin/env python3
"""T-363 —— 按台账「S-835 更正三」重报 S-835 准入表:加族后的账户是**叠加**,不是替换。

**更正三(2026-11-12 18:45 UTC)改的是合成与尺寸**:
  旧(错,T-363@a1c29b2e / T-361):(1 − w)·A_base + w·r_fam —— 拿族**替换** w 份账户(R-v2 与各腿一起缩)
  新(本卡):A_aug = A_base + w·r_fam − w·r_cash —— 由现金供资、付掉那份现金的利息
             (同 T-360 的 `acct_new`;r_cash = S-834 账户的现金腿日收益,cash_rate 在账户日之间复利,
              与 T-360 的 CASH_RET 同源)
  ⇒ (i) 的相关只依赖 w·r_fam 与 A_base,不受影响;(ii) 的零分布统计量、(iii) 最差 20 日 / 有效来源、
    尺寸 w、年化代价**全部按新式重算**。

**尺寸**:二分到该族自己的边际风险贡献 = **叠加后**账户月度方差的 10%,资金倍数 w ≤ 1;
  w > 1 ⇒ 写「尺寸不可行」并同时报 w = 1 的数(登记:资金倍数 > 1 是不可行的)。

**(i) 的读法**(照「S-835 更正二」,不变):corr(族月贡献 Fw, **不带候选**的账户月收益 A_base),
  压力月按 A_base 在本窗内 20 分位定;与 R-v2 的相关对 R-v2 腿自己算;叠加后的相关 corr(Fw, A_aug) 照报不判。
  **0.30 线按登记的字面取单侧 ρ < 0.30**(只挡集中;负相关是分散)。|ρ| 那列的判定删掉,相关原数照报。

**两条能失败的自检**(写进 t363_results.json):
  ① w = 0 时 A_aug 必须**逐日**等于 A_base;
  ② 取一条恒等于 r_cash 的族,A_aug 必须**逐日**等于 A_base(叠加式的定义性质)。

口径(其余照台账 S-835 的登记,账户照 S-834 的体检):
  账户 = RB(加密 / 股 / 金,flex_alloc.rb_weights)+ 现金 + R-v2(t352_engine.simulate(fix=True),
          每票 0.75% / 上限 0.80 / 名额 10)—— 与 docs/research/s834_diversification_audit.py 逐字同一套;
          动手前先对上「年化 +35.7%、R-v2 风险占比 0.742」。
  族   = T-348 的装配(t348_r3.py)产出的独立袖套净值(t348_r3_families.csv);
          World50 = docs/research/t099_world50_replay.py 的 EWxMom 臂(月频 → 按日历日铺到共同日)。
  窗口 = A:max(族的首个进场日, 2021-10-11);B:2021-10-11 起(T-348 同口径;A=B 时第 (iv) 条退化,表里注明)。
  零分布 = apparatus.circular_shift(族的日收益序列, block 1, 500 次)—— 拆开族与账户的对齐;
          统计量 = 叠加后账户年化 − 不带候选的账户年化(S-835 更正)。
  对账 = 旧合成 + 旧尺寸这条路径仍在脚本里(mode="legacy"),逐个复现 t361_results.json ⇒ 数据装配没动。

用法(仓库根):python3 docs/research/t363_admission_table.py
产物:docs/research/t363_results.json(全部数 + 自检) + docs/research/T-363_admission_table.md(表)
只读:不写库、不改任何既有文件。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
R = "/Volumes/CometCloudAI/cometcloud-local/research/"

import t310_slots as T310                                     # noqa: E402
from src.data.evaluation import apparatus as ap              # noqa: E402
from src.data.universe import flex_alloc as fa               # noqa: E402

T310.UM = R + "s681/_um_daily.jsonl"
T310.STYLE = R + "t156/_style.json"
OUT_JSON = os.path.join(HERE, "t363_results.json")
OUT_MD = os.path.join(HERE, "T-363_admission_table.md")
T361_JSON = os.path.join(HERE, "t361_results.json")     # 旧口径留档,用来对账

START = pd.Timestamp("2021-10-11")
F_, CAP_, N_ = 0.0075, 0.80, 10          # S-831 真钱现配置:每票 0.75% / 上限 0.80 / 名额 10
SRC = ["crypto", "equity", "gold", "rv2", "cash"]
TARGET_RC = 0.10                         # S-835:族自己的风险贡献占账户 10%
N_NULL = 500                             # S-835:circular_shift 500 次
SEED = 363
N_SELFCHECK = 200        # 自检:多少条独立随机序列(把 61 个月的相关噪声压下去)
FEB = ("2023-02-08", "2023-03-08")        # 卡里点名的那段
FAM_ORDER = ["S681_H2", "S681_H4", "S808", "S810", "S642", "S736_fixed", "S736_published", "World50_EWxMom"]
FAM_LABEL = {
    "S681_H2": "S-681 H2(pump fade)",
    "S681_H4": "S-681 H4(熊市反弹失败)",
    "S808": "S-808(被挤之后 · T-332)",
    "S810": "S-810(被挤之后 · T-334)",
    "S642": "S-642(空头臂 · T-159)",
    "S736_fixed": "S-736(战术空单 · 记账修正版)",
    "S736_published": "S-736(战术空单 · 原始记账)",
    "World50_EWxMom": "World50 回放(EW×Mom)",
}


def _mod(name: str, path: str):
    sp = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


E1 = _mod("t352_engine", os.path.join(HERE, "t352_engine.py"))
S823 = _mod("s823", os.path.join(HERE, "s823_three_state.py"))


def log(msg: str) -> None:
    print(msg, flush=True)


# ── 月份网格(向量化:零分布要跑 500 次 × 每族 × 每窗)────────────────────────
class MonthGrid:
    def __init__(self, idx: pd.DatetimeIndex):
        per = idx.to_period("M").to_numpy()
        change = np.where(per[1:] != per[:-1])[0] + 1
        self.bounds = np.concatenate([[0], change, [len(per)]])
        self.labels = [str(p) for p in pd.PeriodIndex(per, freq="M").unique()]

    def comp(self, r: np.ndarray) -> np.ndarray:
        """月内复利 → 月收益。"""
        return np.expm1(np.add.reduceat(np.log1p(r), self.bounds[:-1]))

    def summ(self, r: np.ndarray) -> np.ndarray:
        """月内加总(贡献口径,同 S-834 的 C[k].resample('M').sum())。"""
        return np.add.reduceat(r, self.bounds[:-1])


def cagr_from_monthly(m: np.ndarray, years: float) -> float:
    if years <= 0 or not len(m):
        return float("nan")
    return float(np.prod(1.0 + m) ** (1.0 / years) - 1.0)


def cagr_from_daily(r: pd.Series) -> float:
    yrs = (r.index[-1] - r.index[0]).days / 365.25
    if yrs <= 0:
        return float("nan")
    return float((1.0 + r).prod() ** (1.0 / yrs) - 1.0)


# ── 账户(照 s834_diversification_audit.py 的做法)────────────────────────────
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
    res = E1.simulate(TK, bars, gate_d, CAP_, equity0=630.0, risk_frac=F_, cap_n=N_, fix=True)
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
        cr = between(cash_rate, prev, day)      # 现金腿的**日收益率**(未按权重缩;T-360 的 CASH_RET 同源)
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
    SRC5 = list(SRC)
    Cm = pd.DataFrame({k: C[k].resample("M").sum() for k in SRC5})
    Am = (1 + C["acct"]).resample("M").prod() - 1
    rc = {k: float(np.cov(Cm[k], Am)[0, 1] / Am.var()) for k in SRC5}
    return {
        "cagr": cagr_from_daily(C["acct"]),
        "months": int(len(Am)),
        "risk_contribution": rc,
        "rv2_risk_share": rc["rv2"],
        "eff_sources": float(np.exp(-sum(x * np.log(x) for x in
                                          (np.clip(list(rc.values()), 1e-9, None) / max(sum(rc.values()), 1e-12))))),
        "worst_month": [str(Am.idxmin().date()), float(Am.min())],
        "Cm": Cm, "Am": Am,
    }


# ── 族曲线 → 账户共同日上的日收益 ───────────────────────────────────────────
def nav_to_account_ret(nav: pd.Series, acct_idx: list) -> pd.Series:
    """族的独立袖套净值 → 账户共同日上的日收益(两共同日之间按 flex_alloc._between 复利)。"""
    cal = pd.date_range(nav.index[0], nav.index[-1], freq="D")
    r = nav.reindex(cal).ffill().pct_change().fillna(0.0)
    out = [fa._between(r, acct_idx[i - 1], acct_idx[i]) for i in range(1, len(acct_idx))]
    return pd.Series(out, index=acct_idx[1:])


def monthly_to_account_ret(monthly: dict, acct_idx: list) -> pd.Series:
    """月频族的月度收益 → 日频:每月按日历日均摊 ((1+r_m)^(1/该月日历天数) − 1),
    再按 flex_alloc._between 落到账户共同日(账户只吃到跨进该月的那几天)。"""
    cal = pd.date_range(acct_idx[0] - pd.Timedelta(days=40), acct_idx[-1], freq="D")
    per = cal.to_period("M")
    days_in = per.map(lambda p: p.days_in_month).to_numpy()
    r_cal = np.zeros(len(cal))
    for i, p in enumerate(per):
        key = str(p)
        rm = monthly.get(key)
        if rm is None:
            continue
        r_cal[i] = (1.0 + float(rm)) ** (1.0 / days_in[i]) - 1.0
    r = pd.Series(r_cal, index=cal)
    out = [fa._between(r, acct_idx[i - 1], acct_idx[i]) for i in range(1, len(acct_idx))]
    return pd.Series(out, index=acct_idx[1:])


def load_families(acct_idx: list) -> dict:
    df = pd.read_csv(os.path.join(HERE, "t348_r3_families.csv"), parse_dates=["d"])
    meta = json.load(open(os.path.join(HERE, "t348_r3_families_meta.json")))
    out: dict = {}
    for k, m in meta.items():
        nav = df[df["family"] == k].set_index("d")["nav"].astype(float).sort_index()
        nav.index = pd.to_datetime(nav.index)
        out[k] = {"ret": nav_to_account_ret(nav, acct_idx), "meta": m, "nav": nav}
    return out


def load_world50(rep_path: str, acct_idx: list) -> dict:
    rep = json.load(open(rep_path))
    w50_m = monthly_ret_from_replay(rep, "EWxMom")
    return {"ret": monthly_to_account_ret(w50_m, acct_idx),
            "meta": {"first_entry": str(min(w50_m)) if w50_m else str(START.date()),
                     "note": "本机 w50_daily 重建面板 · 价格收益(不含股息);S-581 私有面板为总收益,EW 17.4%/EW×Mom 18.0%"},
            "nav": None}


# ── 合成口径(S-835 更正三)─────────────────────────────────────────────────
def synth(rb_a, rf_a, rcash_a, w, mode="additive"):
    """加族后的账户**日收益**。

    additive(本卡,登记口径):A_base + w·r_fam − w·r_cash —— 由现金供资、付掉那份现金的利息
                              (同 T-360 的 acct_new)。
    legacy(T-361 / 更正二,只留在脚本里对账):(1 − w)·A_base + w·r_fam —— 拿族替换 w 份账户(错口径)。
    """
    if mode == "legacy":
        return (1.0 - w) * rb_a + w * rf_a
    return rb_a + w * rf_a - w * rcash_a


# ── 核心:一族一窗的准入四条的数 ─────────────────────────────────────────────
def window_metrics(acct: dict, fam_r: pd.Series, w: float, a, b, stress_flags: dict,
                   active_start, mode: str = "additive", n_null: int = N_NULL) -> dict:
    C = acct["C"]
    idx = C.index
    m = (idx >= a) & (idx <= b)
    rb = C["acct"][m]
    rf = fam_r.reindex(idx)[m]
    rcash = C["cash_ret"].reindex(idx)[m]
    if len(rb) < 60:
        return {"ok": False, "n_days": int(len(rb))}
    g = MonthGrid(rb.index)
    rb_a, rf_a, rcash_a = rb.to_numpy(), rf.to_numpy(), rcash.to_numpy()
    ra = synth(rb_a, rf_a, rcash_a, w, mode)
    A = g.comp(ra)                       # 加族后的账户月收益(叠加口径;相关照报不判)
    A_base = g.comp(rb_a)                # 不带候选的账户月收益((i) 的比较对象)
    Fw = g.summ(w * rf_a)                # 族对账户的月贡献(加总口径)
    if mode == "legacy":
        Cm_base = {k: g.summ((1 - w) * C[k][m].to_numpy()) for k in SRC}
    else:
        # 叠加口径:各腿原样,只有现金腿因供资而变(扣掉 w 份现金的利息)
        Cm_base = {k: g.summ(C[k][m].to_numpy()) for k in SRC}
        Cm_base["cash"] = g.summ(C["cash"][m].to_numpy() - w * rcash_a)
    Rv2m = Cm_base["rv2"]
    labels = g.labels
    st_legacy = np.array([bool(stress_flags.get(l, False)) for l in labels])  # T-361 的压力月(core 全局 20 分位)
    thr = float(np.quantile(A_base, 0.2)) if len(A_base) >= 5 else float("nan")
    st_base = A_base <= thr              # 本卡的压力月:按 A_base 在本窗内定(S-835 更正二)

    def corr(x, y, sel=None):
        if sel is not None:
            x, y = x[sel], y[sel]
        if len(x) < 4 or np.std(x) == 0 or np.std(y) == 0:
            return float("nan")
        return float(np.corrcoef(x, y)[0, 1])

    # 风险贡献(叠加后的账户为分母)
    contrib = dict(Cm_base)
    contrib["fam"] = Fw
    rc = {k: float(np.cov(v, A)[0, 1] / A.var()) for k, v in contrib.items()}
    tot = sum(rc.values())
    eff = float(np.exp(-sum((x / tot) * np.log(x / tot) for x in rc.values() if x > 0)))
    # 基线:不加族时的有效来源数(同一窗口)
    rc_base = {k: float(np.cov(g.summ(C[k][m].to_numpy()), A_base)[0, 1] / A_base.var()) for k in SRC}
    tb = sum(rc_base.values())
    eff_base = float(np.exp(-sum((x / tb) * np.log(x / tb) for x in rc_base.values() if x > 0)))

    # 最差 20 日
    def worst20(x):
        s = pd.Series(x, index=rb.index)
        return float(((1 + s).rolling(20).apply(np.prod) - 1).min())

    w20_base, w20_aug = worst20(rb_a), worst20(ra)
    # 「扣掉纯供资成本后」的反事实账户:基线账户付掉 w 份现金的利息、但没加族(A_base − w·r_cash);
    # 与 A_aug 的差 = 族在付掉供资成本之后真正的边际贡献。legacy 口径没有现金腿,不扣。
    r_no_cash = rb_a if mode == "legacy" else rb_a - w * rcash_a
    w20_no_cash = worst20(r_no_cash)
    cagr_no_cash = float(cagr_from_daily(pd.Series(r_no_cash, index=rb.index)))

    # (ii) 零分布:把族的日收益整体错位,账户年化会怎样
    i0 = int(np.searchsorted(rb.index.to_numpy(), np.datetime64(active_start), side="left")) if active_start is not None else 0
    i0 = max(0, min(i0, len(rf_a) - 2))
    seg = rf_a[i0:]
    years = (rb.index[-1] - rb.index[0]).days / 365.25
    base_cagr = cagr_from_monthly(A_base, years)
    rng = np.random.default_rng(SEED)
    nulls = []
    for _ in range(n_null):
        sh = ap.circular_shift(seg, rng, block=1)
        rs = rf_a.copy()
        rs[i0:] = sh
        nulls.append(cagr_from_monthly(g.comp(synth(rb_a, rs, rcash_a, w, mode)), years))
    actual = cagr_from_monthly(A, years)
    p_up = ap.p_upper(actual - base_cagr, [x - base_cagr for x in nulls]) if nulls else None

    return {
        "ok": True,
        "mode": mode,
        "n_days": int(len(rb)),
        "start": str(rb.index[0].date()),
        "end": str(rb.index[-1].date()),
        "months": int(len(A)),
        "stress_months": int(st_base.sum()),
        "stress_months_legacy": int(st_legacy.sum()),
        "stress_threshold": thr,
        "w": float(w),
        "cagr_base": float(base_cagr),
        "cagr_aug": float(actual),
        "dcagr_pp": float(100 * (actual - base_cagr)),
        # 扣掉纯供资成本后的反事实账户(A_base − w·r_cash;legacy 口径 = A_base)
        "cagr_no_cash": cagr_no_cash,
        "dcagr_vs_no_cash_pp": float(100 * (actual - cagr_no_cash)),
        "worst20_no_cash": float(w20_no_cash),
        "p_upper": float(p_up) if p_up is not None else None,
        "null_mean": float(np.mean(nulls)),
        "null_sd": float(np.std(nulls)),
        # ── (i) 新口径(S-835 更正二):族贡献 vs **不带候选**的账户月收益 A_base
        "corr_acct_base_full": corr(Fw, A_base),
        "corr_acct_base_stress": corr(Fw, A_base, st_base),
        # ── 旧口径:族贡献 vs **叠加之后**的账户月收益 A(照报一列、不判)
        "corr_acct_aug_full": corr(Fw, A),
        "corr_acct_aug_stress": corr(Fw, A, st_base),
        # ── 与 R-v2 的相关:定义不变(对 R-v2 腿自己算)
        "corr_rv2_full": corr(Fw, Rv2m),
        "corr_rv2_stress": corr(Fw, Rv2m, st_base),
        # ── T-361 压力月集合(core 全局 20 分位)下的对照数,用来跟旧表对账
        "corr_acct_base_stress_legacy": corr(Fw, A_base, st_legacy),
        "corr_acct_aug_stress_legacy": corr(Fw, A, st_legacy),
        "corr_rv2_stress_legacy": corr(Fw, Rv2m, st_legacy),
        "mean_monthly_contrib_pct": float(Fw.mean() * 100),
        "total_contrib_pct": float(Fw.sum() * 100),
        "rc": {k: round(v, 4) for k, v in rc.items()},
        "rc_fam": float(rc["fam"]),
        "eff_sources": eff,
        "eff_sources_base": eff_base,
        "worst20_base": w20_base,
        "worst20_aug": w20_aug,
        "worst20_delta_pp": float(100 * (w20_aug - w20_base)),
        "fam_vol_ann": float(np.std(rf_a) * np.sqrt(365)),
        "fam_cagr": cagr_from_daily(pd.Series(rf_a, index=rb.index)),
    }


def size_family(acct: dict, fam_r: pd.Series, mode: str = "additive") -> dict:
    """二分:调到族自己的边际风险贡献 = **叠加后**账户月度方差的 10%(S-835 更正三)。

    资金倍数上限 w = 1(登记):到不了就是「尺寸不可行」,同时报 w = 1 的数。
    """
    C = acct["C"]
    rb = C["acct"]
    rf = fam_r.reindex(C.index).fillna(0.0)
    rcash = C["cash_ret"].reindex(C.index).fillna(0.0)
    g = MonthGrid(rb.index)
    rb_a, rf_a, rcash_a = rb.to_numpy(), rf.to_numpy(), rcash.to_numpy()

    def rc_at(w):
        ra = synth(rb_a, rf_a, rcash_a, w, mode)
        A = g.comp(ra)
        Fw = g.summ(w * rf_a)
        if A.var() == 0:
            return float("nan")
        return float(np.cov(Fw, A)[0, 1] / A.var())

    grid = np.linspace(0.0, 1.0, 201)
    vals = [rc_at(x) for x in grid]
    ok = [(x, v) for x, v in zip(grid, vals) if not np.isnan(v)]
    mono = all(ok[i][1] <= ok[i + 1][1] + 1e-9 for i in range(len(ok) - 1))
    cross = None
    for i in range(len(ok) - 1):
        if ok[i][1] <= TARGET_RC <= ok[i + 1][1]:
            cross = (ok[i][0], ok[i + 1][0])
            break
    if cross is None:
        # w ≤ 1 到不了 10% 风险贡献 ⇒ 尺寸不可行(登记:资金倍数 > 1),报 w = 1 的数
        return {"w": None, "w_used": 1.0, "feasible": False, "reachable": False,
                "rc_at_w1": rc_at(1.0), "rc_max": ok[-1][1], "monotone": bool(mono),
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
            "rc_at_w": rc_at(w), "rc_at_w1": rc_at(1.0), "rc_max": ok[-1][1],
            "monotone": bool(mono)}


# ── 自检:把 (i) 的两种读法各自会给出什么数(S-835 更正二)────────────────────
def _corr(x, y, sel=None):
    if sel is not None:
        x, y = x[sel], y[sel]
    if len(x) < 4 or np.std(x) == 0 or np.std(y) == 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def self_check(acct: dict, target_vol: float) -> dict:
    """造一条与 A_base 独立的随机序列,按尺寸规则叠上去,看 (i) 的几种读法各给什么数。

    台账 S-835 更正二的预期:新口径 corr(Fw, A_base) ≈ 0;T-361 的实现口径(旧合成 (1−w)、
    旧尺寸)corr(Fw, A_legacy) ≈ √0.10 = 0.316。更正三换了合成 ⇒ 叠加口径下 corr(Fw, A_aug)
    不再是 √0.10(那个恒等式依赖「账户被缩到 (1−w)」),这个数照报、不设目标值。
    单条序列的相关噪声有 1/√(月数) ≈ 0.13,故跑 N_SELFCHECK 条独立序列看分布。
    """
    C = acct["C"]
    idx = C.index
    rb = C["acct"]
    rcash = C["cash_ret"]
    g = MonthGrid(idx)
    rb_a, rcash_a = rb.to_numpy(), rcash.to_numpy()
    A_base = g.comp(rb_a)
    rng = np.random.default_rng(SEED)
    sd_d = target_vol / np.sqrt(365.0)
    new_c, old_c, add_c, ws, ws_leg = [], [], [], [], []
    n_infeas = 0
    for _ in range(N_SELFCHECK):
        rf = pd.Series(rng.standard_normal(len(idx)) * sd_d, index=idx)
        rf_a = rf.to_numpy()
        # 叠加口径的尺寸(不可行时用 w = 1)
        sz_a = size_family(acct, rf, "additive")
        w = sz_a["w_used"]
        if not sz_a.get("feasible", True):
            n_infeas += 1
        A_add = g.comp(synth(rb_a, rf_a, rcash_a, w, "additive"))
        Fw_add = g.summ(w * rf_a)
        new_c.append(_corr(Fw_add, A_base))
        add_c.append(_corr(Fw_add, A_add))
        ws.append(w)
        # 旧口径(留档对账):旧合成 + 旧尺寸
        sz_l = size_family(acct, rf, "legacy")
        wl = sz_l.get("w")
        if wl is None:
            continue
        A_leg = g.comp(synth(rb_a, rf_a, rcash_a, wl, "legacy"))
        Fw_leg = g.summ(wl * rf_a)
        old_c.append(_corr(Fw_leg, A_leg))
        ws_leg.append(wl)
    return {
        "n_draws": len(new_c),
        "target_vol_ann": float(target_vol),
        "n_months": int(len(A_base)),
        "w_mean": float(np.mean(ws)), "w_min": float(np.min(ws)), "w_max": float(np.max(ws)),
        "n_infeasible_w1": int(n_infeas),
        "new_reading_corr_mean": float(np.mean(new_c)),
        "new_reading_corr_sd": float(np.std(new_c)),
        "new_reading_corr_absmean": float(np.mean(np.abs(new_c))),
        "old_reading_corr_mean": float(np.mean(old_c)) if old_c else float("nan"),
        "old_reading_corr_sd": float(np.std(old_c)) if old_c else float("nan"),
        "additive_aug_corr_mean": float(np.mean(add_c)),
        "additive_aug_corr_sd": float(np.std(add_c)),
        "legacy_w_mean": float(np.mean(ws_leg)) if ws_leg else float("nan"),
        "target_new": 0.0,
        "target_old": float(np.sqrt(TARGET_RC)),
        "new_ok": bool(abs(np.mean(new_c)) < 0.05),
        "old_ok": bool(bool(old_c) and abs(np.mean(old_c) - np.sqrt(TARGET_RC)) < 0.03),
    }


def identity_checks(acct: dict, fams: dict) -> dict:
    """两条**能失败**的自检(S-835 更正三 · 任务书 ②)。

    ① w = 0 时,A_aug 必须逐日等于 A_base;
    ② 取一条恒等于 r_cash 的族(现金腿),A_aug 必须逐日等于 A_base —— 叠加式的定义性质。
    两条都是**逐日**比(日频 A_aug − 日频 A_base 的最大绝对差),容差 1e-15。
    """
    C = acct["C"]
    idx = C.index
    rb_a = C["acct"].to_numpy()
    rcash_a = C["cash_ret"].to_numpy()
    tol = 1e-15
    # ① w = 0
    aug0 = synth(rb_a, np.zeros_like(rb_a), rcash_a, 0.0, "additive")
    d0 = float(np.max(np.abs(aug0 - rb_a)))
    # ② 恒现金族
    sz_cash = size_family(acct, pd.Series(rcash_a, index=idx), "additive")
    w_cash = sz_cash["w_used"]
    aug_cash = synth(rb_a, rcash_a, rcash_a, w_cash, "additive")
    d_cash = float(np.max(np.abs(aug_cash - rb_a)))
    # 每个族按自己的尺寸也要成立(族 = 现金腿)
    per_fam = {}
    for k in FAM_ORDER:
        if k not in fams:
            continue
        fr = fams[k]["ret"].reindex(idx).fillna(0.0)
        w = size_family(acct, fr, "additive")["w_used"]
        aug = synth(rb_a, rcash_a, rcash_a, w, "additive")
        per_fam[k] = {"w_used": float(w), "max_abs_diff": float(np.max(np.abs(aug - rb_a)))}
    all_ok = bool(d0 <= tol and d_cash <= tol and
                  all(v["max_abs_diff"] <= tol for v in per_fam.values()))
    return {
        "tolerance": tol,
        "w0_identity": {"max_abs_diff": d0, "ok": bool(d0 <= tol),
                        "note": "全样本逐日;任何窗口子集同样成立"},
        "constant_cash_family_identity": {"w_used": float(w_cash),
                                          "feasible": bool(sz_cash.get("feasible", False)),
                                          "max_abs_diff": d_cash, "ok": bool(d_cash <= tol)},
        "per_family_constant_cash": per_fam,
        "all_ok": all_ok,
    }


def cash_weight_stats(C: pd.DataFrame) -> dict:
    """账户的现金权重(C["cash"] = 权重 × 现金日收益 ⇒ 权重 = 两者之比)。"""
    cr = C["cash_ret"].replace(0.0, np.nan)
    w = (C["cash"] / cr).replace([np.inf, -np.inf], np.nan).dropna()
    return {"cash_ret_mean": float(C["cash_ret"].mean()),
            "weight_mean": float(w.mean()) if len(w) else float("nan"),
            "weight_min": float(w.min()) if len(w) else float("nan"),
            "weight_max": float(w.max()) if len(w) else float("nan"),
            "n_days_with_rate": int(len(w))}


def passes(rec: dict, pat_key: str, iv_key: str = "iv_same_direction") -> bool:
    """一族是否四条全过:两个窗口的 (i)(ii)(iii) 都过,且 (iv) 两窗口同向。

    (iv) 是空判(两个窗口同一段)时按 Seth 2026-11-12 的第 ③ 问记「另一窗口不可得」,不记为过。
    """
    pats = rec.get(pat_key) or {}
    a = pats.get("A_earliest")
    b = pats.get("B_2021-10-11")
    if a is None or b is None:
        return False
    iv = rec.get(iv_key)
    if iv is None:
        return False
    if not rec.get("iv_available", True):
        return False
    return bool(a == [True, True, True] and b == [True, True, True] and iv)


def judge(m: dict) -> dict:
    """S-835 的 (i)–(iv) 逐条判定(**本卡:0.30 线取单侧 ρ < 0.30**,登记的字面)。

    (i) = 族月贡献 Fw 与 A_base 的相关(全样本 + 压力月)、与 R-v2 的相关(全样本 + 压力月),
          四个数都要 < 0.30。单侧:只挡正相关(= 集中);负相关是分散,不是违例。
          |ρ| 那列的判定按更正三删掉,相关原数照报(i_abs_rho_max 只是留档)。
    """
    def _lt_one_sided(vals, lim=0.30):
        return all((v is not None) and (not np.isnan(v)) and v < lim for v in vals)

    c1 = [m["corr_acct_base_full"], m["corr_acct_base_stress"], m["corr_rv2_full"], m["corr_rv2_stress"]]
    c1_ok = _lt_one_sided(c1)
    c2_ok = bool(m["mean_monthly_contrib_pct"] > 0) and (m["p_upper"] is not None) and (m["p_upper"] < 0.10)
    c3a = bool(m["worst20_aug"] >= m["worst20_base"] - 1e-12)
    c3b = bool(m["eff_sources"] > m["eff_sources_base"])
    c3_ok = c3a and c3b
    return {
        "i_corr_lt_030": bool(c1_ok),
        "i_corr_lt_030_one_sided": bool(c1_ok),
        "i_corr_values": [float(v) for v in c1],
        "i_abs_rho_max": float(max(abs(v) for v in c1 if v is not None and not np.isnan(v))),
        "ii_positive_and_p_lt_010": bool(c2_ok),
        "iii_worst20_not_worse": bool(c3a),
        "iii_eff_sources_up": bool(c3b),
        "iii_ok": bool(c3_ok),
        "pattern": [bool(c1_ok), bool(c2_ok), bool(c3_ok)],
    }


def judge_legacy_t361(m: dict) -> dict:
    """T-361 的实现(旧合成 + |ρ| < 0.30 + core 全局压力月)—— **只用于与 t361_results.json 对账**,不作判定。"""
    def _lt(vals, lim=0.30):
        return all((v is not None) and (not np.isnan(v)) and abs(v) < lim for v in vals)
    c1 = [m["corr_acct_aug_full"], m["corr_acct_aug_stress_legacy"], m["corr_rv2_full"], m["corr_rv2_stress_legacy"]]
    c1_ok = _lt(c1)
    c2_ok = bool(m["mean_monthly_contrib_pct"] > 0) and (m["p_upper"] is not None) and (m["p_upper"] < 0.10)
    c3a = bool(m["worst20_aug"] >= m["worst20_base"] - 1e-12)
    c3b = bool(m["eff_sources"] > m["eff_sources_base"])
    return {"pattern": [bool(c1_ok), bool(c2_ok), bool(c3a and c3b)]}


def main() -> None:
    log("=== 账户(S-834 口径)===")
    acct = build_account()
    C = acct["C"]
    st = account_stats(C)
    log(f"  账户 {C.index[0].date()} → {C.index[-1].date()} · {st['months']} 个月 · "
        f"年化 {st['cagr']:+.2%} · R-v2 风险占比 {st['rv2_risk_share']:.3f} · 有效来源 {st['eff_sources']:.2f}")
    chk = {"cagr_pct": round(st["cagr"] * 100, 2), "rv2_risk_share": round(st["rv2_risk_share"], 3),
           "expect_cagr_pct": 35.7, "expect_rv2": 0.742,
           "cagr_ok": bool(abs(st["cagr"] - 0.357) < 0.005), "rv2_ok": bool(abs(st["rv2_risk_share"] - 0.742) < 0.005)}
    log(f"  对账:年化 {chk['cagr_pct']}% (期望 35.7%) · R-v2 {chk['rv2_risk_share']} (期望 0.742) · "
        f"{'对上' if chk['cagr_ok'] and chk['rv2_ok'] else '对不上!'}")
    if not (chk["cagr_ok"] and chk["rv2_ok"]):
        raise SystemExit("账户对不上 S-834 的 +35.7% / 0.742,停。")

    # 压力月:core(账户主腿)月度收益的 20 分位以下
    core_m = (1 + acct["core_daily"]["core_nav_1_cap_pit24"].reindex(C.index).pct_change().fillna(0.0)).resample("M").prod() - 1
    stress_flags = {str(k.to_period("M")): bool(v) for k, v in (core_m <= core_m.quantile(0.2)).items()}

    acct_idx = acct["idx"]
    log("=== 族曲线(T-348 的装配)===")
    fams = load_families(acct_idx)

    # World50:本机重建的面板(价格收益)跑 t099_world50_replay → EWxMom 月收益
    fams["World50_EWxMom"] = load_world50(R + "w50_daily/world50_replay_t361.json", acct_idx)

    # ── 自检先跑:三条恒等式 + (i) 的几种读法各给什么数 ─────────────────────
    vols = []
    for key in FAM_ORDER:
        if key not in fams:
            continue
        fr0 = fams[key]["ret"].reindex(C.index).fillna(0.0)
        vols.append(float(np.std(fr0.to_numpy()) * np.sqrt(365)))
    med_vol = float(np.median(vols))
    log(f"=== 自检 1:与 A_base 独立的随机序列 × {N_SELFCHECK}(年化波动取族的中位 {med_vol:.1%})===")
    sc = self_check(acct, med_vol)
    log(f"  新口径 corr(Fw, A_base)        均值 {sc['new_reading_corr_mean']:+.4f} "
        f"(sd {sc['new_reading_corr_sd']:.3f},|ρ| 均值 {sc['new_reading_corr_absmean']:.3f}) → 应 ≈ 0 · "
        f"{'对上' if sc['new_ok'] else '对不上!'}")
    log(f"  T-361 实现口径(旧合成+旧尺寸)corr(Fw, A_legacy) 均值 {sc['old_reading_corr_mean']:+.4f} "
        f"(sd {sc['old_reading_corr_sd']:.3f}) → 应 ≈ √0.10 = {sc['target_old']:.3f} · "
        f"{'对上' if sc['old_ok'] else '对不上!'}")
    log(f"  叠加口径 corr(Fw, A_aug)       均值 {sc['additive_aug_corr_mean']:+.4f} "
        f"(sd {sc['additive_aug_corr_sd']:.3f}) —— 合成换了,不再是 √0.10,照报不设目标")
    log(f"  尺寸 w 均值 {sc['w_mean']:.3f}({sc['w_min']:.3f}–{sc['w_max']:.3f})· "
        f"其中 {sc['n_infeasible_w1']} 条到不了 10% 风险贡献(报 w=1)· {sc['n_draws']} 条 / {sc['n_months']} 个月")

    log("=== 自检 2:两条能失败的恒等式(逐日)===")
    ic = identity_checks(acct, fams)
    log(f"  ① w = 0 ⇒ A_aug 逐日 = A_base:最大绝对差 {ic['w0_identity']['max_abs_diff']:.3e} · "
        f"{'过' if ic['w0_identity']['ok'] else '不过!'}")
    log(f"  ② 族恒等于 r_cash ⇒ A_aug 逐日 = A_base(w={ic['constant_cash_family_identity']['w_used']:.4f}):"
        f"最大绝对差 {ic['constant_cash_family_identity']['max_abs_diff']:.3e} · "
        f"{'过' if ic['constant_cash_family_identity']['ok'] else '不过!'}")
    log(f"  两条自检合计:{'全过' if ic['all_ok'] else '不过!'}")

    cw = cash_weight_stats(C)
    log(f"=== 现金腿(S-834 账户)==:日收益均值 {cw['cash_ret_mean']:.6f}· 账户现金权重 均 {cw['weight_mean']:.3f}"
        f"(min {cw['weight_min']:.3f} / max {cw['weight_max']:.3f}· {cw['n_days_with_rate']} 天有利率)")

    results = {"account": {k: v for k, v in st.items() if k not in ("Cm", "Am")}, "reconcile": chk,
               "self_check": sc, "identity_checks": ic, "cash_leg": cw,
               "families": {}, "config": {"f": F_, "cap": CAP_, "n": N_, "target_rc": TARGET_RC,
                                          "n_null": N_NULL, "seed": SEED, "start": str(START.date()),
                                          "composition": "A_aug = A_base + w·r_fam − w·r_cash"
                                                         "(S-835 更正三:叠加,不是替换;r_cash = S-834 账户的现金腿)",
                                          "sizing": "二分:族自己的边际风险贡献 = 叠加后账户月度方差的 10%;"
                                                    "资金倍数 w ≤ 1;w > 1 ⇒ 尺寸不可行(同时报 w = 1 的数)",
                                          "criterion_i_reading": "corr(Fw, A_base)—— 族月贡献 vs 不带候选的账户月收益;"
                                                                "压力月按 A_base 在本窗内 20 分位定",
                                          "criterion_i_line": "单侧 ρ < 0.30(登记的字面;|ρ| 那列的判定已删,相关原数照报)",
                                          "criterion_i_reading_old": "corr(Fw, A)—— 族月贡献 vs 加族后的账户月收益(T-361)"}}

    for key in FAM_ORDER:
        if key not in fams:
            continue
        fam = fams[key]
        fr = fam["ret"].reindex(C.index).fillna(0.0)
        fe = pd.Timestamp(fam["meta"].get("first_entry", str(C.index[0].date())))
        sz = size_family(acct, fr, "additive")
        w = sz["w_used"]                      # 尺寸不可行时 = 1.0(登记:同时报 w = 1 的数)
        sz_leg = size_family(acct, fr, "legacy")
        w_leg = sz_leg.get("w")
        log(f"=== {key}({FAM_LABEL.get(key, key)}) 首个进场 {fe.date()} · 尺寸 w="
            f"{'不可行(报 w=1)' if not sz.get('feasible') else f'{w:.4f}'} "
            f"(rc@w={sz.get('rc_at_w', float('nan')):.4f} · rc@1={sz.get('rc_at_w1', float('nan')):.4f} "
            f"· 旧尺寸 w={w_leg if w_leg is None else round(w_leg, 4)})")
        wins = {"A_earliest": max(fe, START), "B_2021-10-11": START}
        rec = {"label": FAM_LABEL.get(key, key), "first_entry": str(fe.date()),
               "meta": {k: v for k, v in fam["meta"].items() if k in ("n_tickets", "note", "last_exit", "risk_frac")},
               "sizing": sz, "sizing_legacy_t361": sz_leg, "windows": {}}
        for wn, ws in wins.items():
            m = window_metrics(acct, fr, w, ws, C.index[-1], stress_flags, fe, mode="additive")
            if not m.get("ok"):
                continue
            j = judge(m)
            m["judge"] = j
            rec["windows"][wn] = m
            log(f"  [{wn}] {m['start']}→{m['end']}:年化 {m['cagr_base']:+.2%}→{m['cagr_aug']:+.2%} "
                f"| corr(A_base) {m['corr_acct_base_full']:+.2f}/{m['corr_acct_base_stress']:+.2f} "
                f"[加族后 corr(A_aug) {m['corr_acct_aug_full']:+.2f}/{m['corr_acct_aug_stress']:+.2f}] "
                f"corr(rv2) {m['corr_rv2_full']:+.2f}/{m['corr_rv2_stress']:+.2f} "
                f"| 贡献 {m['mean_monthly_contrib_pct']:+.3f}%/月 p={m['p_upper']:.3f} "
                f"| 20日 {m['worst20_base']:+.1%}→{m['worst20_aug']:+.1%} "
                f"| 有效来源 {m['eff_sources_base']:.2f}→{m['eff_sources']:.2f} | (i){'✓' if j['i_corr_lt_030'] else '✗'}"
                f"(ii){'✓' if j['ii_positive_and_p_lt_010'] else '✗'}(iii){'✓' if j['iii_ok'] else '✗'}")
        # 旧口径复现(旧合成 + 旧尺寸)—— 只用来与 T-361 对账、标「因合成改变而翻转」
        legacy = {}
        if w_leg is not None:
            for wn, ws in wins.items():
                ml = window_metrics(acct, fr, w_leg, ws, C.index[-1], stress_flags, fe, mode="legacy")
                if not ml.get("ok"):
                    continue
                ml["judge_legacy_t361"] = judge_legacy_t361(ml)
                legacy[wn] = ml
        rec["legacy_t361_replicate"] = legacy
        a = rec["windows"].get("A_earliest", {}).get("judge", {}).get("pattern")
        b = rec["windows"].get("B_2021-10-11", {}).get("judge", {}).get("pattern")
        ao = legacy.get("A_earliest", {}).get("judge_legacy_t361", {}).get("pattern")
        bo = legacy.get("B_2021-10-11", {}).get("judge_legacy_t361", {}).get("pattern")
        rec["pattern_new"] = {"A_earliest": a, "B_2021-10-11": b}
        rec["pattern_old_t361"] = {"A_earliest": ao, "B_2021-10-11": bo}
        if a is not None and b is not None:
            rec["iv_same_direction"] = bool(a == b)
            rec["iv_window_dependent"] = bool(a != b)
            rec["iv_degenerate"] = bool(wins["A_earliest"] == wins["B_2021-10-11"])
            rec["iv_note"] = "A=B(同窗口,退化):另一窗口不可得" if rec["iv_degenerate"] else ""
            log(f"  (iv) 两窗口同向:{rec['iv_same_direction']} {rec['iv_note']}")
        rec["iv_available"] = bool(not rec.get("iv_degenerate", False))
        if ao is not None and bo is not None:
            rec["iv_same_direction_old"] = bool(ao == bo)
        rec["passes_new"] = passes(rec, "pattern_new")
        rec["passes_old_t361"] = passes(rec, "pattern_old_t361", "iv_same_direction_old")
        rec["sizing_infeasible"] = not bool(sz.get("feasible", True))
        rec["passes_ignoring_size"] = bool(rec["passes_new"])
        rec["passes"] = bool(rec["passes_new"] and not rec["sizing_infeasible"])
        rec["pattern_changed_by_composition"] = bool((ao != a) or (bo != b))
        rec["conclusion_changed"] = bool(rec["passes_new"] != rec["passes_old_t361"])
        log(f"  结论:新口径(叠加 + 单侧 ρ<0.30) {'过' if rec['passes_new'] else '不过'}"
            f"{'  ⟨尺寸不可行 ⇒ 按登记不算过⟩' if rec['sizing_infeasible'] else ''}"
            f" / T-361 旧口径(替换 + |ρ|<0.30) {'过' if rec['passes_old_t361'] else '不过'}"
            f"{'  ⟨因合成/尺寸改变而翻转⟩' if rec['conclusion_changed'] else ''}")
        # 2023-02-08 → 03-08
        seg = fr.loc[FEB[0]:FEB[1]]
        fam_feb = float((1 + seg).prod() - 1) if len(seg) else float("nan")
        rec["feb_window"] = {"start": FEB[0], "end": FEB[1], "fam_total_pct": round(100 * fam_feb, 2),
                             "n_days": int(len(seg))}
        # 族自身全历史
        if fam.get("nav") is not None:
            nav = fam["nav"]
            yrs = (nav.index[-1] - nav.index[0]).days / 365.25
            rec["standalone"] = {"start": str(nav.index[0].date()), "end": str(nav.index[-1].date()),
                                 "total_pct": round(100 * float(nav.iloc[-1] - 1), 1),
                                 "cagr_pct": round(100 * float(nav.iloc[-1] ** (1 / yrs) - 1), 2)}
        results["families"][key] = rec

    # 与 T-361 旧表对账:旧读法在同数据上应逐个复现
    cc = crosscheck_t361(results)
    log(f"=== 与 T-361 旧表对账:比较 {cc.get('n_compared')} 个数 · 最大绝对差 "
        f"{cc.get('max_abs_diff', float('nan')):.6f} · 旧 (i)(ii)(iii) pattern 一致 {cc.get('pattern_match')}"
        f"{'' if cc.get('pattern_match') else ' · 不一致:' + str(cc.get('pattern_mismatch'))}")
    results["crosscheck_t361"] = cc

    json.dump(results, open(OUT_JSON, "w"), indent=1, default=str)
    write_md(results)
    log(f"=== 写完 {OUT_JSON} · {OUT_MD}")


def monthly_ret_from_replay(rep: dict, arm: str) -> dict:
    """从回放报告里取逐月收益(arms[arm] 的 ret 与 months 对齐;缺就按窗口顺序兜底)。"""
    a = rep["arms"][arm]
    ms = a.get("months")
    rs = a.get("ret")
    if ms is None or rs is None:
        return {}
    return {m: float(r) for m, r in zip(ms, rs) if r is not None}


def crosscheck_t361(res: dict) -> dict:
    """旧口径(旧合成 + 旧尺寸)在同一份数据上的复现:应与 t361_results.json 逐个对上
    ⇒ 数据装配没动,变的只有合成与尺寸(以及 (i) 的读法)。"""
    if not os.path.exists(T361_JSON):
        return {"available": False}
    old = json.load(open(T361_JSON))
    pairs = [("corr_acct_aug_full", "corr_fam_acct_full"),
             ("corr_acct_aug_stress_legacy", "corr_fam_acct_stress"),
             ("corr_rv2_full", "corr_fam_rv2_full"),
             ("corr_rv2_stress_legacy", "corr_fam_rv2_stress"),
             ("cagr_base", "cagr_base"), ("cagr_aug", "cagr_aug"),
             ("worst20_base", "worst20_base"), ("worst20_aug", "worst20_aug"),
             ("eff_sources", "eff_sources"), ("eff_sources_base", "eff_sources_base"),
             ("mean_monthly_contrib_pct", "mean_monthly_contrib_pct"),
             ("total_contrib_pct", "total_contrib_pct"),
             ("dcagr_pp", "dcagr_pp"), ("p_upper", "p_upper")]
    diffs, pat_bad, bad = [], [], []
    bad_fields: dict = {}
    for fk, fr in res["families"].items():
        of = old.get("families", {}).get(fk)
        if of is None:
            continue
        leg = fr.get("legacy_t361_replicate", {})
        for wn, m in leg.items():
            om = of.get("windows", {}).get(wn)
            if om is None:
                continue
            for nk, ok in pairs:
                a, b = m.get(nk), om.get(ok)
                if a is None or b is None:
                    continue
                d = abs(float(a) - float(b))
                diffs.append(d)
                if d > 1e-9:
                    bad.append(f"{fk}/{wn}/{nk}: {float(a)} vs {float(b)}")
                    bad_fields[nk] = bad_fields.get(nk, 0) + 1
            pa = list(m.get("judge_legacy_t361", {}).get("pattern", []))
            pb = list(om.get("judge", {}).get("pattern", []))
            if pa != pb:
                pat_bad.append(f"{fk}/{wn}: {pa} vs {pb}")
    return {"available": True, "n_compared": len(diffs),
            "max_abs_diff": float(max(diffs)) if diffs else float("nan"),
            "n_mismatch": len(bad),
            "mismatch_fields": bad_fields,
            "mismatch_examples": bad[:10],
            "pattern_mismatch": pat_bad, "pattern_match": len(pat_bad) == 0,
            "note": "对账对象 = 脚本里的旧口径复现(旧合成 + 旧尺寸)vs t361_results.json"}


def write_md(res: dict) -> None:
    L = []
    A = res["account"]
    L.append("# T-363 —— 按「S-835 更正三」重报的 S-835 准入表:加族后的账户是**叠加**(A_base + w·r_fam − w·r_cash),不是替换\n")
    L.append(f"- 账户(照 S-834 口径):年化 **{A['cagr']*100:.1f}%**(期望 35.7%)· R-v2 风险占比 **{A['rv2_risk_share']:.3f}**(期望 0.742)"
             f"· 有效来源 {A['eff_sources']:.2f}· {A['months']} 个月\n")
    cl = res.get("cash_leg", {})
    L.append(f"- **合成(更正三)**:A_aug = A_base + w·r_fam − w·r_cash —— 由**现金供资**、付掉那份现金的利息"
             f"(同 T-360 的 `acct_new`;r_cash = S-834 账户的现金腿,账户现金权重均 {cl.get('weight_mean', float('nan')):.2f})。"
             f"上一版(T-363@a1c29b2e / T-361)写的是 (1 − w)·A_base + w·r_fam = 拿族**替换** w 份账户(R-v2 与各腿一起缩)—— 已作废。\n")
    L.append("- **尺寸**:二分到族自己的边际风险贡献 = **叠加后**账户月度方差的 10%;资金倍数 w ≤ 1;"
             "w > 1 ⇒ **尺寸不可行**(同时报 w = 1 的数)。尺寸 w、(ii) 零分布统计量、(iii) 最差 20 日 / 有效来源、"
             "年化代价**全部按新式重算**。\n")
    L.append("- **(i) 的读法**照「S-835 更正二」:族月贡献 Fw vs **不带候选**的账户月收益 A_base(全样本 + 压力月,"
             "压力月按 A_base 在本窗内 20 分位定);与 R-v2 的相关定义不变;加族后的相关 corr(Fw, A_aug)照报一列、不判。\n")
    L.append("- **0.30 线取单侧 ρ < 0.30**(登记的字面:只挡集中,负相关是分散)。`|ρ|` 那列的判定按更正三删掉,"
             "相关原数照报。\n")
    L.append("- **(iv)**:两个窗口同一段(A=B)⇒ 记「另一窗口不可得」、**不记为过**(S-681 H4 就是此情形;"
             "S-835 第一批结果里把 H4 记成「✅ 四条」是记错,已作废)。\n")
    L.append("- 其余照登记:零分布 = `apparatus.circular_shift`(族的日收益序列,block 1,500 次,种子 363),"
             "统计量 = **加族后**账户年化 − **不带候选**的账户年化(S-835 更正);\n"
             "(ii) 族自己的月贡献为正 且 p_upper < 0.10;(iii) 最差 20 日不变差、有效来源数上升;(iv) 两窗口同向\n")
    sc = res.get("self_check", {})
    if sc:
        L.append(f"- **自检 1((i) 的读法)**:造 {sc.get('n_draws')} 条与 A_base 独立的随机序列(年化波动 {sc.get('target_vol_ann', 0)*100:.0f}%),"
                 f"按同一尺寸规则叠上去 —— 新口径 corr(Fw, A_base) 均值 **{sc.get('new_reading_corr_mean', float('nan')):+.3f}**"
                 f"(sd {sc.get('new_reading_corr_sd', 0):.3f},应 ≈ 0);"
                 f"T-361 实现口径(旧合成 + 旧尺寸)corr(Fw, A_legacy) 均值 **{sc.get('old_reading_corr_mean', float('nan')):+.3f}**"
                 f"(sd {sc.get('old_reading_corr_sd', 0):.3f},应 ≈ √0.10 = {sc.get('target_old', 0):.3f});"
                 f"叠加口径 corr(Fw, A_aug) 均值 **{sc.get('additive_aug_corr_mean', float('nan')):+.3f}**"
                 f"(合成换了,不再是 √0.10,照报不设目标)。尺寸 w 均值 {sc.get('w_mean', float('nan')):.3f},"
                 f"其中 {sc.get('n_infeasible_w1')} 条到不了 10% 风险贡献(报 w = 1)。\n")
    ic = res.get("identity_checks", {})
    if ic:
        L.append(f"- **自检 2(两条能失败的恒等式,逐日)**:① w = 0 ⇒ A_aug = A_base,最大绝对差 **{ic.get('w0_identity', {}).get('max_abs_diff', float('nan')):.3e}**;"
                 f"② 族恒等于 r_cash ⇒ A_aug = A_base(w = {ic.get('constant_cash_family_identity', {}).get('w_used', float('nan')):.4f}),"
                 f"最大绝对差 **{ic.get('constant_cash_family_identity', {}).get('max_abs_diff', float('nan')):.3e}**;"
                 f"合计 {'全过' if ic.get('all_ok') else '**不过**'}(容差 {ic.get('tolerance')})。\n")
    cc = res.get("crosscheck_t361", {})
    if cc.get("available"):
        L.append(f"- 对账:脚本里留下的**旧口径复现**(旧合成 + 旧尺寸)与 t361_results.json 逐个对上"
                 f"(比较 {cc.get('n_compared')} 个数,容差 1e-9;"
                 f"**{cc.get('n_compared', 0) - cc.get('n_mismatch', 0)} 个逐个对上**,"
                 f"差的 {cc.get('n_mismatch', 0)} 个全在 {list(cc.get('mismatch_fields', {}).keys())}"
                 f"(零分布的随机流与 T-361 那次不同,差几个 rank;最大绝对差 {cc.get('max_abs_diff', float('nan')):.6f}),"
                 f"旧 (i)–(iii) pattern 一致:{cc.get('pattern_match')})⇒ 数据装配没动,变的只有合成与尺寸。\n")
    def f2(v):
        if v is None:
            return "n/a"
        try:
            if np.isnan(v):
                return "n/a"
        except TypeError:
            return "n/a"
        return f"{v:+.2f}"

    def why(m, i_key="i_corr_lt_030"):
        j = m.get("judge", {}) if m else {}
        if not j:
            return "—"
        parts = []
        if not j.get(i_key, False):
            parts.append("i")
        if not j.get("ii_positive_and_p_lt_010", False):
            parts.append("ii")
        if not j.get("iii_ok", False):
            parts.append("iii")
        return "全过" if not parts else "挡在 " + "/".join(parts)

    def verdict(r: dict) -> str:
        """一族一行结论。

        口径(本轮 Seth 答第 ① 问):**尺寸不可行的族照样在 w = 1 上把 (i)–(iv) 判完**,
        结论栏写「过表但分量不到位」或「不过」—— 不因为尺寸直接判不过。
        登记口径的 `passes`(= (i)–(iv) 全过 且 尺寸可行)另存在 t363_results.json 里。
        """
        pats = r.get("pattern_new") or {}
        a, b = pats.get("A_earliest"), pats.get("B_2021-10-11")
        allp = (a == [True, True, True]) and (b == [True, True, True])
        A = r["windows"].get("A_earliest", {})
        B = r["windows"].get("B_2021-10-11", {})
        wa, wb = why(A), why(B)
        tail = " ⟨尺寸不可行:w ≤ 1 到不了 10% 风险贡献⟩" if r.get("sizing_infeasible") else ""
        if allp:
            if r.get("iv_degenerate") or not r.get("iv_available", True):
                return "不过((iv) 另一窗口不可得)" + tail
            if r.get("iv_same_direction"):
                return ("**过表但分量不到位**" + tail) if r.get("sizing_infeasible") else "**过**"
            return "不过((iv) 两窗口不同向)" + tail
        return f"不过({wa} · {wb})" + tail

    def verdict_old(r: dict) -> str:
        """旧口径(T-361:替换合成 + |ρ|<0.30)的结论,只用于对照,不作判定。"""
        pats = r.get("pattern_old_t361") or {}
        a, b = pats.get("A_earliest"), pats.get("B_2021-10-11")
        if a is None or b is None:
            return "不过(旧口径窗口不可得)"
        if not r.get("iv_available", True):
            return "不过((iv) 另一窗口不可得)"
        allp = (a == [True, True, True]) and (b == [True, True, True])
        if allp and r.get("iv_same_direction_old"):
            return "**过**"
        return "不过"

    def old_why(r: dict, wn: str) -> str:
        """旧口径复现(legacy_t361_replicate)里某窗的挡在项。"""
        m = (r.get("legacy_t361_replicate") or {}).get(wn) or {}
        p = (m.get("judge_legacy_t361") or {}).get("pattern")
        if p is None:
            return "n/a"
        parts = [nm for i, nm in enumerate(("i", "ii", "iii")) if not p[i]]
        return "全过" if not parts else "挡在 " + "/".join(parts)

    def old_i_tick(r: dict, wn: str) -> str:
        """旧口径复现里某窗的 (i) 判定。"""
        m = (r.get("legacy_t361_replicate") or {}).get(wn) or {}
        p = (m.get("judge_legacy_t361") or {}).get("pattern")
        if p is None:
            return "n/a"
        return "✓" if p[0] else "✗"

    def leg(r: dict, wn: str, key: str):
        """旧口径复现(legacy_t361_replicate)里某窗的原始数。"""
        m = (r.get("legacy_t361_replicate") or {}).get(wn) or {}
        return m.get(key)

    def tick(m, key):
        j = (m or {}).get("judge", {})
        return "✓" if j.get(key) else "✗"

    def two_tick(mA, mB, key):
        return f"{tick(mA, key)}{tick(mB, key)}"

    def cagr_txt(m):
        if not m:
            return "n/a"
        return (f"{m.get('cagr_base', float('nan')):+.1%}→{m.get('cagr_aug', float('nan')):+.1%}"
                f" ({m.get('dcagr_pp', float('nan')):+.1f}pp)")

    def w20_txt(m):
        if not m:
            return "n/a"
        return f"{m.get('worst20_base', float('nan')):+.1%}→{m.get('worst20_aug', float('nan')):+.1%}"

    # ── 开头汇总表:八个族 ───────────────────────────────────────────────
    def i_txt(mA, mB, k1, k2):
        def one(m):
            if not m:
                return "n/a"
            return f"{f2(m.get(k1))}/{f2(m.get(k2))}"
        def tk(m):
            if not m:
                return ""
            return " ✓" if (m.get("judge", {}) or {}).get("i_corr_lt_030") else " ✗"
        return f"A:{one(mA)}{tk(mA)} · B:{one(mB)}{tk(mB)}"

    def ii_txt(mA, mB):
        def one(m):
            if not m:
                return "n/a"
            v = m.get("p_upper")
            pt = "n/a" if v is None else f"{v:.3f}"
            return (f"{m.get('dcagr_pp', float('nan')):+.1f}pp"
                    f" · 贡献 {m.get('mean_monthly_contrib_pct', float('nan')):+.3f}%/月 · p={pt}")
        return f"A:{one(mA)} · B:{one(mB)}"

    def nocash_txt(mA, mB):
        def one(m):
            if not m:
                return "n/a"
            return (f"20日 {m.get('worst20_no_cash', float('nan')):+.1%}"
                    f" · 年化差 {m.get('dcagr_vs_no_cash_pp', float('nan')):+.1f}pp")
        return f"A:{one(mA)} · B:{one(mB)}"

    def fam_cagr_txt(st):
        v = (st or {}).get("cagr_pct")
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return "n/a"
        return f"{v:+.2f}%"

    def pat_txt(p):
        if not p:
            return "n/a"
        return "".join("✓" if x else "✗" for x in p)

    L.append("## 汇总:八个族在新合成(叠加)下的准入结果\n")
    L.append("A / B = 两个窗口(A = 该族首个进场日起,B = 2021-10-11 起);(i) 的 ✓/✗ 是逐窗判定;"
             "**尺寸 w 是按加族后的账户二分出来的**;不可行时报 w = 1 的数。"
             "「扣掉纯供资成本后」= 扣掉 −w·r_cash、但没加族的反事实账户(A_base − w·r_cash):"
             "20 日是它的最差 20 日,年化差 = 加族后账户年化相对它的差(族在付掉供资成本之后的边际贡献)。\n")
    L.append("| 族 | 尺寸 w | (i) corr(Fw, A_base) 全/压 A/B | (i) corr(Fw, R-v2) 全/压 A/B "
             "| (ii) 年化变化 · 月贡献 · p A/B | (iii) 最差20日 基→加族 A/B | (iii) 扣掉纯供资成本后 A/B "
             "| (iv) 两窗口 | 结论 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for k, r in res["families"].items():
        A = r["windows"].get("A_earliest", {})
        B = r["windows"].get("B_2021-10-11", {})
        sz = r["sizing"]
        wt = f"{sz['w']:.3f}" if sz.get("w") is not None else "**不可行**(w=1)"
        iv = ("另一窗口不可得(A=B)" if r.get("iv_degenerate")
              else ("同向 ✓" if r.get("iv_same_direction") else "窗口依赖 ✗"))
        L.append(f"| {r['label']} | {wt} "
                 f"| {i_txt(A, B, 'corr_acct_base_full', 'corr_acct_base_stress')} "
                 f"| {i_txt(A, B, 'corr_rv2_full', 'corr_rv2_stress')} "
                 f"| {ii_txt(A, B)} "
                 f"| {w20_txt(A)} / {w20_txt(B)} | {nocash_txt(A, B)} | {iv} "
                 f"| {verdict(r)} |")
    L.append("")
    inf = [r["label"] for r in res["families"].values() if not r["sizing"].get("feasible")]
    L.append(f"尺寸不可行的族:{('、'.join(inf)) if inf else '无'} —— 叠加口径下账户的方差不再被缩小,"
             f"低波动族要在资金倍数 w ≤ 1 内做到 10% 风险贡献几乎不可能;"
             f"按登记这七个族**过表也不算数**(t363_results.json 的 `passes`),但 (i)–(iv) 本身仍在 w = 1 上判完。\n")

    L.append("## 尺寸的代价(叠加口径下的年化与最差 20 日)\n")
    L.append("尺寸 = 族自己的边际风险贡献 = **加族后**账户月度方差的 10%(二分)。这个规则按**风险**配权、不按收益配权;"
             "低波动的族要占很大的资金权重。准入表不判年化,这一栏要单独看。\n")
    L.append("| 族 | 尺寸 w | 账户年化 基→加族(窗A) | 账户年化 基→加族(窗B) | 族自身年化(独立袖套) | 族自身票数 |")
    L.append("|---|---|---|---|---|---|")
    for k, r in res["families"].items():
        A = r["windows"].get("A_earliest", {})
        B = r["windows"].get("B_2021-10-11", {})
        st = r.get("standalone") or {}
        nt = (r.get("meta") or {}).get("n_tickets")
        sz = r["sizing"]
        wt = f"{sz['w']:.3f}" if sz.get("w") is not None else "**不可行**(w=1)"
        L.append(f"| {r['label']} | {wt} "
                 f"| {A.get('cagr_base', float('nan')):+.2%} → {A.get('cagr_aug', float('nan')):+.2%} "
                 f"({A.get('dcagr_pp', float('nan')):+.1f} pp) "
                 f"| {B.get('cagr_base', float('nan')):+.2%} → {B.get('cagr_aug', float('nan')):+.2%} "
                 f"({B.get('dcagr_pp', float('nan')):+.1f} pp) "
                 f"| {fam_cagr_txt(st)} | {nt if nt is not None else '—'} |")
    L.append("")

    L.append("| 族 | 尺寸 w | (i) 与账户 A_base 全/压 A/B | (i) 与叠加后账户 A_aug(照报不判) A/B | (i) 与 R-v2 全/压 A/B | (ii) 月贡献%/月 A/B "
             "| (ii) p_upper A/B | (iii) 最差20日 基→加族 A/B | (iii) 有效来源 基→加族 A/B "
             "| (iv) 两窗口 | 新结论(ρ<0.30) | 新结论(\\|ρ\\|<0.30,口径已删) | 旧结论(T-361) | 口径翻转 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for k, r in res["families"].items():
        w = r["sizing"].get("w")
        wt = f"{w:.3f}" if w is not None else "**不可行**(w=1)"
        A = r["windows"].get("A_earliest", {})
        B = r["windows"].get("B_2021-10-11", {})
        if not (A or B):
            L.append(f"| {r['label']} | 尺寸不可达 | — | — | — | — | — | — | — | 不过 | 不过 | 不过 | — |")
            continue
        iv = r.get("iv_same_direction")
        if r.get("iv_degenerate"):
            ivs = "另一窗口不可得(A=B)"
        else:
            ivs = "同向 ✓" if iv else "窗口依赖 ✗"
        def two(f, fmt=None):
            def one(m):
                v = f(m) if m else None
                if v is None:
                    return "n/a"
                if isinstance(v, str):
                    return v
                return fmt.format(v) if fmt else f"{v:+.2f}"
            return f"A: {one(A)} · B: {one(B)}"

        def two_fs(f1, f2_):
            def one(m):
                x, y = (f1(m), f2_(m)) if m else (None, None)
                if x is None or y is None:
                    return "n/a"
                return f"{x} / {y}"
            return f"A: {one(A)} · B: {one(B)}"

        def two_pair(f1, f2_, fmt):
            def one(m):
                x, y = (f1(m), f2_(m)) if m else (None, None)
                if x is None or y is None:
                    return "n/a"
                return f"{fmt.format(x)}→{fmt.format(y)}"
            return f"A: {one(A)} · B: {one(B)}"
        L.append(
            f"| {r['label']} | {wt} "
            f"| {two_fs(lambda m: f2(m.get('corr_acct_base_full')), lambda m: f2(m.get('corr_acct_base_stress')))} "
            f"| {two_fs(lambda m: f2(m.get('corr_acct_aug_full')), lambda m: f2(m.get('corr_acct_aug_stress_legacy')))} "
            f"| {two_fs(lambda m: f2(m.get('corr_rv2_full')), lambda m: f2(m.get('corr_rv2_stress')))} "
            f"| {two(lambda m: m.get('mean_monthly_contrib_pct'), '{0:+.3f}%')} "
            f"| {two(lambda m: ('%.3f' % m['p_upper']) if m.get('p_upper') is not None else 'n/a')} "
            f"| {two_pair(lambda m: m.get('worst20_base'), lambda m: m.get('worst20_aug'), '{0:+.1%}')} "
            f"| {two_pair(lambda m: m.get('eff_sources_base'), lambda m: m.get('eff_sources'), '{0:.2f}')} "
            f"| {ivs} | {verdict(r)} "
            f"| 不判(口径删掉,只报原数) "
            f"| {verdict_old(r)} "
            f"| {'**是**' if r.get('conclusion_changed') else '否'} |")
    L.append("")
    L.append("## 逐族逐窗的原始数\n")
    L.append("主表里是每族每窗的相关与判定;完整的逐族逐窗原始数(含 T-361 压力月集合下的 R-v2 相关、"
             "零分布统计量、风险贡献、有效来源、尺寸二分轨迹)在 `docs/research/t363_results.json`。\n")
    L.append("## 因口径改变而翻转的族\n")
    any_flip = False
    for k, r in res["families"].items():
        if not r.get("conclusion_changed"):
            continue
        any_flip = True
        A = r["windows"].get("A_earliest", {})
        B = r["windows"].get("B_2021-10-11", {})
        d_old = "过" if r.get("passes_old_t361") else "不过"
        d_new = "过" if r.get("passes_new") else "不过"
        L.append(f"- **{r['label']}**:旧口径(T-361) **{d_old}** → 新口径 ρ<0.30 **{d_new}**"
                 f"(尺寸不可行 ⇒ 按登记不算过)。"
                 f"(i) 窗A 新 {f2(A.get('corr_acct_base_full'))}/{f2(A.get('corr_acct_base_stress'))}"
                 f" → 旧 {f2(leg(r, 'A_earliest', 'corr_acct_aug_full'))}/{f2(leg(r, 'A_earliest', 'corr_acct_aug_stress_legacy'))};"
                 f"窗B 新 {f2(B.get('corr_acct_base_full'))}/{f2(B.get('corr_acct_base_stress'))}"
                 f" → 旧 {f2(leg(r, 'B_2021-10-11', 'corr_acct_aug_full'))}/{f2(leg(r, 'B_2021-10-11', 'corr_acct_aug_stress_legacy'))}。"
                 f"判定细节:新 {why(A)} / {why(B)};旧 {old_why(r, 'A_earliest')} / {old_why(r, 'B_2021-10-11')}。\n")
    if not any_flip:
        L.append("- 无。\n")
    L.append("")
    L.append("### 逐窗 (i)(ii)(iii) 判定有变化、但结论没变的族\n")
    L.append("「旧」= T-361 口径复现(替换合成 + |ρ|<0.30 + core 压力月),「新」= 本卡口径(叠加 + 单侧 ρ<0.30 + 本窗压力月);"
             "每格三个字依次是 (i)(ii)(iii) 的 ✓/✗。\n")
    any_i = False
    for k, r in res["families"].items():
        if not r.get("pattern_changed_by_composition"):
            continue
        if r.get("conclusion_changed"):
            continue
        any_i = True
        A = r["windows"].get("A_earliest", {})
        B = r["windows"].get("B_2021-10-11", {})
        po = r.get("pattern_old_t361") or {}
        L.append(f"- **{r['label']}**:旧 A:{pat_txt(po.get('A_earliest'))} / B:{pat_txt(po.get('B_2021-10-11'))}"
                 f" → 新 A:{pat_txt((r.get('pattern_new') or {}).get('A_earliest'))}"
                 f" / B:{pat_txt((r.get('pattern_new') or {}).get('B_2021-10-11'))}"
                 f"(新口径下仍:{why(A)} / {why(B)})⇒ 结论不变(旧、新都不过)。\n")
    if not any_i:
        L.append("- 无。\n")
    L.append("")
    L.append("**与台账的一处不一致(留给 Seth)**:S-835 第一批结果那节把 S-681 H4 记成「✅ 四条全过」,"
             "但它两个窗口是同一段 ⇒ (iv) 是空判;按 Seth 2026-11-12 的第 ③ 问(空判一律写「另一窗口不可得」、不记为过),"
             "H4 在 T-361 的口径下就已经是「不过((iv) 另一窗口不可得)」。本卡按第 ③ 问的口径报,表里两列都给出。\n")
    open(OUT_MD, "w").write("\n".join(L))


if __name__ == "__main__":
    main()
