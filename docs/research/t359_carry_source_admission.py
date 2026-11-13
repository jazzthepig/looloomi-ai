#!/usr/bin/env python3
"""T-359(S-835):资金费套息当成一个**独立来源**,按准入标准 (i)–(iv) 判 —— 不是当现金腿判。

判据原文(REFUTATION_LEDGER `## S-835`,2026-11-12)+ 台账「更正二 / 更正三」(2026-11-12/13):
  (i) 与账户、与 R-v2 叠加的月度相关,全样本与压力月都 < 0.30;
      **更正二**:「与账户相关」= 候选月贡献 vs **不带候选的账户**月收益 A_base(压力月按 A_base 定);
      叠加后的相关另列一栏、不判。**更正三**:0.30 是单侧 ρ < 0.30(只挡集中,负相关是分散)。
  (ii) 它自己的贡献为正,且零分布下 `p_upper` < 0.10,或已有 ≥ 60 天为正的前向记录(本轮:不可得);
      **统计量(更正)**: 候选日收益循环平移后叠到账户上的账户年化 − 不带候选的账户年化(block 1,200 次)。
  (iii) 加进去之后账户最差 20 日不变差、有效来源数上升;
  (iv) 两个窗口(候选数据能到的最早日期起 / 2021-10-11 起)结论同向。

合成(**更正三**):加候选后的账户 = A_base + w·候选 − w·r_cash(现金供资,付掉那份现金利息;
  r_cash = S-834 账户的现金腿 C['cash']);w 二分到候选自己的风险贡献 = 10%,
  w > 1 ⇒「尺寸不可行」并同时报 w = 1 时的数。

账户装配:照抄 `docs/research/s834_diversification_audit.py`(RBv2 + 现金 + R-v2 叠加,
R-v2 用 `docs/research/t352_engine.py` 的 `simulate(fix=True)`,名额 10 / 名义上限 0.80 / 每票风险 0.75%),
日历日序列按 `flex_alloc._between` 进共同日。先对上账:年化 +35.7%、R-v2 风险占比 0.742。

套息臂:生产核 `src/data/signals/carry_hl.py` 的 `carry_b_top_rc`(S-748 真实成本 15.5bp/次),
费率来自 Mac 数据根小时档(HL 已实现)+ Supabase `hl_funding_daily` 视图补尾;日收益逐日记账。

只读、不入库。产物:`docs/research/t359_results.json`。
用法(仓库根):python3 docs/research/t359_carry_source_admission.py
"""
from __future__ import annotations

import csv
import datetime as dt
import importlib.util
import json
import os
import sys
import urllib.parse
import urllib.request
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))
os.chdir(REPO)

MAC = Path("/Volumes/CometCloudAI/cometcloud-local")
DATA_ROOT = MAC / "_data" / "hyperliquid_funding"

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_KEY", "")
if not URL or not KEY:
    raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY,退出(只读研究库)")
HDR = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Prefer": "count=exact"}

# ── S-835 判据线(Seth 定的,Jazz 可改) ───────────────────────────────────────
CORR_MAX = 0.30
RC_TARGET = 0.10
P_MAX = 0.10
NULL_N = 200
NULL_SEED = 20261113

CARRY_INCEPTION = dt.date(2023, 6, 12)     # carry_b_top_rc 起点(第一个满 30 天排名的周一)
ACCT_START = pd.Timestamp("2021-10-11")     # 账户起点(S-831 / S-834 同)
F_RISK, CAP_FRAC, CAP_N = 0.0075, 0.80, 10  # S-831 真钱现配置


# ══════════════════════════════════════════════════════════════════ 取数(只读)
def sb_get(table: str, params: dict):
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{URL}/rest/v1/{table}?{q}", headers=HDR)
    with urllib.request.urlopen(req, timeout=120) as r:
        body = r.read().decode()
        rng = r.headers.get("Content-Range", "") or ""
    total = None
    if "/" in rng:
        tail = rng.split("/")[-1].strip()
        if tail.isdigit():
            total = int(tail)
    return (json.loads(body) if body else []), total


def sb_paged(table: str, params: dict, page: int = 1000, max_pages: int = 400):
    out, tot = [], None
    for i in range(max_pages):
        p = dict(params)
        p["limit"] = str(page)
        p["offset"] = str(i * page)
        rows, t = sb_get(table, p)
        if i == 0:
            tot = t
        out += rows
        if len(rows) < page:
            break
    return out, tot


def load_hourly(names: tuple[str, ...]) -> list[dict]:
    """Mac 小时档(HL 已实现)→ [{coin, d, rate_sum, n_hours}]。"""
    out = []
    for n in names:
        p = DATA_ROOT / f"{n.lower()}_funding_1h.csv"
        if not p.exists():
            continue
        buckets: dict[str, list[float]] = {}
        with open(p, newline="") as f:
            rd = csv.reader(f)
            next(rd)
            for row in rd:
                if not row or not row[0]:
                    continue
                d = dt.datetime.fromtimestamp(int(row[0]) / 1000, dt.timezone.utc).date().isoformat()
                buckets.setdefault(d, []).append(float(row[1]))
        for d, vals in buckets.items():
            out.append({"coin": n, "d": d, "rate_sum": sum(vals), "n_hours": len(vals)})
    return out


