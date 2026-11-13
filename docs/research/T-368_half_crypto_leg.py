"""T-368(台账 S-845 预注册):加密腿加「半仓」档 —— 周线标志亮而 X1V 在场时加密腿敞口 × 0.5(另一半拿现金),按账户口径判。

登记见 REFUTATION_LEDGER `## S-845`(先登记后算;规则不调参)。只读。用法(仓库根目录):
  SUPABASE_URL=x SUPABASE_KEY=x python3 docs/research/T-368_half_crypto_leg.py docs/research/t342_daily.csv <cometcloud-local/research/>

装配照抄 `docs/research/s843_beta_leg_trend_exit.py` 的 assemble(S-834 账户口径:RBv2 权重、21 日再平衡、腿与现金利息一字不改);
只多一个参数:加密腿的半仓档(标志亮 ⇒ 该腿敞口 × 0.5,另一半拿现金利息)。
BTC 周日收盘取 `ohlcv_daily`(symbol BTC、source binance_hist),落 docs/research/T-368_btc_weekly.json。
"""
from __future__ import annotations

import importlib.util
import json
import os
import pickle
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, "docs/research")
sys.path.insert(0, ".")
from src.data.universe import flex_alloc as fa  # noqa: E402

R = sys.argv[2] if len(sys.argv) > 2 else "/Volumes/CometCloudAI/cometcloud-local/research/"
OUT, WEEKLY_JSON = "docs/research/T-368_results.json", "docs/research/T-368_btc_weekly.json"
SEED, N_NULL, SMA_N, LB_W, SWITCH_COST = 20261113, 200, 10, 4, 20 / 1e4
HALF_START, HALF_END = "2021-10-12", "2024-03-31"      # 判据 (d) 的前半段
HALF_START2, HALF_END2 = "2024-04-01", "2026-10-30"   # 判据 (d) 的后半段
KEY = os.environ["SUPABASE_KEY"]
BASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
HEAD = {"apikey": KEY, "Authorization": "Bearer " + KEY}


# ── BTC 周日收盘(ohlcv_daily / binance_hist)────────────────────────────────
def _get(table: str, params, rng: str = "0-999", extra: dict | None = None):
    url = f"{BASE_URL}/rest/v1/{table}?" + urllib.parse.urlencode(params)
    h = dict(HEAD, Range=rng)
    if extra:
        h.update(extra)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=300) as r:
        body = r.read().decode()
        return (json.loads(body) if body else []), r.headers.get("Content-Range")


def fetch_btc_daily() -> tuple[list[dict], int]:
    params = [("select", "trade_date,close,source"), ("source", "eq.binance_hist"),
              ("symbol", "eq.BTC"), ("order", "trade_date.asc")]
    _, cr = _get("ohlcv_daily", params, "0-0", {"Prefer": "count=exact"})
    total = int(str(cr).split("/")[-1]) if cr and "/" in str(cr) else 0
    rows, off = [], 0
    while off < total:
        page, _ = _get("ohlcv_daily", params, f"{off}-{off + 999}")
        if not page:
            break
        rows.extend(page)
        off += len(page)
    return rows, total


def weekly_closes(rows: list[dict]) -> tuple[pd.Series, dict]:
    """日收盘 → 周(周日结束)收盘。同日多行取最后一条。返回 (周收盘序列, 诊断)。"""
    px: dict[str, float] = {}
    dup = 0
    for r in rows:
        c = r.get("close")
        if c is None:
            continue
        day = str(r.get("trade_date"))[:10]
        if day in px:
            dup += 1
        px[day] = float(c)
    s = pd.Series(px, dtype=float)
    s.index = pd.to_datetime(s.index)
    s = s.sort_index()
    wk_end = s.index + pd.to_timedelta((6 - s.index.dayofweek) % 7, unit="D")
    wk = s.groupby(wk_end).last()
    wk = wk.sort_index()
    diag = {"daily_rows": len(px), "dup_days": dup, "daily_first": str(s.index[0].date()),
            "daily_last": str(s.index[-1].date()), "weeks": len(wk), "week_first": str(wk.index[0].date()),
            "week_last": str(wk.index[-1].date()),
            "weeks_missing_sunday": int(sum(1 for e in wk.index if (e - pd.Timedelta(days=6)) not in set(s.index)))}
    return wk, diag


def flag_series(wk: pd.Series) -> pd.Series:
    """周线标志:该周日收盘 < 10 周均线 且 < 4 周前收盘。只用 ≤ 该周日的数据。"""
    sma = wk.rolling(SMA_N).mean()
    lb = wk.shift(LB_W)
    return ((wk < sma) & (wk < lb)).where(sma.notna() & lb.notna())


