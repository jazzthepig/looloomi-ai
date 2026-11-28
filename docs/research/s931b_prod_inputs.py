"""T-447:S-931 换生产输入重跑 —— 研究用,不进任何账、不动钱、只读库。

卡 `tasks/T-447.json`(Seth 11-28 04:50Z 开):S-931 的 BASE 两处输入不是生产那一版
(T-446 复核:(a) ① NAV 用 `core_variants_daily.cap_pit24`、生产是 `multiplier_daily.core_u_replay`;
(b) 资金费固定年化 10%、生产传实测 BTC 永续资金费;另:未平票只扣 1×10bp,预注册字面 2×10bp)。
⇒ 这里只换输入重跑:窗口、种子(931)、判据(c1–c5)一个不改,结论照预注册判。

用法(仓库根目录):
    python3 docs/research/s931b_prod_inputs.py            # 三条臂全跑(500 次平移零分布,种子 931)
    python3 docs/research/s931b_prod_inputs.py --nshift 5  # 冒烟

三条臂(同一套数据、同一套判据):
  ORIG_full —— 原口径(① = cap_pit24、资金费固定年化 10%)、原窗口 2020-02-01 → 2026-11-19
               (用来复现 S-931 已发布的数:数据来源不同,只作对照)
  ORIG_23   —— 原口径,窗口收到生产 ① 序列的起点 2023-01-02 → 2026-11-19(同窗口对照)
  PROD_23   —— 生产输入(① = multiplier_daily.core_u_replay;资金费 = funding_history binance_perp
               按天求和 ×365,缺值才落 0.10 并计数)＋未平票 2×10bp,同窗口
生产 ① 的回放 `core_u_replay` 只回放到 2023-01-02 ⇒ 发现段 [2020-02-01, 2022-12-31] 没有生产输入,
发现段的 LUW / 崩塌不可评 —— 如实写,不外推。
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from src.data.signals.tom import trade_path, trade_returns  # noqa: E402

REST = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
KEY = os.environ["SUPABASE_KEY"]
OUT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "docs/research/s931b_results.json")
WINDOW_END = dt.date(2026, 11, 19)          # 预注册的窗口末(S-931 用的数据截止日)
PX_FROM = dt.date(2020, 1, 1)               # px 起点:⓪ 第 10 个周日(=首次能判)落在 2020-03-08,与 S-931 发布数(2020-02 那段崩塌「不可评」)对得上
COST = 0.001


def _load(name):
    sp = importlib.util.spec_from_file_location(name, os.path.join(HERE, f"{name}.py"))
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


S931 = _load("s931_x1v_zero_veto")           # 原脚本:只 import,不改
B, P = S931.B, S931.P                        # s928(⓪ 周度状态)、s929(T-370 v1 票)


# ── 只读取数(每页 ≤1000,带 order=)────────────────────────────────────────────

def _fetch(table: str, params: dict, order: str) -> list:
    rows, off = [], 0
    while True:
        p = dict(params)
        p.update({"limit": 1000, "offset": off, "order": order})
        url = REST + table + "?" + urllib.parse.urlencode(p, safe="(),.*:<>=")
        req = urllib.request.Request(url, headers={"apikey": KEY, "Authorization": f"Bearer {KEY}"})
        with urllib.request.urlopen(req, timeout=180) as r:
            body = r.read().decode()
        batch = json.loads(body) if body else []
        if not batch:
            break
        rows.extend(batch)
        off += len(batch)
        if len(batch) < 1000:
            break
    return rows


def _d(s: str) -> dt.date:
    return dt.date(int(s[:4]), int(s[5:7]), int(s[8:10]))


def load_inputs() -> dict:
    px: dict = {"BTC": {}, "ETH": {}}
    rows = _fetch("ohlcv_daily", {"select": "symbol,trade_date,open,high,low,close",
                                  "source": "eq.binance_hist", "symbol": "in.(BTC,ETH)"}, "id.asc")
    for r in rows:
        d = _d(r["trade_date"])
        if d < PX_FROM or any(r[k] is None for k in ("open", "high", "low", "close")):
            continue
        px[r["symbol"]][d] = (float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
    fund: dict = {"BTC": {}, "ETH": {}}
    for r in _fetch("funding_history", {"select": "symbol,funding_time,funding_rate",
                                        "venue": "eq.binance_perp", "symbol": "in.(BTC,ETH)"}, "funding_time.asc,symbol.asc"):
        if r["funding_rate"] is None:
            continue
        fund[r["symbol"]][_d(r["funding_time"])] = fund[r["symbol"]].get(_d(r["funding_time"]), 0.0) + float(r["funding_rate"])
    stable = {(_d(r["d"])): float(r["value"]) for r in _fetch(
        "state_daily", {"select": "d,value", "entity": "eq.panel", "feature": "eq.stable_supply_30d",
                        "value": "not.is.null"}, "entity.asc,feature.asc,d.asc")}
    taker = {(_d(r["d"])): float(r["value"]) for r in _fetch(
        "state_daily", {"select": "d,value", "entity": "eq.panel", "feature": "eq.taker_buy_share_30d",
                        "value": "not.is.null"}, "entity.asc,feature.asc,d.asc")}
    d200 = {(_d(r["d"])): float(r["value"]) for r in _fetch(
        "state_daily", {"select": "d,value", "entity": "eq.panel", "feature": "eq.dist_200",
                        "value": "not.is.null"}, "entity.asc,feature.asc,d.asc")}
    y2 = {(_d(r["d"])): float(r["value"]) for r in _fetch(
        "macro_daily", {"select": "d,value", "series": "eq.ust_2y", "value": "not.is.null"}, "series.asc,d.asc")}
    core_prod = {(_d(r["d"])): float(r["nav"]) for r in _fetch(
        "multiplier_daily", {"select": "d,nav", "arm": "eq.core_u_replay"}, "arm.asc,d.asc")}
    core_orig = {(_d(r["d"])): float(r["nav"]) for r in _fetch(
        "core_variants_daily", {"select": "d,nav", "arm": "eq.cap_pit24"}, "arm.asc,d.asc")}
    return {"px": px, "fund": fund, "stable": stable, "taker": taker, "y2": y2, "d200": d200,
            "core_prod": core_prod, "core_orig": core_orig}


# ── 跑:与 s931.build 同口径,只多一个资金费入参 ───────────────────────────────

def build(data: dict, core_nav: dict, fund_ann, wk_override: dict | None = None, pre: tuple | None = None):
    px, fund, stable, taker, y2, d200 = data["px"], data["fund"], data["stable"], data["taker"], data["y2"], data["d200"]
    if pre is None:
        core = pd.Series({pd.Timestamp(d): v for d, v in core_nav.items()}).sort_index()
        g0 = S931.x1v(core)                   # = trade_path(core,'rally',0.0,'l20',True)(生产函数)
    else:
        core, g0 = pre
    r0 = trade_returns(core, g0, fund_ann)
    bdays = sorted(d for d in px["BTC"] if d in px["ETH"])
    bclose = {d: px["BTC"][d][3] for d in bdays}
    wk = wk_override if wk_override is not None else {s: x for s, x in B.weekly_states(bdays, bclose, stable, taker, y2, "D1").items()}
    defend_all = B.daily_defend(bdays, wk)
    g1 = S931.veto(g0, defend_all)
    r1 = trade_returns(core, g1, fund_ann)
    days = [d for d in (ts.date() for ts in core.index) if d >= S931.START and d in px["BTC"] and d in px["ETH"]]
    base_ret = {ts.date(): float(v) for ts, v in r0.items()}
    v1_ret = {ts.date(): float(v) for ts, v in r1.items()}
    dd = {d: defend_all.get(d, False) for d in days}
    wkw = {s: x for s, x in wk.items() if s in set(days)}
    res = {"BASE": S931.account(days, base_ret, px, fund, d200, stable, dd, wkw, False),
           "V1": S931.account(days, v1_ret, px, fund, d200, stable, dd, wkw, False),
           "V2": S931.account(days, v1_ret, px, fund, d200, stable, dd, wkw, True)}
    core_d = {d: float(core[pd.Timestamp(d)]) for d in days}
    hold = np.array([core_d[d] / core_d[days[0]] for d in days])
    first_ready = min((s for s, v in wk.items() if v.get("ready")), default=days[0])
    return days, core_d, hold, res, wk, dd, first_ready, g0, g1


def seg_stats_safe(days, nav):
    """s931.seg_stats 同口径;发现段为空(窗口在 SPLIT 之后)时 disc = None(不可评),hold = 全段。"""
    m = np.array([d < S931.SPLIT for d in days])
    out = {"all": B.underwater(days, nav)}
    if m.any() and (~m).any():
        out["disc"] = B.underwater(days, nav, m)
        out["hold"] = B.underwater(days, nav, ~m)
    elif (~m).all():
        out["disc"], out["hold"] = None, out["all"]
    else:
        out["disc"], out["hold"] = out["all"], None
    return out


def judge_safe(st: dict, ct: list, rt: list, tk: dict, pct: float) -> dict:
    """s931.judge 同一条一条;发现段缺(c1 的 disc 一半、c5 的 disc 段)时该半边记 None = 不可评。"""
    c1h = bool(st["V2"]["hold"]["longest_underwater_d"] < st["BASE"]["hold"]["longest_underwater_d"])
    c1d = None
    if st["V2"].get("disc"):
        c1d = bool(st["V2"]["disc"]["longest_underwater_d"] <= st["BASE"]["disc"]["longest_underwater_d"])
    c1 = None if c1d is None else bool(c1h and c1d)
    ev = [c for c in ct if c["evaluable"]]
    cuts = [1 - c["V2"] / c["BASE"] for c in ev if c["BASE"] < 0]
    c2 = bool(all(c["V2"] >= c["BASE"] for c in ev) and (np.mean(cuts) > 0 if cuts else False))
    c3 = bool(all(r["V2"] >= r["BASE"] - 0.10 for r in rt))
    c4 = bool(pct >= 0.90)
    def half(k):
        t = tk.get(k) or {}
        if not t.get("n"):
            return None
        return bool(t.get("mean_pct", 0) > 0 and (t.get("payoff") or 0) >= 2)
    c5h, c5d = half("hold"), half("disc")
    c5 = None if c5d is None else bool(c5h and c5d)
    parts = {"c1": c1, "c2": c2, "c3": c3, "c4": c4, "c5": c5}
    known = [v for v in parts.values() if v is not None]
    return {"c1_underwater": c1, "c2_crash_not_worse": c2, "mean_cut_vs_base": round(float(np.mean(cuts)), 3) if cuts else None,
            "c3_rally_cost": c3, "c4_shift_pct": round(pct, 3), "c4": c4, "c5_tickets": c5,
            "c1_hold_part": c1h, "c1_disc_part": c1d, "c5_hold_part": c5h, "c5_disc_part": c5d,
            "pass": bool(all(known)) and len(known) == 5,
            "pass_note": "五条全过" if len(known) == 5 else f"不可判:缺 {5 - len(known)} 条(发现段无生产输入)"}


def run_arm(data: dict, core_nav: dict, fund_ann, n_shift: int) -> dict:
    core = pd.Series({pd.Timestamp(d): v for d, v in core_nav.items()}).sort_index()
    g0 = S931.x1v(core)                       # 生产 X1V 路径,同一臂内只算一次
    pre = (core, g0)
    days, core_d, hold, res, wk, dd, first_ready, g0, g1 = build(data, core_nav, fund_ann, None, pre)
    navs = {"HOLD": hold, **{k: v["nav"] for k, v in res.items()}}
    st = {k: seg_stats_safe(days, nv) for k, nv in navs.items()}
    ct, rt = S931.episodes_table(days, core_d, navs, first_ready)
    tk = S931.tstats(res["V2"]["tickets"])
    suns = sorted(s for s, v in wk.items() if v.get("ready"))
    flags = [wk[s]["defend"] for s in suns]
    rng = np.random.default_rng(S931.SEED)
    null = []
    for _ in range(n_shift):
        o = int(rng.integers(8, len(suns) - 8))
        w2 = {s: {"defend": bool(f), "ready": True} for s, f in zip(suns, np.roll(flags, o))}
        _, _, _, r2, _, _, _, _, _ = build(data, core_nav, fund_ann, w2, pre)
        null.append(B.underwater(days, r2["V2"]["nav"])["longest_underwater_d"])
    pct = float((np.array(null) > st["V2"]["all"]["longest_underwater_d"]).mean())
    veto_days = int(sum(1 for d in days if dd[d]))
    vetoed_long = int(sum(1 for ts, a, b in zip(g0.index, g0.values, g1.values) if ts.date() >= S931.START and a > 0 and b == 0))
    # 未平票:预注册字面 2×10bp(进场 + 出场各 10bp;未平的那张照样算两次)
    open_fixed = []
    for t in res["V2"]["open"]:
        t2 = dict(t)
        t2["pct"] = (t["entry"] - t["exit"]) / t["entry"] + t["fund"] - 2 * COST
        open_fixed.append(t2)
    j_safe = judge_safe(st, ct, rt, tk, pct)
    j_orig = S931.judge(st, ct, rt, tk, pct) if st["V2"].get("disc") else None
    same = None if j_orig is None else bool(all(j_safe[k] == j_orig[k] for k in
            ("c1_underwater", "c2_crash_not_worse", "mean_cut_vs_base", "c3_rally_cost", "c4", "c5_tickets")))
    return {"window": [str(days[0]), str(days[-1])], "stats": st, "crash": ct, "rally": rt, "tickets": tk,
            "open_tickets": [{k: (str(v) if isinstance(v, dt.date) else v) for k, v in t.items()
                              if k in ("sym", "entry_d", "entry", "stop0", "pct", "why")} for t in open_fixed],
            "defend_days": veto_days, "x1v_long_days_vetoed": vetoed_long,
            "shift_null_luw": {"median": float(np.median(null)), "q10": float(np.quantile(null, 0.10))},
            "judge": j_safe, "judge_orig": j_orig, "judge_matches_s931_judge": same}


def funding_annual(fund: dict, core_dates: list) -> tuple:
    """生产口径(BTC 永续日资金费 ×365);缺的日子按 tom.trade_returns 的规则 ffill,开头没有才落 0.10。"""
    ann = pd.Series({pd.Timestamp(d): v * 365.0 for d, v in fund.items() if d in set(core_dates)})
    raw = ann.reindex(pd.to_datetime(core_dates))
    obs = int(raw.notna().sum())
    ffilled = int((raw.isna() & raw.ffill().notna()).sum())
    default = int((raw.isna() & raw.ffill().isna()).sum())
    return ann, {"core_days": len(core_dates), "funding_observed_days": obs,
                 "funding_ffilled_days": ffilled, "funding_default_0.10_days": default}


if __name__ == "__main__":
    n_shift = 5 if "--nshift" in sys.argv else S931.N_SHIFT
    if "--nshift" in sys.argv:
        n_shift = int(sys.argv[sys.argv.index("--nshift") + 1])
    data = load_inputs()
    print("INPUTS px", {s: (min(d), max(d), len(d)) for s, d in data["px"].items()},
          "| fund", {s: len(d) for s, d in data["fund"].items()},
          "| stable", len(data["stable"]), "| taker", len(data["taker"]), "| y2", len(data["y2"]),
          "| d200", len(data["d200"]),
          "| core_prod", (min(data["core_prod"]), max(data["core_prod"]), len(data["core_prod"])),
          "| core_orig", (min(data["core_orig"]), max(data["core_orig"]), len(data["core_orig"])), flush=True)

    arms = {}
    orig_23 = {d: v for d, v in data["core_orig"].items() if d >= dt.date(2023, 1, 2) and d <= WINDOW_END}
    prod_23 = {d: v for d, v in data["core_prod"].items() if d >= dt.date(2023, 1, 2) and d <= WINDOW_END}
    ann, fcount = funding_annual(data["fund"]["BTC"], sorted(prod_23))

    def miss_days(sym: str, d0: dt.date, d1: dt.date) -> dict:
        """窗口内没有资金费记录的天数。加密腿:tom.trade_returns 先 ffill(用上一日实测),开头没有才落 0.10;
        票的路径是 `fund[sym].get(d, 0.0)` —— 缺的那天按 0 静默算,这里单列出来,不当 0 混进结论。"""
        s = data["fund"].get(sym, {})
        days = [d for d in sorted(data["px"]["BTC"]) if d0 <= d <= d1 and d in data["px"]["ETH"]]
        miss = [d for d in days if d not in s]
        return {"window_days": len(days), "missing_days": len(miss),
                "first_missing": str(miss[0]) if miss else None, "last_missing": str(miss[-1]) if miss else None}

    pub = {}
    pub_path = os.path.join(HERE, "s931_results.json")
    if os.path.exists(pub_path):
        pub = json.load(open(pub_path))
    inp = {"px": {s: [str(min(d)), str(max(d)), len(d)] for s, d in data["px"].items()},
           "fund": {s: [str(min(d)), str(max(d)), len(d)] for s, d in data["fund"].items()},
           "stable": [str(min(data["stable"])), str(max(data["stable"])), len(data["stable"])],
           "taker": [str(min(data["taker"])), str(max(data["taker"])), len(data["taker"])],
           "y2": [str(min(data["y2"])), str(max(data["y2"])), len(data["y2"])],
           "d200": [str(min(data["d200"])), str(max(data["d200"])), len(data["d200"])],
           "core_prod": [str(min(data["core_prod"])), str(max(data["core_prod"])), len(data["core_prod"])],
           "core_orig": [str(min(data["core_orig"])), str(max(data["core_orig"])), len(data["core_orig"])]}
    house_rules = {
        "layer": "③ 加密腿(生产 X1V)+ ⓪ 否决 + 空头票",
        "ruler": "账户口径:回本时间、每段崩塌的损失、每段上涨拿到几成;票:占名义 % 的均值与盈亏比(DECISIONS 11-11 / 11-15)",
        "uses": ["T370", "EXPOSURE"],
        "varies": {
            "① 的 NAV": "S-931 原用 core_variants_daily.cap_pit24(① 历史锚);T-447 换成生产的 multiplier_daily.core_u_replay(生产 tom_trader 的核,forward_books.tom_inputs)",
            "资金费": "S-931 原用固定年化 10%(tom.trade_returns 的默认值);T-447 换成实测 BTC 永续资金费(funding_history binance_perp 按天求和 ×365,与 forward_books.tom_inputs 同口径),缺值先 ffill、再落 0.10",
            "未平票成本": "S-931 原脚本对未平票只扣 1×10bp;按预注册字面,T-447 记 2×10bp",
            "⓪ 否决": "S-931:新加的一层 —— ⓪ 确认转向后,X1V 的多头(含反弹单、回补)清零,直到 ⓪ 退出",
            "⓪ 签名": "S-931:回测里没有 Jazz 的签名,用 S-928 的 D1 防守代理(同 S-929)",
            "加密腿权重": "S-931 账户里加密腿占 100%;生产 T25 里这条腿占 30%(FLEX_X1V_ARMS T25 crypto=0.30)—— 结论不能直接搬去生产",
        },
    }

    def dump():
        out = {"card": "T-447",
               "window_rule": {"start": str(S931.START), "split": str(S931.SPLIT), "end": str(WINDOW_END),
                               "seed": S931.SEED, "n_shift": n_shift,
                               "note": "生产 ① 序列 core_u_replay 只回放到 2023-01-02 ⇒ 发现段 [2020-02-01, 2022-12-31] 无生产输入"},
               "funding_count": fcount,
               "funding_missing": {"BTC_prod_window": miss_days("BTC", dt.date(2023, 1, 2), WINDOW_END),
                                   "ETH_prod_window": miss_days("ETH", dt.date(2023, 1, 2), WINDOW_END),
                                   "BTC_orig_window": miss_days("BTC", S931.START, WINDOW_END),
                                   "ETH_orig_window": miss_days("ETH", S931.START, WINDOW_END)},
               "house_rules": house_rules,
               "arms": arms, "published_s931": pub, "inputs": inp,
               "notes": ["A 臂(重建对照)与 B 臂(生产输入)只差三处输入;判据、阈值、窗口、平移种子完全一样。",
                         "ORIG_full 与 S-931 发布数的差 = 数据重建漂移(私有导出不在仓库侧,这里从库重建);PROD_23 与 ORIG_23 的差 = 生产输入效应。",
                         "PROD_23 的窗口由 ① 生产核的历史决定(core_u_replay 自 2023-01-02 起)—— 发现段没有生产 NAV,相关判据记「不可评」。"]}
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1, default=str)

    # ① 生产输入(交付的那条)
    arms["PROD_23"] = run_arm(data, prod_23, ann, n_shift)
    print("ARM PROD_23 done", json.dumps(arms["PROD_23"]["judge"]), "| funding", json.dumps(fcount), flush=True)
    dump()
    # ② 同窗口对照:原口径(① = cap_pit24、资金费固定年化 10%)
    arms["ORIG_23"] = run_arm(data, orig_23, None, n_shift)
    print("ARM ORIG_23 done", json.dumps(arms["ORIG_23"]["judge"]), flush=True)
    dump()
    # ③ 原窗口原口径:复现 S-931 已发布的数(数据来源不同,只作对照)
    orig_full = {d: v for d, v in data["core_orig"].items() if d <= WINDOW_END}
    arms["ORIG_full"] = run_arm(data, orig_full, None, n_shift)
    print("ARM ORIG_full done", json.dumps(arms["ORIG_full"]["judge"]), flush=True)
    dump()
    print("WROTE", OUT, flush=True)