def load_sb_daily(names: tuple[str, ...], d0: str, d1: str):
    """Supabase hl_funding_daily(同一口径的日聚合)→ [{coin, d, rate_sum, n_hours}]。"""
    params = {"select": "coin,d,rate_sum,n_hours",
              "coin": "in.(" + ",".join(names) + ")",
              "d": f"gte.{d0}", "order": "coin.asc,d.asc"}
    rows, tot = sb_paged("hl_funding_daily", params)
    keep = []
    for r in rows:
        d = str(r["d"])[:10]
        if d <= d1:
            keep.append({"coin": r["coin"], "d": d, "rate_sum": float(r["rate_sum"]),
                         "n_hours": int(r["n_hours"])})
    return keep, tot


def load_lend(d0: str, d1: str) -> dict[str, float]:
    """feature_matrix_daily.f->>'stable_lend_apy_7d'(%/yr)—— 借贷基准。"""
    rows, _ = sb_paged("feature_matrix_daily", {"select": "d,f", "d": f"gte.{d0}", "order": "d.asc"})
    apy = {}
    for r in rows:
        d = str(r["d"])[:10]
        if d > d1:
            continue
        v = (r.get("f") or {}).get("stable_lend_apy_7d")
        if v is not None:
            apy[d] = float(v)
    return apy


def load_forward_record(arm: str = "carry_b_top_rc"):
    """前向纸面记录(carry_hl_daily)—— 判据 (ii) 的第二条路。"""
    try:
        rows, tot = sb_paged("carry_hl_daily", {"select": "d,ret,nav,n_on", "arm": f"eq.{arm}",
                                                "order": "d.asc"})
    except Exception as e:                                    # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    if not rows:
        return {"rows": 0, "count_exact": tot, "note": "表里没有这个臂的行"}
    pos = sum(1 for r in rows if float(r.get("ret") or 0) > 0)
    return {"rows": len(rows), "count_exact": tot, "positive_days": pos,
            "first": str(rows[0]["d"])[:10], "last": str(rows[-1]["d"])[:10],
            "nav_last": rows[-1].get("nav"),
            "note": "前向记录天数(判据 (ii) 的第二条路要 ≥60 天为正)"}


# ══════════════════════════════════════════════════════════════════ ① 账户装配
print("[1/6] 装配账户(照抄 s834_diversification_audit.py)…", flush=True)
import t310_slots as T310                                    # noqa: E402
from src.data.universe import flex_alloc as fa               # noqa: E402
from src.data.signals import carry_hl as CH                  # noqa: E402
from src.data.evaluation import apparatus as AP              # noqa: E402

T310.UM = str(MAC / "research" / "s681" / "_um_daily.jsonl")
T310.STYLE = str(MAC / "research" / "t156" / "_style.json")
sp = importlib.util.spec_from_file_location("t352_engine", HERE / "t352_engine.py")
E1 = importlib.util.module_from_spec(sp)
sp.loader.exec_module(E1)

d = pd.read_csv(HERE / "t342_daily.csv", parse_dates=["date"]).set_index("date")
legs_px = {"crypto": d.crypto_leg_nav_x1v, "equity": d.equity_close_acwi, "gold": d.gold_close_xauusd}
cal = pd.date_range(d.index[0], d.index[-1], freq="D")
cash_rate = d.cash_daily_rate.reindex(cal).ffill().fillna(0.0)
raw, _ = T310.load_tickets()
bars = T310.load_bars({t["symbol"] for t in raw})
exits, _ = T310.classify_exits(raw, bars)
TK = T310.to_engine_tickets(raw, exits)
gate_d, _, _ = T310.load_gate()
res = E1.simulate(TK, bars, gate_d, CAP_FRAC, equity0=630.0, risk_frac=F_RISK, cap_n=CAP_N, fix=True)
rv2 = pd.Series({pd.Timestamp(r[0]): float(r[1]) for r in res["curve"]}).sort_index().pct_change().dropna()

df = pd.concat(legs_px, axis=1).dropna().sort_index()
rets = df.pct_change()
idx = [x for x in df.index if x >= ACCT_START]
tgt = pd.Series(fa.rb_weights(rets.loc[:idx[0]].iloc[1:])).reindex(list(fa.LEGS)).fillna(0.0)
hold = tgt.copy()
rows, nav = [], 1.0
between = fa._between
for i, day in enumerate(idx[1:], start=1):
    row = rets.loc[day, list(fa.LEGS)]
    prev = idx[i - 1]
    c = {k: float(hold[k] * row[k]) for k in fa.LEGS}
    c["cash"] = (1.0 - float(hold.sum())) * between(cash_rate, prev, day)
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
    rows.append({"d": day, **c, "acct": g + c.get("cost", 0.0), "nav": nav})
C = pd.DataFrame(rows).set_index("d").fillna(0.0)
SRC = ["crypto", "equity", "gold", "rv2", "cash"]
core = d.core_nav_1_cap_pit24.reindex(C.index).pct_change().fillna(0.0)