def day_flag_map(weeks: list[pd.Timestamp], flags: list[bool]) -> dict[pd.Timestamp, bool]:
    """周日 S 的标志对下一周(周一 S+1 … 周日 S+7)生效;按「最近一个严格早于 d 的周日」取值。"""
    s = np.array([w.value for w in weeks], dtype="int64")
    f = np.array([bool(x) for x in flags], dtype=bool)
    out: dict[pd.Timestamp, bool] = {}
    for d in IDX[1:]:
        i = int(np.searchsorted(s, pd.Timestamp(d).value, side="left")) - 1
        out[pd.Timestamp(d)] = bool(f[i]) if i >= 0 else False
    return out


# ── R-v2 序列(照抄 s843 的缓存逻辑,缓存落在 Mac 数据根)────────────────────
def rv2_series():
    ck = R + "t368_rv2.pkl"
    if os.path.exists(ck):
        return pickle.load(open(ck, "rb"))
    import t310_slots as T310
    T310.UM = R + "s681/_um_daily.jsonl"
    T310.STYLE = R + "t156/_style.json"
    sp = importlib.util.spec_from_file_location("t352_engine", "docs/research/t352_engine.py")
    E1 = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(E1)
    raw, _ = T310.load_tickets()
    bars = T310.load_bars({t["symbol"] for t in raw})
    exits, _ = T310.classify_exits(raw, bars)
    TK = T310.to_engine_tickets(raw, exits)
    gate_d, _, _ = T310.load_gate()
    res = E1.simulate(TK, bars, gate_d, 0.80, equity0=630.0, risk_frac=0.0075, cap_n=10, fix=True)
    s = pd.Series({pd.Timestamp(r[0]): float(r[1]) for r in res["curve"]}).sort_index().pct_change().dropna()
    pickle.dump(s, open(ck, "wb"))
    return s


# ── 输入 ────────────────────────────────────────────────────────────────────
d = pd.read_csv(sys.argv[1], parse_dates=["date"]).set_index("date")
START = pd.Timestamp("2021-10-11")
cal = pd.date_range(d.index[0], d.index[-1], freq="D")
cash_rate = d.cash_daily_rate.reindex(cal).ffill().fillna(0.0)
RV2 = None  # 懒加载(取数 + 引擎重算慢);assemble 之前由 main 填好


def get_rv2():
    global RV2
    if RV2 is None:
        RV2 = rv2_series()
    return RV2


df = pd.concat({"crypto": d.crypto_leg_nav_x1v, "equity": d.equity_close_acwi, "gold": d.gold_close_xauusd}, axis=1).dropna().sort_index()
rets = df.pct_change()
IDX = [x for x in df.index if x >= START]

# X1V 在场 = 加密腿净值当天有变动(腿在空仓期净值走平);核(src/data/signals/tom.py 的 CORE_X1V 规则)只做交叉核对
CRYPTO_NAV = df["crypto"]
IN_MKT = {pd.Timestamp(day): bool(abs(float(CRYPTO_NAV.loc[day] - CRYPTO_NAV.shift(1).loc[day])) > 1e-12)
          for day in IDX[1:]}


def kernel_crosscheck() -> dict:
    try:
        from src.data.signals.tom import trade_path
    except Exception as e:  # pragma: no cover
        return {"error": str(e)}
    core = d.core_nav_1_cap_pit24.astype(float).dropna()
    g = trade_path(core, "rally", 0.0, "l20", True)
    gs = g.shift(1)
    days = [x for x in IDX[1:] if x in gs.index]
    agree = sum(1 for x in days if bool(gs.loc[x] != 0) == IN_MKT.get(x, False))
    warm = [x for x in days if gs.index.get_loc(x) >= 260]
    agree_warm = sum(1 for x in warm if bool(gs.loc[x] != 0) == IN_MKT.get(x, False))
    return {"days": len(days), "agree": agree, "agree_pct": round(agree / max(len(days), 1), 4),
            "warm_days": len(warm), "warm_agree_pct": round(agree_warm / max(len(warm), 1), 4)}