M = lambda x: (1 + x).resample("M").prod() - 1        # 月度复利
MS = lambda x: x.resample("M").sum()                 # 月度求和(分项贡献口径,同 s834)
Cm0 = pd.DataFrame({k: MS(C[k]) for k in SRC})
Am0 = M(C["acct"])
Km = M(core)
rc0 = {k: float(np.cov(Cm0[k], Am0)[0, 1] / Am0.var()) for k in SRC}
ent = lambda w: float(np.exp(-sum(x * np.log(x) for x in (np.clip(list(w.values()), 1e-9, None)
                                                          / np.clip(list(w.values()), 1e-9, None).sum()))))
acct_cagr = float(C["nav"].iloc[-1] ** (365.25 / (idx[-1] - idx[0]).days) - 1)
recon = {"acct_cagr_pct": round(acct_cagr * 100, 2), "acct_cagr_target_pct": 35.7,
         "rv2_risk_share": round(rc0["rv2"], 3), "rv2_risk_share_target": 0.742,
         "eff_sources": round(ent(rc0), 2), "vol_ann_monthly_pct": round(float(Am0.std() * np.sqrt(12)) * 100, 1),
         "window": [str(idx[0].date()), str(idx[-1].date())], "months": int(len(Am0)),
         "ok": bool(abs(acct_cagr * 100 - 35.7) <= 1.0 and abs(rc0["rv2"] - 0.742) <= 0.02)}
print(f"      对账:年化 {acct_cagr*100:.1f}%(目标 35.7)· R-v2 风险占比 {rc0['rv2']:.3f}(目标 0.742)"
      f"· 有效来源 {ent(rc0):.1f}", flush=True)

# ══════════════════════════════════════════════════════════════════ ② 套息臂
print("[2/6] 重出套息日收益序列(carry_hl 生产核 carry_b_top_rc)…", flush=True)
from src.research.strategies.causal_positioning import DEFAULT_UNIVERSE   # noqa: E402

names = tuple(sorted({n for n in DEFAULT_UNIVERSE if (DATA_ROOT / f"{n.lower()}_funding_1h.csv").exists()}))
ACCT_END = idx[-1].date()
hourly = load_hourly(names)
sb_rows, sb_tot = load_sb_daily(names, "2023-05-12", ACCT_END.isoformat())
# 口径核对:视图与小时档在同一段上是否一致(一致才敢用视图补尾)
hv = {(r["coin"], r["d"]): (r["rate_sum"], r["n_hours"]) for r in hourly}
sv = {(r["coin"], r["d"]): (r["rate_sum"], r["n_hours"]) for r in sb_rows}
common = sorted(set(hv) & set(sv))
maxdiff = max((abs(hv[k][0] - sv[k][0]) for k in common), default=None)
maxdiff_h = max((abs(hv[k][1] - sv[k][1]) for k in common), default=None)
merged = dict(hv)
for k, v in sv.items():
    merged.setdefault(k, v)          # 小时档优先,视图补尾
rows_m = [{"coin": c, "d": dd, "rate_sum": v[0], "n_hours": v[1]} for (c, dd), v in merged.items()]
d0 = dt.date(2023, 5, 12)
days_c, F = CH.matrix(rows_m, names, d0, ACCT_END)
path = CH.path(days_c, F, "carry_b_top_rc", inception=CARRY_INCEPTION, cost=CH.COST_REAL)
carry_s = pd.Series({r["d"]: float(r["ret"]) for r in path}).sort_index()
carry_s.index = pd.to_datetime(carry_s.index)
carry_s = carry_s[carry_s.index <= pd.Timestamp(ACCT_END)]
carry_on = carry_s[carry_s != 0.0]
print(f"      宇宙 {len(names)} 名 · 费率源:小时档 {len(hourly)} 行 + 视图 {len(sb_rows)} 行"
      f" · 口径核对(重叠 {len(common)} 格):费率最大差 {maxdiff} / 小时数最大差 {maxdiff_h}", flush=True)
print(f"      套息臂:起点 {carry_s.index[0].date()} → 末 {carry_s.index[-1].date()}"
      f" · 有收益的日子 {len(carry_on)} · 末日 {carry_s.index[-1].date()}", flush=True)

carry = carry_s.reindex(C.index).fillna(0.0)          # 账户日历上的套息日收益
carry_apy = carry.loc[carry.index >= pd.Timestamp(CARRY_INCEPTION)]

# ══════════════════════════════════════════════════════════════════ ③ 窗口与尺寸
print("[3/6] 定尺寸(自己的风险贡献 = 10%,二分)…", flush=True)
WINDOWS = {"A_candidate_start": (pd.Timestamp(CARRY_INCEPTION), pd.Timestamp(ACCT_END)),
           "B_account_start": (ACCT_START, pd.Timestamp(ACCT_END))}


# 台账「S-835 更正三」:加候选后的账户 = A_base + w·候选 − w·r_cash(现金供资,付掉那份现金利息)
CASH = C["cash"].astype(float)            # S-834 账户的现金腿(日贡献)


def compose(base: pd.Series, cand: pd.Series, cash: pd.Series, w: float) -> pd.Series:
    """加候选后的账户 = A_base + w·候选 − w·r_cash(台账「更正三」的式子)。"""
    return base + w * cand - w * cash


def ann(daily: pd.Series) -> float:
    """日序列的年化(几何,365.25 天)。"""
    days = max(1, (daily.index[-1] - daily.index[0]).days)
    return float((1 + daily).prod() ** (365.25 / days) - 1)


def rc_curve(w: float, acct_daily: pd.Series, carry_daily: pd.Series, cash_daily: pd.Series, mask: pd.Series):
    """给定缩放 w:返回 (候选自己的风险贡献, 叠加后账户月收益, 候选月贡献, 叠加后账户日收益)。"""
    dd = compose(acct_daily, carry_daily, cash_daily, w)[mask]
    am = M(dd)
    cm = MS(carry_daily[mask]) * w
    rc = float(np.cov(cm, am)[0, 1] / am.var())
    return rc, am, cm, dd


def size_carry(acct_daily: pd.Series, carry_daily: pd.Series, cash_daily: pd.Series, mask: pd.Series):
    """二分到候选自己的风险贡献 = 10%(对叠加后的账户)。返回 (w, 网格)。"""
    grid = np.concatenate([np.linspace(0, 1, 21), np.linspace(1, 10, 19), np.linspace(10, 200, 20)])
    rcs = [(g, rc_curve(float(g), acct_daily, carry_daily, cash_daily, mask)[0]) for g in grid]
    above = [(g, r) for g, r in rcs if r >= RC_TARGET]
    if not above:
        return None, rcs
    lo = 0.0
    for g, r in rcs:
        if r >= RC_TARGET:
            hi = float(g)
            break
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        r = rc_curve(mid, acct_daily, carry_daily, cash_daily, mask)[0]
        if r >= RC_TARGET:
            hi = mid
        else:
            lo = mid
    return hi, rcs


# ══════════════════════════════════════════════════════════════════ ④ 判据
def worst20(daily: pd.Series):
    r20 = (1 + daily).rolling(20).apply(np.prod) - 1
    e = r20.idxmin()
    s0 = daily.index[max(0, daily.index.get_loc(e) - 19)]
    return s0, e, float(r20.loc[e])