# ── 装配(S-834 口径;只多一个半仓档参数)────────────────────────────────────
def assemble(half: dict[pd.Timestamp, bool] | None = None) -> pd.DataFrame:
    """half[day] = 该日周线标志是否亮;None = 原账户(无规则)。
    加密腿敞口 f:标志亮且 X1V 在场 ⇒ 0.5(另一半拿现金利息);X1V 不在场 ⇒ 0(照旧);标志灭 ⇒ 1。
    换档成本 20bp × 变动的权重,只对「1.0 ⇄ 0.5」的档位变化计(X1V 自身进出的成本已在腿净值里)。"""
    tgt = pd.Series(fa.rb_weights(rets.loc[:IDX[0]].iloc[1:])).reindex(list(fa.LEGS)).fillna(0.0)
    hold = tgt.copy()
    rows, nav = [], 1.0
    f_prev = 1.0
    rv2 = get_rv2()
    for i, day in enumerate(IDX[1:], start=1):
        prev = IDX[i - 1]
        row = rets.loc[day, list(fa.LEGS)].copy()
        cr = fa._between(cash_rate, prev, day)
        sw = 0.0
        if half is not None:
            in_mkt = IN_MKT.get(day, False)
            lit = bool(half.get(day, False))
            f = 0.5 if (lit and in_mkt) else (0.0 if not in_mkt else 1.0)
            if f != f_prev:
                if (f in (0.0, 1.0)) and (f_prev in (0.0, 1.0)):
                    pass                      # X1V 自身进出:腿净值里已付,不重复计
                else:
                    sw += SWITCH_COST * abs(f - f_prev) * float(hold["crypto"])
                f_prev = f
            row["crypto"] = float(row["crypto"]) if f >= 1.0 else (0.5 * float(row["crypto"]) + 0.5 * cr if f > 0 else 0.0)
        c = {k: float(hold[k] * row[k]) for k in fa.LEGS}
        c["cash"] = (1.0 - float(hold.sum())) * cr
        c["rv2"] = fa._between(rv2, prev, day)
        g = sum(c.values())
        nav *= 1 + g
        hold = hold * (1 + row) / (1 + g)
        cost = sw
        if i % 21 == 0:
            new = pd.Series(fa.rb_weights(rets.loc[:day].iloc[1:])).reindex(list(fa.LEGS)).fillna(0.0)
            cost += float((hold - new).abs().sum()) * 20 / 1e4
            hold = new.copy()
        if cost:
            nav *= 1 - cost
            c["cost"] = -cost
        rows.append({"d": day, **c, "acct": g + c.get("cost", 0.0), "nav": nav})
    return pd.DataFrame(rows).set_index("d").fillna(0.0)


def cagr(C, sub=None) -> float:
    if sub is None:
        return float(C["nav"].iloc[-1] ** (365.25 / (C.index[-1] - IDX[0]).days) - 1)
    s = C.loc[sub[0]:sub[1], "acct"]
    if len(s) < 2:
        return float("nan")
    days = (s.index[-1] - s.index[0]).days + 1
    return float((1 + s).prod() ** (365.25 / days) - 1)


def underwater(C):
    nav = pd.concat([pd.Series({IDX[0]: 1.0}), C["nav"]])
    peak = nav.cummax()
    out, start, prev = [], None, None
    for day, v in (nav / peak - 1).items():
        if v < 0 and start is None:
            start = prev
        if v >= 0 and start is not None:
            out.append((str(start.date()), str(day.date()), (day - start).days,
                        round(float((nav.loc[start:day] / peak.loc[start:day] - 1).min()) * 100, 1)))
            start = None
        prev = day
    if start is not None:
        out.append((str(start.date()), "未收回", (nav.index[-1] - start).days,
                    round(float((nav.loc[start:] / peak.loc[start:] - 1).min()) * 100, 1)))
    return sorted(out, key=lambda x: -x[2])


def worst20(C):
    return round(float(((1 + C["acct"]).rolling(20).apply(np.prod, raw=True) - 1).min()) * 100, 2)


def summary(C):
    uw = underwater(C)
    return {"cagr_pct": round(cagr(C) * 100, 2), "longest_uw_days": uw[0][2], "top3_uw": uw[:3],
            "worst20_pct": worst20(C),
            "yearly_pct": {str(y): round(float(v) * 100, 2) for y, v in C["acct"].groupby(C.index.year).sum().items()},
            "cagr_first_half_pct": round(cagr(C, (HALF_START, HALF_END)) * 100, 2),
            "cagr_second_half_pct": round(cagr(C, (HALF_START2, HALF_END2)) * 100, 2)}