def evaluate(wname: str, w_start, w_end, carry_mask_start=None):
    m = (C.index >= w_start) & (C.index <= w_end)
    base_full, carry_full, cash_full = C["acct"], carry, CASH
    aug_full = compose(base_full, carry_full, cash_full, 1.0)     # 占位,尺寸定完再乘 w
    # 只在套息在场的月份上算(套息没在场的月份它是 0,算进去会稀释/伪相关)
    months_with_carry = MS(carry_full[m]).index[MS(carry_full[m]).abs() > 0]
    res_w = {"window": [str(pd.Timestamp(w_start).date()), str(pd.Timestamp(w_end).date())],
             "carry_active_from": str(pd.Timestamp(carry_mask_start).date()) if carry_mask_start else None}
    # ── 尺寸:在窗口 A 上定档(套息有数据的整个区间),其他窗口用同一档;w > 1 ⇒ 尺寸不可行
    maskA = pd.Series(True, index=C.index) & (C.index >= pd.Timestamp(CARRY_INCEPTION))
    w_req, grid = size_carry(base_full, carry_full, cash_full, maskA)
    res_w["size_grid_sample"] = [[round(float(g), 3), round(float(r), 4)] for g, r in grid[::4]]
    if w_req is None:
        res_w["verdict"] = "不可达:套息的风险贡献在任何缩放下都到不了 10%"
        return res_w
    feasible = bool(w_req <= 1.0)
    w_used = float(w_req) if feasible else 1.0
    aug_full = compose(base_full, carry_full, cash_full, w_used)
    rc_at_req = rc_curve(float(w_req), base_full, carry_full, cash_full, maskA)[0]
    rc_win = rc_curve(w_used, base_full, carry_full, cash_full, m)[0]
    res_w["sizing"] = {
        "w_required": round(float(w_req), 4),
        "rc_carry_at_required": round(rc_at_req, 4),
        "w_used": round(w_used, 4),
        "rc_carry_at_used_in_window": round(rc_win, 4),
        "size_feasible": feasible,
        "note": ("w = 候选日收益在账户上的缩放(= 名义敞口倍数);命中 10% 风险贡献需 w = "
                 f"{float(w_req):.4f} > 1 ⇒ **尺寸不可行**,本轮按 w = 1 报数"
                 if not feasible else
                 "w = 候选日收益在账户上的缩放(= 名义敞口倍数);命中 10% 风险贡献"),
    }
    # ── 账户指标:加之前 / 加之后(A_aug = A_base + w·候选 − w·r_cash)
    def acct_stats(daily):
        am = M(daily)
        return {"cagr_pct": round(ann(daily) * 100, 2),
                "vol_ann_pct": round(float(am.std() * np.sqrt(12)) * 100, 2),
                "worst20_pct": round(worst20(daily)[2] * 100, 2)}
    base_daily = base_full[m]
    new_daily = aug_full[m]
    res_w["account_before"] = acct_stats(base_daily)
    res_w["account_after"] = acct_stats(new_daily)
    s0b, e0b, v0b = worst20(base_daily)
    s0a, e0a, v0a = worst20(new_daily)
    res_w["worst20_before"] = [str(s0b.date()), str(e0b.date()), round(v0b * 100, 2)]
    res_w["worst20_after"] = [str(s0a.date()), str(e0a.date()), round(v0a * 100, 2)]
    # ── 有效来源数(风险贡献熵);A_aug 里现金腿被抽走 w 份 ⇒ 现金贡献变 (1−w)·cash
    def rc_map(daily, w_carry=None):
        cm = pd.DataFrame({k: MS(C[k][m]) for k in SRC})
        if w_carry is not None:
            cm["cash"] = cm["cash"] * (1.0 - w_carry)
        am = M(daily)
        rc = {k: float(np.cov(cm[k], am)[0, 1] / am.var()) for k in SRC}
        return rc, am, cm
    rcb, amb, cmb = rc_map(base_daily)
    rca, ama, cma = rc_map(new_daily, w_used)
    rca["carry"] = float(np.cov(MS(carry_full[m]) * w_used, ama)[0, 1] / ama.var())
    res_w["eff_sources_before"] = round(ent(rcb), 2)
    res_w["eff_sources_after"] = round(ent(rca), 2)
    res_w["rc_before"] = {k: round(v, 3) for k, v in rcb.items()}
    res_w["rc_after"] = {k: round(v, 3) for k, v in rca.items()}
    # ── (i) 相关(台账「S-835 更正二」):候选月贡献 vs **不带候选的账户**月收益 A_base;
    #    压力月按 A_base 定(20 分位);叠加后的相关另列一栏、不判
    _mc = set(pd.PeriodIndex(months_with_carry, freq="M"))
    m2 = pd.Series(m & C.index.to_period("M").isin(_mc), index=C.index)
    am_base = M(base_full[m2])
    am_aug = M(aug_full[m2])
    cmv = MS(carry_full[m2]) * w_used
    stress = am_base <= am_base.quantile(0.2)
    cm_rv2 = MS(C["rv2"][m2])

    def cc(a, b):
        try:
            return round(float(a.corr(b)), 3)
        except Exception:                                     # noqa: BLE001
            return None
    res_w["corr"] = {
        "reading": "corr(w·候选月贡献, A_base 月收益);压力月按 A_base 的 20 分位定",
        "one_sided": "ρ < 0.30(单侧:负相关是分散,只挡集中)",
        "months_used": int(len(am_base)),
        "carry_vs_account_base_full": cc(cmv, am_base),
        "carry_vs_account_base_stress": cc(cmv[stress], am_base[stress]) if stress.sum() > 2 else None,
        "carry_vs_account_overlay_full": cc(cmv, am_aug),
        "carry_vs_account_overlay_stress": cc(cmv[stress], am_aug[stress]) if stress.sum() > 2 else None,
        "carry_vs_rv2_full": cc(cmv, cm_rv2),
        "carry_vs_rv2_stress": cc(cmv[stress], cm_rv2[stress]) if stress.sum() > 2 else None,
        "n_stress_months": int(stress.sum()),
        "overlay_corr_judged": False,
    }
    # ── (ii) 它自己的贡献为正 + 零分布(台账「更正」口径:
    #      统计量 = 套息日收益循环平移后叠到账户上的账户年化 − 不带套息的账户年化)
    cser = carry_full[m2]
    monthly_carry = MS(cser)
    res_w["own_contribution"] = {
        "months_with_carry": int(len(monthly_carry)),
        "mean_monthly_contribution_pct": round(float(monthly_carry.mean() * w_used * 100), 4),
        "total_pct": round(float(cser.sum() * w_used * 100), 2),
        "arith_ann_pct_nominal": round(float(cser.mean() * 365 * 100), 3),
        "arith_ann_pct_capital_x0.75": round(float(cser.mean() * 365 * 100 * 0.75), 3),
        "positive_months": int((monthly_carry * w_used > 0).sum()),
        "note": "w·套息 的月贡献(账户日历口径)",
    }
    # 字面读法(对套息自身序列做循环平移后比它自己的均值)退化:平移不改变序列均值 ⇒ 不作判据
    res_w["null_test_literal_note"] = {
        "stat": "mean_daily_return",
        "note": "循环平移不改变序列均值 ⇒ 零分布退化(apparatus NoOpNull);本轮不作判据",
    }
    # ── 判据用:账户年化差(实际 vs 循环平移后的零分布)
    base_ann = ann(base_daily)
    actual_ann_diff = ann(new_daily) - base_ann
    seg = m & (C.index >= pd.Timestamp(CARRY_INCEPTION))       # 平移段:套息有数据的日历段
    carry_seg = carry_full[seg]

    def stat_fn(rng):
        sh = pd.Series(AP.circular_shift(carry_seg.values, rng, block=1), index=carry_seg.index)
        cand = carry_full.copy()
        cand.loc[seg] = sh
        nd = compose(base_full, cand, cash_full, w_used)[m]
        return float(ann(nd) - base_ann)
    null, p_up = None, None
    try:
        null = AP.null_distribution(stat_fn, NULL_N, NULL_SEED, actual=float(actual_ann_diff))
        p_up = AP.p_upper(float(actual_ann_diff), null)
    except Exception as e:                                    # noqa: BLE001
        res_w.setdefault("null_test_account_ann", {})["error"] = f"{type(e).__name__}: {e}"
    res_w["null_test_account_ann"] = {
        "stat": "套息日收益循环平移后叠到账户上的账户年化 − 不带套息的账户年化",
        "actual_ann_diff_pp": round(float(actual_ann_diff) * 100, 4),
        "base_ann_pct": round(base_ann * 100, 4),
        "aug_ann_pct": round(ann(new_daily) * 100, 4),
        "null_mean_pp": round(float(np.mean(null)) * 100, 4) if null is not None else None,
        "null_sd_pp": round(float(np.std(null)) * 100, 4) if null is not None else None,
        "p_upper": p_up, "n": NULL_N, "seed": NULL_SEED,
        "shift_segment": [str(carry_seg.index[0].date()), str(carry_seg.index[-1].date())] if len(carry_seg) else None,
    }
    # ── 附报(不作判据):自定的「压力月累计收益」统计量
    me = core[m2].resample("M").last()
    me_stress = me[me <= me.quantile(0.2)]
    labels = m2.index.to_period("M").to_timestamp("M")
    sd = pd.Series(labels.isin(me_stress.index), index=m2.index)
    stat_actual = float(cser[sd].sum())

    def stat_fn2(rng):
        sh = pd.Series(AP.circular_shift(cser.values, rng, block=1), index=cser.index)
        return float(sh[sd].sum())
    null2, p2 = None, None
    try:
        null2 = AP.null_distribution(stat_fn2, NULL_N, NULL_SEED, actual=stat_actual)
        p2 = AP.p_upper(stat_actual, null2)
    except Exception as e:                                    # noqa: BLE001
        res_w.setdefault("null_test_stress_month_appendix", {})["error"] = f"{type(e).__name__}: {e}"
    res_w["null_test_stress_month_appendix"] = {
        "stat": "套息在压力月(core 的最差五分之一月)里的累计收益",
        "judged": False,
        "note": "自定统计量,本轮只附报、不作判据(判据用上面的账户年化差)",
        "actual_pct": round(stat_actual * 100, 4),
        "null_mean_pct": round(float(np.mean(null2)) * 100, 4) if null2 is not None else None,
        "null_sd_pct": round(float(np.std(null2)) * 100, 4) if null2 is not None else None,
        "p_upper": p2, "n": NULL_N, "seed": NULL_SEED,
    }
    # ── (iv) 去掉最好一段(只报不判)
    best_span = None
    if len(monthly_carry) >= 12:
        half = 6
        vals = monthly_carry.rolling(half).sum().dropna()
        if len(vals):
            best_span = (str(vals.idxmax().date()), str((vals.idxmax() + pd.offsets.MonthBegin(half)).date()))
    res_w["drop_best_half_year"] = best_span
    if best_span:
        keep = ~((C.index >= pd.Timestamp(best_span[0])) & (C.index <= pd.Timestamp(best_span[1])))
        m3 = m & keep
        rc3, am3, cm3, dd3 = rc_curve(w_used, base_full, carry_full, cash_full, m3)
        c3 = MS(carry_full[m3]) * w_used
        am_base3 = M(base_full[m3])
        core3 = M(core[m3])
        st3 = core3 <= core3.quantile(0.2)
        res_w["without_best_half_year"] = {
            "span": best_span,
            "rc_carry": round(rc3, 4),
            "carry_vs_account_base_full": round(float(c3.corr(am_base3)), 3),
            "carry_vs_account_overlay_full": round(float(c3.corr(am3)), 3),
            "carry_monthly_mean_pct": round(float(MS(carry_full[m3]).mean() * w_used * 100), 4),
            "carry_ann_pct": round(float(MS(carry_full[m3]).mean() * w_used * 12 * 100), 3),
            "n_stress": int(st3.sum()),
        }
    return res_w


results = {"task": "T-359", "ledger": "S-835", "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "criteria_lines": {"corr_max": CORR_MAX, "rc_target": RC_TARGET, "p_max": P_MAX,
                              "corr_reading": "单侧 ρ < 0.30(只挡集中;负相关是分散)",
                              "null": f"apparatus.circular_shift(block=1, n={NULL_N}, seed={NULL_SEED})",
                              "null_stat": "套息日收益循环平移后叠到账户上的账户年化 − 不带套息的账户年化",
                              "ledger_amendments": "S-835 更正二(i 的读法)/ 更正三(合成式 + 单侧线 + 两条自检)"},
           "composition": {
               "formula": "A_aug = A_base + w·候选 − w·r_cash(现金供资,付掉那份现金利息)",
               "r_cash": "S-834 账户的现金腿 C['cash'](日贡献)",
               "reading_i": "corr(w·候选月贡献, A_base 月收益);压力月按 A_base 的 20 分位定;叠加后的相关另列一栏、不判",
               "ledger": "S-835 更正二 / 更正三",
           },
           "reconciliation": recon,
           "carry_arm": {"universe": list(names), "n_names": len(names),
                         "inception": CARRY_INCEPTION.isoformat(),
                         "funding_sources": {"mac_hourly_rows": len(hourly), "sb_view_rows": len(sb_rows),
                                             "sb_view_count_exact": sb_tot},
                         "overlap_check": {"cells": len(common), "max_abs_rate_diff": maxdiff,
                                           "max_abs_hours_diff": maxdiff_h},
                         "last_nonzero_day": str(carry_on.index[-1].date()) if len(carry_on) else None,
                         "days_with_return": int(len(carry_on)),
                         "note": "生产核 carry_hl.path(arm=carry_b_top_rc, cost=COST_REAL=15.5bp/次);不含基差(S-748 量到基差拖累 −0.068pp/yr)"}}