# ── 主流程 ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    t0 = time.time()
    rows, total = fetch_btc_daily()
    wk, diag = weekly_closes(rows)
    fl = flag_series(wk)
    lit_weeks = [w for w in wk.index if bool(fl.get(w, False))]
    json.dump({"source": "ohlcv_daily symbol=BTC source=binance_hist", "fetched_rows": len(rows),
               "db_total_rows": total, "diag": diag,
               "weekly_close": {str(w.date()): round(float(v), 4) for w, v in wk.items()},
               "sma10": {str(w.date()): (round(float(v), 4) if pd.notna(v) else None) for w, v in wk.rolling(SMA_N).mean().items()},
               "close_4w_ago": {str(w.date()): (round(float(v), 4) if pd.notna(v) else None) for w, v in wk.shift(LB_W).items()},
               "flag_lit": {str(w.date()): bool(fl.get(w, False)) for w in wk.index}},
              open(WEEKLY_JSON, "w"), ensure_ascii=False, indent=1)
    print(f"[btc] 行 {len(rows)}/{total} · 周 {len(wk)} · 亮灯周 {len(lit_weeks)} · 用时 {time.time()-t0:.0f}s", flush=True)
    print(f"[btc] 最近 8 周: " + " | ".join(f"{w.date()}={float(wk.loc[w]):.0f}{'*' if bool(fl.get(w, False)) else ''}" for w in wk.index[-8:]), flush=True)
    if "--only-btc" in sys.argv:
        sys.exit(0)

    # 账户窗口内的周网格(周日的标志对下一周生效)
    grid = [w for w in wk.index if pd.Timestamp(HALF_START) <= w + pd.Timedelta(days=1) <= pd.Timestamp(HALF_END2)]
    grid = [w for w in grid if pd.notna(fl.get(w, False)) or pd.notna(wk.rolling(SMA_N).mean().get(w, np.nan))]
    flags = [bool(fl.get(w, False)) for w in grid]
    half_map = day_flag_map(grid, flags)
    base = assemble()
    rc = float(np.cov(base["rv2"].resample("M").sum(), ((1 + base["acct"]).resample("M").prod() - 1))[0, 1] /
               ((1 + base["acct"]).resample("M").prod() - 1).var())
    B = summary(base)
    print("BASE", json.dumps(B, ensure_ascii=False), "rv2_share", round(rc, 3), flush=True)
    assert abs(B["cagr_pct"] - 35.7) < 0.15 and abs(rc - 0.742) < 0.002, "账户对不上 S-834,停"

    # 两条自检
    empty_map = {day: False for day in IDX[1:]}
    sc_empty = float((assemble(empty_map)["acct"] - base["acct"]).abs().max())
    sc_nolit = float((assemble({day: False for day in IDX[1:]})["acct"] - base["acct"]).abs().max())
    assert sc_empty == 0.0 and sc_nolit == 0.0, f"自检失败 {sc_empty} {sc_nolit}"

    V_curve = assemble(half_map)
    V = summary(V_curve)
    V["yearly_diff_pp"] = {y: round(V["yearly_pct"][y] - B["yearly_pct"][y], 2) for y in B["yearly_pct"]}
    V["diff_ex_2022_pp"] = round(sum(v for y, v in V["yearly_diff_pp"].items() if y != "2022"), 2)
    # 半仓统计
    f_days = {}
    for day in IDX[1:]:
        in_mkt = IN_MKT.get(day, False)
        lit = bool(half_map.get(day, False))
        f_days[day] = 0.5 if (lit and in_mkt) else (0.0 if not in_mkt else 1.0)
    half_days = [x for x, f in f_days.items() if f == 0.5]
    switches = []
    prev_f = 1.0
    for day in IDX[1:]:
        f = f_days[day]
        if f != prev_f:
            switches.append((str(day.date()), prev_f, f))
            prev_f = f
    gear_switches = [s for s in switches if {s[1], s[2]} == {0.5, 1.0}]
    lit_weeks_in_window = [w for w in grid if flags[grid.index(w)]]
    V["half_days"] = len(half_days)
    V["half_weeks"] = len({(x - pd.Timedelta(days=x.dayofweek - 1 if x.dayofweek else 7)).strftime("%Y-%m-%d") for x in half_days}) if half_days else 0
    V["lit_weeks_in_window"] = len(lit_weeks_in_window)
    V["exposure_switches_total"] = len(switches)
    V["gear_switches"] = len(gear_switches)
    V["gear_switch_detail"] = gear_switches[:40]
    print("VARIANT", json.dumps(V, ensure_ascii=False), flush=True)

    # 零分布:把亮灯序列按周循环平移 200 次(种子 20261113)
    rng = np.random.default_rng(SEED)
    n = len(grid)
    nc, nu, nw = [], [], []
    for _ in range(N_NULL):
        k = int(rng.integers(1, n))
        sh = [flags[(j - k) % n] for j in range(n)]
        C = assemble(day_flag_map(grid, sh))
        nc.append(cagr(C) * 100)
        nu.append(underwater(C)[0][2])
        nw.append(worst20(C))
    nc, nu, nw = np.array(nc), np.array(nu), np.array(nw)
    null = {"n": N_NULL, "cagr_median": round(float(np.median(nc)), 2), "cagr_p10": round(float(np.quantile(nc, 0.1)), 2),
            "cagr_p90": round(float(np.quantile(nc, 0.9)), 2),
            "uw_median": float(np.median(nu)), "uw_p10": float(np.quantile(nu, 0.1)),
            "worst20_median": round(float(np.median(nw)), 2),
            "real_cagr_pctile": round(float((nc < V["cagr_pct"]).mean()), 3),
            "real_uw_pctile_shorter": round(float((nu > V["longest_uw_days"]).mean()), 3),
            "real_worst20_pctile_better": round(float((nw > V["worst20_pct"]).mean()), 3)}
    print("NULL", json.dumps(null), flush=True)

    uw_gain = B["longest_uw_days"] - V["longest_uw_days"]
    w20_gain = V["worst20_pct"] - B["worst20_pct"]
    a_uw = uw_gain >= 30
    a_w20 = w20_gain >= 1.0
    a = a_uw or a_w20
    b = V["cagr_pct"] >= B["cagr_pct"] - 1.0
    c_cagr = V["cagr_pct"] > null["cagr_median"]
    c_uw = null["real_uw_pctile_shorter"] >= 0.8 if a_uw else None
    c_w20 = null["real_worst20_pctile_better"] >= 0.8 if a_w20 else None
    c_parts = [x for x in (c_cagr, c_uw, c_w20) if x is not None]
    c = bool(c_cagr) and all(c_parts) and (c_uw is not None or c_w20 is not None)
    d1 = V["cagr_first_half_pct"] - B["cagr_first_half_pct"]
    d2 = V["cagr_second_half_pct"] - B["cagr_second_half_pct"]
    crit_d = (d1 >= -1.0) and (d2 >= -1.0)
    verdict = {"a_uw_shorter_30d": bool(a_uw), "a_worst20_better_1pp": bool(a_w20), "a_pass": bool(a),
               "uw_gain_days": uw_gain, "worst20_gain_pp": w20_gain,
               "b_cagr_within_1pp": bool(b), "cagr_gap_pp": round(V["cagr_pct"] - B["cagr_pct"], 2),
               "c_beats_shift_null": bool(c), "c_cagr_above_median": bool(c_cagr),
               "c_uw_top20": c_uw, "c_worst20_top20": c_w20,
               "d_halves_within_1pp": bool(crit_d), "d_first_half_pp": round(d1, 2), "d_second_half_pp": round(d2, 2),
               "pass": bool(a and b and c and d)}
    print("VERDICT", json.dumps(verdict), flush=True)

    res = {"task": "T-368", "ledger": "S-845", "seed": SEED, "n_null": N_NULL,
           "window": {"start": str(IDX[0].date()), "end": str(IDX[-1].date()), "days": len(IDX) - 1},
           "rule": {"sma_weeks": SMA_N, "lookback_weeks": LB_W, "half_exposure": 0.5, "switch_cost_bp": 20,
                    "effective": "周日收盘判,下周一生效", "x1v_in_market_source": "加密腿净值当日有变动(空仓期走平)"},
           "btc": {"rows": len(rows), "db_total": total, "diag": diag, "weekly_json": WEEKLY_JSON,
                   "lit_weeks_total": len(lit_weeks),
                   "recent_weeks": [{"week_end": str(w.date()), "close": round(float(wk.loc[w]), 2),
                                     "sma10": (round(float(wk.rolling(SMA_N).mean().loc[w]), 2) if pd.notna(wk.rolling(SMA_N).mean().loc[w]) else None),
                                     "flag": bool(fl.get(w, False))} for w in wk.index[-12:]]},
           "self_checks": {"empty_rule_max_abs_diff": sc_empty, "never_lit_max_abs_diff": sc_nolit},
           "kernel_crosscheck": kernel_crosscheck(),
           "base": {**B, "rv2_share": round(rc, 3)},
           "variant": V,
           "null": null,
           "verdict": verdict,
           "lit_week_ends_in_window": [str(w.date()) for w in lit_weeks_in_window],
           "half_day_first": str(half_days[0].date()) if half_days else None,
           "half_day_last": str(half_days[-1].date()) if half_days else None,
           "elapsed_s": round(time.time() - t0, 1)}
    json.dump(res, open(OUT, "w"), ensure_ascii=False, indent=1)
    print("WROTE", OUT, flush=True)