# ── 自检(两条能失败;台账「S-835 更正三」第 2 点)────────────────────────────
def self_check(case: str, cand: pd.Series, w: float):
    aug = compose(C["acct"], cand, CASH, w)
    dmax = float((aug - C["acct"]).abs().max())
    return {"case": case, "w": w, "max_abs_diff_vs_A_base": dmax, "pass": bool(dmax < 1e-12)}


results["self_checks"] = {
    "w0_equals_base": self_check("w = 0 ⇒ A_aug 逐日 = A_base", carry, 0.0),
    "candidate_equals_cash_equals_base": self_check("候选恒等于 r_cash ⇒ A_aug 逐日 = A_base", CASH, 1.0),
    "note": "两条都真跑一遍 compose 再比,不是写死 True;tol = 1e-12",
}

print("[4/6] 判据 (i)–(iv)(窗口 A)…", flush=True)
results["windows"] = {}
results["windows"]["A_candidate_start"] = evaluate("A_candidate_start", *WINDOWS["A_candidate_start"])
print(f"      A:w={results['windows']['A_candidate_start'].get('sizing',{}).get('w_used')} "
      f"RC={results['windows']['A_candidate_start'].get('sizing',{}).get('rc_carry_at_used_in_window')} "
      f"相关={results['windows']['A_candidate_start'].get('corr')}", flush=True)
print("[5/6] 判据 (i)–(iv)(窗口 B)…", flush=True)
results["windows"]["B_account_start"] = evaluate("B_account_start", *WINDOWS["B_account_start"])
print(f"      B:w={results['windows']['B_account_start'].get('sizing',{}).get('w_used')} "
      f"RC={results['windows']['B_account_start'].get('sizing',{}).get('rc_carry_at_used_in_window')} "
      f"相关={results['windows']['B_account_start'].get('corr')}", flush=True)

# ── 附报 ①:套息臂在 R-v2 最差的 20 个交易日(2023-02-08 → 03-08)里的收益
rv2_bad = worst20(C["rv2"])
m20 = (C.index >= rv2_bad[0]) & (C.index <= rv2_bad[1])
overlap20 = (C.index >= pd.Timestamp(CARRY_INCEPTION)) & m20
results["rv2_worst20"] = {
    "span": [str(rv2_bad[0].date()), str(rv2_bad[1].date())],
    "rv2_20d_pct": round(rv2_bad[2] * 100, 2),
    "carry_return_pct_in_span": round(float(carry[m20].sum() * 100), 4),
    "carry_days_with_data_in_span": int((carry[m20] != 0).sum()),
    "note": "R-v2 腿自己最差的 20 个交易日(全账户窗口内)",
}
# 卡上点名的那一段(2023-02-08 → 03-08)单独报:那 20 天里套息臂有没有在跑
_card_named = (C.index >= pd.Timestamp("2023-02-08")) & (C.index <= pd.Timestamp("2023-03-08"))
results["rv2_worst20_card_named_span"] = {
    "span": ["2023-02-08", "2023-03-08"],
    "account_worst20_windowB": results["windows"]["B_account_start"].get("worst20_before"),
    "carry_return_pct_in_span": round(float(carry[_card_named].sum() * 100), 4),
    "carry_days_with_data_in_span": int((carry[_card_named] != 0).sum()),
    "note": "卡上点名的 2023-02-08 → 03-08 是**账户**(窗口 B)最差的 20 日;套息臂 2023-06-12 才起 ⇒ 这 20 天它没在跑(收益 0)",
}
# 套息在场的重叠段里,R-v2 最差的 20 天
m_ov = (C.index >= pd.Timestamp(CARRY_INCEPTION))
rv2_ov = worst20(C["rv2"][m_ov])
m20b = (C.index >= rv2_ov[0]) & (C.index <= rv2_ov[1])
results["rv2_worst20_overlap"] = {
    "span": [str(rv2_ov[0].date()), str(rv2_ov[1].date())],
    "rv2_20d_pct": round(rv2_ov[2] * 100, 2),
    "carry_return_pct_in_span": round(float(carry[m20b].sum() * 100), 4),
    "account_worst20_within_overlap_before": None, "account_worst20_within_overlap_after": None,
}
wA = results["windows"]["A_candidate_start"].get("sizing", {}).get("w_used")
if wA:
    mm = m_ov
    wb = worst20(C["acct"][mm])
    wa = worst20(compose(C["acct"], carry, CASH, wA)[mm])
    results["rv2_worst20_overlap"]["account_worst20_within_overlap_before"] = [str(wb[0].date()), str(wb[1].date()), round(wb[2] * 100, 2)]
    results["rv2_worst20_overlap"]["account_worst20_within_overlap_after"] = [str(wa[0].date()), str(wa[1].date()), round(wa[2] * 100, 2)]

# ── 附报 ②:与借贷利率的差(只报)
apy = load_lend("2023-05-01", ACCT_END.isoformat())
lend_daily = pd.Series({pd.Timestamp(k): v / 100 / 365 for k, v in apy.items()}).sort_index()
INTERVALS = [("2023H2", "2023-07-01", "2023-12-31"), ("2024H1", "2024-01-01", "2024-06-30"),
             ("2024H2", "2024-07-01", "2024-12-31"), ("2025H1", "2025-01-01", "2025-06-30"),
             ("2025H2", "2025-07-01", "2025-12-31"), ("2026H1", "2026-01-01", "2026-06-30"),
             ("2026-07+", "2026-07-01", ACCT_END.isoformat()),
             ("全样本", "2023-06-12", ACCT_END.isoformat())]
spread = []
for lbl, a, b in INTERVALS:
    a, b = pd.Timestamp(a), pd.Timestamp(b)
    cm_ = carry[(carry.index >= a) & (carry.index <= b)]
    lm = lend_daily[(lend_daily.index >= a) & (lend_daily.index <= b)]
    n = max(len(cm_), 1)
    carry_ann_nom = float(cm_.mean() * 365 * 100) if len(cm_) else None
    carry_ann_cap = carry_ann_nom * 0.75 if carry_ann_nom is not None else None
    lend_ann = float(lm.mean() * 365 * 100) if len(lm) else None
    spread.append({"interval": lbl, "carry_ann_nominal_pct": round(carry_ann_nom, 3) if carry_ann_nom is not None else None,
                   "carry_ann_capital_x0.75_pct": round(carry_ann_cap, 3) if carry_ann_cap is not None else None,
                   "lend_ann_pct": round(lend_ann, 3) if lend_ann is not None else None,
                   "diff_cap_minus_lend_pp": round(carry_ann_cap - lend_ann, 3) if (carry_ann_cap is not None and lend_ann is not None) else None,
                   "n_days": n})
results["vs_lending"] = spread

# ── 附报 ③:前向记录(判据 (ii) 的第二条路:≥60 天为正)—— 不可得
results["forward_record"] = load_forward_record()
results["forward_record"]["status"] = "不可得"
results["forward_record"]["status_note"] = ("登记允许「零分布 p_upper < 0.10」或「≥60 天前向记录」二选一;"
                                            "生产臂前向记录不足 60 天 ⇒ 这条路不可得 ⇒ 只按 p_upper 判")

# ── 判定汇总(机器可读)
def verdict(w):
    v = {}
    c = w.get("corr", {})

    def below(x):
        """单侧:ρ < 0.30(负相关是分散,只挡集中)。"""
        return x is not None and float(x) < CORR_MAX
    v["i_corr_ok"] = bool(below(c.get("carry_vs_account_base_full"))
                           and below(c.get("carry_vs_account_base_stress"))
                           and below(c.get("carry_vs_rv2_full"))
                           and below(c.get("carry_vs_rv2_stress")))
    o = w.get("own_contribution", {})
    pos = bool((o.get("mean_monthly_contribution_pct") or 0) > 0)
    nt = w.get("null_test_account_ann", {})
    p = nt.get("p_upper")
    v["ii_positive"] = pos
    v["ii_p_upper"] = p
    v["ii_forward_path"] = "不可得"
    v["ii_ok"] = bool(pos and p is not None and p < P_MAX)
    b4, af = w.get("worst20_before"), w.get("worst20_after")
    v["iii_worst20_not_worse"] = bool(b4 and af and af[2] >= b4[2] - 1e-9)
    v["iii_eff_sources_up"] = bool((w.get("eff_sources_after") or 0) >= (w.get("eff_sources_before") or 0))
    v["iii_ok"] = bool(v["iii_worst20_not_worse"] and v["iii_eff_sources_up"])
    v["size_feasible"] = bool(w.get("sizing", {}).get("size_feasible"))
    v["all_ok"] = bool(v.get("i_corr_ok") and v.get("ii_ok") and v.get("iii_ok") and v.get("size_feasible"))
    return v


results["verdicts"] = {k: verdict(v) for k, v in results["windows"].items()}
a, b = results["verdicts"]["A_candidate_start"], results["verdicts"]["B_account_start"]
same = {kk: bool(a.get(kk) == b.get(kk)) for kk in ("i_corr_ok", "ii_ok", "iii_ok", "all_ok")}
results["window_same_direction"] = {"per_criterion": same, "all_same": all(same.values()),
                                    "note": "(iv) 两个窗口结论同向"}
results["overall"] = {
    "admitted": bool(a.get("all_ok") and b.get("all_ok") and results["window_same_direction"]["all_same"]),
    "summary": ("四条全过且尺寸可行 ⇒ 进前向影子臂" if (a.get("all_ok") and b.get("all_ok"))
                else "有条不过 / 尺寸不可行 ⇒ 不准入"),
    "failures_A": [k for k in ("i_corr_ok", "ii_ok", "iii_ok", "size_feasible") if not a.get(k)],
    "failures_B": [k for k in ("i_corr_ok", "ii_ok", "iii_ok", "size_feasible") if not b.get(k)],
}

out = HERE / "t359_results.json"
json.dump(results, open(out, "w"), indent=1, default=str, ensure_ascii=False)
print("[6/6] 写产物:", out, flush=True)
print(json.dumps({"reconciliation": recon, "verdicts": results["verdicts"],
                  "same": results["window_same_direction"], "overall": results["overall"],
                  "rv2_worst20": results["rv2_worst20"], "forward": results["forward_record"],
                  "vs_lending": spread}, ensure_ascii=False, indent=1)[:4000])
