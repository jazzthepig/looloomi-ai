"""T-333 —— S-809 情绪过热之后的转弯做空 BTC(预注册见下面 PREREG,先写下来再算,只算一次)。

用法:python3 docs/research/t333_euphoria_short.py
产物:docs/research/T-333_euphoria_turn_short.md + t333_results.json + t333_tickets.csv
数据:只读 Supabase(perp_bv_daily / v_funding_daily / macro_daily[fng] / style_index_pit_daily)
     + Deribit DVOL 缓存(只用于 S-736 自检)。
纪律:不改代码、不入库、不做 DDL;零分布 / 盈亏 / A-B 比较只用 src/data/evaluation/apparatus.py。
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))

from docs.research.crash_atlas_common import to_calendar  # noqa: E402
from src.data.evaluation.apparatus import (  # noqa: E402
    NoOpNull,
    ab_test,
    null_distribution,
    percentile_of,
)

U = os.environ["SUPABASE_URL"]
K = os.environ["SUPABASE_KEY"]
H = {"apikey": K, "Authorization": "Bearer " + K, "Prefer": "count=exact"}
CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/research/t333")
DVOL_CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/_cache/t229")

COST_BPS = 7.5            # 每次开 / 关 7.5bp(S-736 同)
STOP_ATR = 1.5            # 止损 = 进场价 + 1.5 × ATR14(d)(S-736 同)
TP_ATR = 2.5              # 止盈 = 进场价 − 2.5 × ATR14(d)(S-736 同)
TIME_STOP = 15            # 时间止损 15 根(S-736 同)
RISK_PCT = 0.005          # 每票风险 0.5% 净值(S-736 同)
MAX_NOTIONAL = 0.50       # 名义 ≤ 净值 50%(S-736 同)
MA_N = 20
ATR_N = 14
MIN_OBS = 250             # 扩张分位最少观测数(S-809 写死)
OVERHEAT_PCT = 85         # 扩张 85 分位(S-809 写死)
TURN_WINDOW = 30          # 过热日之后 30 天内(S-809 写死)
SEED = 809
N_NULL = 1000
ALT_STYLES = ["defi", "second_l1_l2", "infra_tokenization", "ai", "app"]

S809_VERBATIM = """## S-809 — 情绪过热之后的转弯做空 BTC:恐惧贪婪 + 资金费都在高位,之后价格第一次跌破 20 日线才开空票 —— 预注册(Seth,2026-11-11 00:30 UTC;S-736 是在「恐惧 / 流动性变差」时做空,失败;这条是反过来 —— 在「贪婪」见顶转弯时做空;交 B 道 T-333)
**为什么。** 崩盘图谱(T-187)里加密自己的情绪线索 —— 恐惧贪婪 7 日均 ≥ 75(lift 2.97)、BTC 资金费年化 7 日均 ≥ 30%(急跌 lift 3.19)—— 锚点只有 3–5 个,做不成规则,但方向一致:**拥挤的多头付着高资金费,一旦价格转弯,清算链会放大下跌**。S-736 的失败告诉我们:不要在恐惧里做空(那是底部),要在贪婪里、等价格先转弯。
**写死。** 过热日 h:`fng` 7 日均 ≥ 截至 h 的扩张 85 分位 **且** BTC 资金费年化 7 日均 ≥ 截至 h 的扩张 85 分位(各 ≥ 250 个观测;数据同 T-187 的 `macro_series('fng')` 与 `v_funding_daily`)。触发日 d:某个过热日之后 30 天内,BTCUSDT 永续收盘**第一次**低于 20 日均线;已有票在场不叠加。票机械**与 S-736 一字相同**(BTCUSDT 永续,d + 1 开盘进空,止损 1.5 ATR,止盈 2.5 ATR,+1R 保本,时间 15 根,成本与资金费同)。
**判(全过才 ✅,与 S-736 同一把尺):** (a) 票数 ≥ 15(不足只报不判);(b) 平均 R > 0 且 `ab_test` 对 0 p < 0.10(票少,放宽一档,算前写死);(c) 随机对照:同出场规则、同票数、只在「收盘 < 20 日线」的日子里随机进场(1,000 次,种子 809),平均 R ≥ 对照 90 分位;(d) 对 |R| 最大的一张留一,平均 R 仍 > 0;(e) 逐期报(2020–21 / 2022 / 2023–24 / 2025–26)。另报:同触发下做空 ① 山寨等权篮的平均 R(只报)。
**后果:** 全过 ⇒ 开纸面臂 `short_euphoria_turn`(不动钱);不过 ⇒ 市场级情绪过热做不成空票。**诚实:** 过热段在 2019–2026 只有几段,票数大概率不多 —— 这条更可能落在「只报不判」;那也是答案。**试验计数:+1(做空族)。**"""

PREREG = """# T-333 —— S-809 情绪过热之后的转弯做空 BTC

## S-809 预注册原文(照抄,来自 REFUTATION_LEDGER.md)

""" + S809_VERBATIM + """

## 本卡的执行口径(**算之前写死**;与预注册冲突处以预注册为准,这里只写「原文没写」的部分)

**数据(全部只读,不入库):**
- 价格 / 票:`perp_bv_daily`(`pair = eq.BTCUSDT`,Binance U 本位永续),bar = 日线 o/h/l/c。
- 情绪:`macro_daily`(`series = eq.fng`),日频。
- 资金费:`v_funding_daily`(`symbol = eq.BTC`),日内合计 = Σ(`funding_rate` × `n`)。
- 山寨篮:`style_index_pit_daily`(`weighting = eq.equal`,`dimension in (sector,tier)`,
  五个板块 `defi / second_l1_l2 / infra_tokenization / ai / app`,T-187 同口径)。
- DVOL(Deribit 日线)只用于 **S-736 自检**,不参与 S-809 触发。

**过热日 h(只用到 h 及之前的数据):**
- `fng7(h)` = fng 的 7 日滚动均值(日历日,`to_calendar(fng, 7)` 后 rolling(7),缺值不补 0)。
- `fund7ann(h)` = 资金费日内合计 × 365 → 7 日滚动均值(日历日,`to_calendar(f, 5)` + `to_calendar(ann, 10)`,
  与 T-187 的 `btc_funding_annualized` 同构造)。
- 两个**扩张 85 分位**各自按「截至 h 的全部观测」线性插值算(≥ 250 个观测才可用;不用全样本分位)。
- h 成立 ⇔ `fng7(h) ≥ fng7 扩张 85 分位` **且** `fund7ann(h) ≥ fund7ann 扩张 85 分位`。

**触发日 d:** 某个过热日 h 之后 **30 天内**(d > h 且 d ≤ h + 30),BTCUSDT 永续收盘**第一次**
低于 20 日均线(MA20 含当日)的那一天。多个过热日指向同一个 d ⇒ 只算一张票(归属记最早的那个 h)。
已有票在场不叠加(下一张票的进场日必须晚于上一张的出场日)—— 与 S-736 同。

**票(与 S-736 一字相同):** d+1 开盘进空;ATR14(d) = Wilder RMA(TR);止损 = 进场价 + 1.5×ATR14(d);
止盈 = 进场价 − 2.5×ATR14(d);浮盈 +1R 后止损移到进场价(保本);时间止损 15 根;
同一根 bar 既碰止损又碰止盈 ⇒ 按止损(保守);跳空越过止损/止盈 ⇒ 按开盘价;成本 7.5bp × 2;
资金费按持有期实计(空方收正费率)。
R 的口径:价格 R = (进场价 − 出场价) ÷ R 单位;净 R = 价格 R + 资金费 R − 成本 R。

**判据(a)–(e)(原文照抄,见上;下面只写读法):**
- (a) 票数 ≥ 15;不足 ⇒ **只报不判**(其余 (b)–(e) 仍逐条报数与判定,照写)。
- (b) 平均净 R > 0 且 `apparatus.ab_test`(对照臂 = 0,逐日 NAV 口径,与 S-736 同)p < 0.10。
  **「票少放宽一档」的读法锁定(算前写死):** 原文里的 p < 0.10 本身就是相对 S-736 的 p < 0.05
  放宽的那一档;**不再二次放宽**(票少也不把门槛降到 0.20)。
- (c) 随机对照:同出场规则、同票数、只在「收盘 < 20 日线」的日子里随机进场,1,000 次,种子 809。
  **抽样池写死:** S-809 评估窗 = 首个过热日 → 最后一根 bar,池 = 该窗内收盘 < MA20 的日子。
  **主口径 = 贪心不重叠**(与实际票同构);**辅口径 = 独立抽样**,两个都报。
  判定用 `apparatus.percentile_of`(实际值在零分布中的中秩分位)≥ 0.90。
- (d) 对 |净 R| 最大的一张留一,平均净 R 仍 > 0。
- (e) 逐期报(2020–21 / 2022 / 2023–24 / 2025–26,按信号日切)。
  **原文没给 (e) 的数值门槛** ⇒ (e) 判为「已报」;另按 S-736 同一把尺(**任一期平均净 R < −0.3 ⇒ ❌**)
  给出**辅助判定**,明确标注是辅助口径,不替代原文。

**自检(卡上的 acceptance):** 先用同一套数据与同一套票机械复现 S-736 的 18 张票(平均净 R −0.3745),
复现不上就不出结论。复现用的 S-736 触发:① `cycle_vector_daily.phase = turning` 或
`deterioration` ≤ 截至 d 的扩张 20 分位(≥ 250 观测);② BTC DVOL 过去一年分位 ≥ 0.70(不含当日);
③ 收盘 < MA20;窗口 = DVOL 有数据的日子。

**副(只报):** 同触发下做空 ① 山寨等权篮(五板块等权)的平均收益(% 与 R 等价)。

**试验计数:做空族 +1。**
"""

# ───────────────────────────── 取数 ─────────────────────────────
def pull(table: str, params: dict, page: int = 1000) -> list[dict]:
    """PostgREST 翻页读。必须带 order=(按主键排);每页 ≤ 1000 行。"""
    rows: list[dict] = []
    off = 0
    while True:
        q = dict(params)
        q["limit"] = str(page)
        q["offset"] = str(off)
        url = f"{U}/rest/v1/{table}?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers=H)
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = json.loads(resp.read())
        if not isinstance(body, list):
            raise RuntimeError(f"{table}: {str(body)[:200]}")
        rows.extend(body)
        if len(body) < page:
            return rows
        off += page


def load(name: str, table: str, params: dict) -> list[dict]:
    p = CACHE / f"{name}.json"
    if p.exists():
        rows = json.loads(p.read_text())
        print(f"  cache {name}: {len(rows)} rows", flush=True)
        return rows
    rows = pull(table, params)
    CACHE.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows))
    print(f"  pulled {name}: {len(rows)} rows", flush=True)
    return rows


print("[1/8] 读数据…", flush=True)
perp = load("perp_btc", "perp_bv_daily",
            {"select": "d,o,h,l,c,pair,symbol,recorded_at", "pair": "eq.BTCUSDT",
             "order": "d.asc,recorded_at.asc"})
cyc = load("cycle", "cycle_vector_daily",
           {"select": "d,phase,deterioration,shift,shift_pct,n_components", "order": "d.asc"})
vf = load("v_funding_btc", "v_funding_daily",
          {"select": "d,symbol,funding_rate,n", "symbol": "eq.BTC", "order": "d.asc,symbol.asc"})
fng_rows = load("fng", "macro_daily",
                {"select": "d,value", "series": "eq.fng", "order": "d.asc"})
alt_rows = load("alt_styles", "style_index_pit_daily",
                {"select": "d,style,ret,dimension,weighting,n_members",
                 "dimension": "in.(sector,tier)",
                 "style": "in.(" + ",".join(ALT_STYLES) + ")",
                 "weighting": "eq.equal", "order": "d.asc"})

# ── bar(同一日多条 ⇒ 取 recorded_at 最晚的一条)──
bars_by_d: dict[str, dict] = {}
n_dup = 0
for r in perp:
    if any(r.get(k) is None for k in ("o", "h", "l", "c")):
        continue
    d = str(r["d"])[:10]
    if d in bars_by_d:
        n_dup += 1
    bars_by_d[d] = {"d": d, "o": float(r["o"]), "h": float(r["h"]),
                    "l": float(r["l"]), "c": float(r["c"])}
bars = [bars_by_d[d] for d in sorted(bars_by_d)]
DATES = [b["d"] for b in bars]
IDX = {d: i for i, d in enumerate(DATES)}
OPEN = np.array([b["o"] for b in bars], dtype=float)
HIGH = np.array([b["h"] for b in bars], dtype=float)
LOW = np.array([b["l"] for b in bars], dtype=float)
CLOSE = np.array([b["c"] for b in bars], dtype=float)
n = len(bars)
print(f"  bars: {n} {DATES[0]} → {DATES[-1]}(同日重复 {n_dup} 条,取最后)", flush=True)

# ── 资金费:日内合计 ──
fund_bn: dict[str, float] = {}
for r in vf:
    dd = str(r["d"])[:10]
    nn = int(r.get("n") or 1)
    fund_bn[dd] = fund_bn.get(dd, 0.0) + float(r["funding_rate"]) * nn

# ── 周期向量(自检用)──
phase: dict[str, str] = {}
det: dict[str, float] = {}
for r in cyc:
    dd = str(r["d"])[:10]
    if r.get("phase"):
        phase[dd] = str(r["phase"])
    if r.get("deterioration") is not None:
        det[dd] = float(r["deterioration"])

# ── 指标(只用到 d 及之前)──
print("[2/8] 算指标…", flush=True)
tr = np.zeros(n)
tr[0] = HIGH[0] - LOW[0]
for i in range(1, n):
    tr[i] = max(HIGH[i] - LOW[i], abs(HIGH[i] - CLOSE[i - 1]), abs(LOW[i] - CLOSE[i - 1]))
atr = np.full(n, np.nan)
if n > ATR_N:
    atr[ATR_N] = float(np.mean(tr[1:ATR_N + 1]))
    for i in range(ATR_N + 1, n):
        atr[i] = (atr[i - 1] * (ATR_N - 1) + tr[i]) / ATR_N
ma20 = np.full(n, np.nan)
for i in range(MA_N - 1, n):
    ma20[i] = float(np.mean(CLOSE[i - MA_N + 1:i + 1]))

# ── fng / 资金费年化(口径同 T-187)──
fng_s = (pd.Series(pd.to_numeric([r["value"] for r in fng_rows], errors="coerce"),
                    index=pd.to_datetime([str(r["d"])[:10] for r in fng_rows]), dtype="float64")
         .dropna().sort_index())
fng_cal = to_calendar(fng_s, 7)
fng7 = fng_cal.rolling(7, min_periods=7).mean()

f_s = pd.Series(fund_bn, dtype="float64").sort_index()
f_s.index = pd.to_datetime(f_s.index)
f_cal = to_calendar(f_s, 5)
fund_ann = f_cal * 365.0
fund_ann_cal = to_calendar(fund_ann, 10)
fund7ann = fund_ann_cal.rolling(7, min_periods=7).mean()
print(f"  fng7: {fng7.first_valid_index()} → {fng7.last_valid_index()};fund7ann: "
      f"{fund7ann.first_valid_index()} → {fund7ann.last_valid_index()}", flush=True)


def expanding_pct(series: pd.Series, pct: float, min_obs: int) -> dict[str, float]:
    """截至 d 的扩张分位(线性插值)。观测数 < min_obs 的日子没有阈值。"""
    out: dict[str, float] = {}
    buf: list[float] = []
    for d in series.index:
        v = series.loc[d]
        if pd.isna(v):
            continue
        buf.append(float(v))
        if len(buf) >= min_obs:
            out[d.strftime("%Y-%m-%d")] = float(np.percentile(np.asarray(buf, dtype=float), pct))
    return out


p85_fng = expanding_pct(fng7, OVERHEAT_PCT, MIN_OBS)
p85_fund = expanding_pct(fund7ann, OVERHEAT_PCT, MIN_OBS)
print(f"  扩张 85 分位首日:fng {min(p85_fng)} / funding {min(p85_fund)}", flush=True)

# ── 票机械(与 S-736 一字相同)──
def simulate(d: str, tp_atr: float = TP_ATR, fund_map: dict[str, float] | None = None) -> dict | None:
    """在信号日 d 开一张空票。返回票的字典;数据不够返回 None。"""
    fm = fund_map if fund_map is not None else fund_bn
    i = IDX[d]
    if i + 1 >= n:
        return None
    a = atr[i]
    if math.isnan(a) or a <= 0:
        return None
    j = i + 1
    entry = float(OPEN[j])
    r_unit = STOP_ATR * a
    stop0 = entry + r_unit
    target = entry - tp_atr * a
    be_trigger = entry - r_unit          # +1R
    stop = stop0
    exit_i = None
    exit_px = None
    reason = ""
    for k in range(TIME_STOP):
        b = j + k
        if b >= n:
            break
        o, h, l = float(OPEN[b]), float(HIGH[b]), float(LOW[b])
        if o >= stop:                       # 跳空穿止损 ⇒ 按开盘价
            exit_i, exit_px, reason = b, o, ("保本" if stop == entry else "止损")
            break
        if o <= target:                    # 跳空越过止盈 ⇒ 按开盘价
            exit_i, exit_px, reason = b, o, "止盈"
            break
        if h >= stop:
            exit_i, exit_px, reason = b, stop, ("保本" if stop == entry else "止损")
            break
        if l <= target:
            exit_i, exit_px, reason = b, target, "止盈"
            break
        if l <= be_trigger:                # 浮盈到 +1R ⇒ 止损移到进场价
            if h >= entry:                 # 同一根 bar 回到进场价 ⇒ 保守按保本出场
                exit_i, exit_px, reason = b, entry, "保本"
                break
            stop = entry
    truncated = False
    if exit_i is None:
        b = min(j + TIME_STOP - 1, n - 1)
        exit_i, exit_px, reason = b, float(CLOSE[b]), "时间"
        truncated = b < j + TIME_STOP - 1
    hold_days = exit_i - j + 1
    fd = DATES[j:exit_i + 1]
    fund = float(sum(fm.get(x, 0.0) for x in fd))
    r_px = (entry - exit_px) / r_unit
    r_fund = fund * entry / r_unit
    r_cost = 2.0 * (COST_BPS / 1e4) * entry / r_unit
    return {
        "signal_d": d, "entry_d": DATES[j], "exit_d": DATES[exit_i],
        "entry": entry, "exit": exit_px, "atr14_d": a, "r_unit": r_unit,
        "stop": stop0, "target": target, "reason": reason, "hold_days": hold_days,
        "funding_sum": fund, "r_price": r_px, "r_fund": r_fund, "r_cost": r_cost,
        "r_net": r_px + r_fund - r_cost, "truncated": truncated,
    }


def run_tickets(signal_days: list[str], tp_atr: float = TP_ATR) -> list[dict]:
    """按时间顺序开票:已有一张票在场 ⇒ 不叠加。"""
    out: list[dict] = []
    open_until = ""
    skipped = 0
    for d in signal_days:
        if IDX[d] + 1 >= n:
            continue
        entry_d = DATES[IDX[d] + 1]
        if entry_d <= open_until:          # 上一张还在场
            skipped += 1
            continue
        t = simulate(d, tp_atr=tp_atr)
        if t is None:
            continue
        out.append(t)
        open_until = t["exit_d"]
    run_tickets.skipped_overlap = skipped  # type: ignore[attr-defined]
    return out


def sleeve_nav(tks: list[dict], day_start: str, day_end: str) -> tuple[list[str], np.ndarray]:
    """逐日盯市 NAV(每票风险 0.5% 净值,名义 ≤ 净值 50%)—— 与 S-736 同口径。"""
    days = [d for d in DATES if day_start <= d <= day_end]
    cash = 1.0
    open_t: dict | None = None
    nav = []
    for d in days:
        i = IDX[d]
        if open_t is not None and IDX[open_t["exit_d"]] == i:
            t = open_t
            pnl = t["notional"] * (t["entry"] - t["exit"]) / t["entry"]
            fund_cash = t["notional"] * sum(t["_fund_day"].get(dd, 0.0)
                                            for dd in DATES[IDX[t["entry_d"]]:i + 1])
            cash += pnl + fund_cash - t["notional"] * (COST_BPS / 1e4)
            t["_pnl_cash"] = pnl
            t["_fund_cash"] = fund_cash
            open_t = None
        if open_t is None:
            for t in tks:
                if t["entry_d"] == d:
                    notional = min(RISK_PCT * cash / (t["r_unit"] / t["entry"]), MAX_NOTIONAL * cash)
                    t["notional"] = notional
                    t["equity_at_entry"] = cash
                    cash -= notional * (COST_BPS / 1e4)
                    open_t = t
                    break
        unreal = 0.0
        if open_t is not None:
            t = open_t
            unreal += t["notional"] * (t["entry"] - CLOSE[i]) / t["entry"]
            unreal += t["notional"] * sum(t["_fund_day"].get(dd, 0.0)
                                          for dd in DATES[IDX[t["entry_d"]]:i + 1])
        nav.append(cash + unreal)
    return days, np.array(nav)


# ───────────────────────────── 自检:S-736 复现 ─────────────────────────────
print("[3/8] 自检:复现 S-736 的 18 张票…", flush=True)
dvol: dict[str, float] = {}
_dp = DVOL_CACHE / "deribit_dvol_btc_daily.json"
if not _dp.exists():
    raise SystemExit(f"拿不到 DVOL 缓存 {_dp}")
dvol.update({k: float(v) for k, v in json.loads(_dp.read_text()).items()})
dv_days = sorted(dvol)
dv_vals = np.array([dvol[d] for d in dv_days], dtype=float)
dv_idx = {d: i for i, d in enumerate(dv_days)}


def dvol_pct(d: str) -> float | None:
    i = dv_idx.get(d)
    if i is None:
        return None
    lo = (dt.date.fromisoformat(d) - dt.timedelta(days=365)).isoformat()
    j = int(np.searchsorted(dv_days, lo, side="left"))
    w = dv_vals[j:i]
    if w.size == 0:
        return None
    return float(np.sum(w <= dv_vals[i]) / w.size)


det_days = sorted(det)
det_exp_p20: dict[str, float] = {}
_buf: list[float] = []
for d in det_days:
    _buf.append(det[d])
    if len(_buf) >= MIN_OBS:
        det_exp_p20[d] = float(np.percentile(np.asarray(_buf, dtype=float), 20))


def trig_px(d: str) -> bool:
    i = IDX[d]
    return bool(not math.isnan(ma20[i]) and CLOSE[i] < ma20[i])


sig736: list[str] = []
elig_px_all: list[str] = []
for d in DATES:
    if not (dv_days[0] <= d <= dv_days[-1]):
        continue
    if trig_px(d):
        elig_px_all.append(d)
    liq = (phase.get(d) == "turning") or (
        d in det_exp_p20 and det.get(d) is not None and det[d] <= det_exp_p20[d])
    ok_dv, _q = (False, None)
    q = dvol_pct(d)
    if q is not None:
        ok_dv = q >= 0.70
    if liq and ok_dv and trig_px(d):
        sig736.append(d)
tickets736 = run_tickets(sig736)
avg736 = float(np.mean([t["r_net"] for t in tickets736])) if tickets736 else None

ref_path = HERE / "t256_results.json"
ref = json.loads(ref_path.read_text())
ref_days = [t["signal_d"] for t in ref["tickets"]]
ref_avg = float(ref["summary"]["avg_r_net"])
selfcheck = {
    "reference": "docs/research/t256_results.json(S-736 结果,lane-a T-256)",
    "ref_n_tickets": int(ref["summary"]["n_tickets"]), "ref_avg_r_net": ref_avg,
    "repro_n_tickets": len(tickets736), "repro_avg_r_net": avg736,
    "repro_signal_days": [t["signal_d"] for t in tickets736],
    "ref_signal_days": ref_days,
    "signal_days_identical": [t["signal_d"] for t in tickets736] == ref_days,
    "avg_diff": (avg736 - ref_avg) if (avg736 is not None and ref_avg is not None) else None,
    "n_signal_days_736": len(sig736),
    "dvol_window": [dv_days[0], dv_days[-1]],
}
ok_self = (selfcheck["repro_n_tickets"] == selfcheck["ref_n_tickets"]
           and selfcheck["avg_diff"] is not None and abs(selfcheck["avg_diff"]) < 0.02)
selfcheck["ok"] = bool(ok_self)
print(f"  S-736 自检:复现 {len(tickets736)} 张(参考 {ref_days and len(ref_days)} 张),"
      f"平均净 R {avg736:.4f}(参考 {ref_avg:.4f}),逐位一致={selfcheck['signal_days_identical']}",
      flush=True)

# ───────────────────────────── S-809 触发 ─────────────────────────────
print("[4/8] 找过热日与触发日…", flush=True)
hot: list[str] = []
hot_detail: dict[str, dict] = {}
for d in DATES:
    ds = pd.Timestamp(d)
    if ds not in fng7.index or ds not in fund7ann.index:
        continue
    fv, uv = fng7.loc[ds], fund7ann.loc[ds]
    if pd.isna(fv) or pd.isna(uv):
        continue
    pf = p85_fng.get(d)
    pu = p85_fund.get(d)
    if pf is None or pu is None:
        continue
    if fv >= pf and uv >= pu:
        hot.append(d)
        hot_detail[d] = {"fng7": float(fv), "fng_p85": pf, "fund7ann": float(uv),
                         "fund_p85": pu}
print(f"  过热日 {len(hot)} 天:{hot[:3]} … {hot[-3:] if hot else ''}", flush=True)

# 机制诊断:两个分量各自的热度(为什么某些年份没有过热日)
comp: dict[str, dict] = {}
for d in DATES:
    ds = pd.Timestamp(d)
    if ds not in fng7.index or ds not in fund7ann.index:
        continue
    pf = p85_fng.get(d)
    pu = p85_fund.get(d)
    if pf is None or pu is None:
        continue
    fv, uv = fng7.loc[ds], fund7ann.loc[ds]
    if pd.isna(fv) or pd.isna(uv):
        continue
    y = d[:4]
    c = comp.setdefault(y, {"days": 0, "fng_hot": 0, "fund_hot": 0, "both": 0,
                             "max_fng_ratio": 0.0, "max_fund_ratio": 0.0,
                             "max_fng7": None, "max_fund7ann": None})
    c["days"] += 1
    c["fng_hot"] += int(fv >= pf)
    c["fund_hot"] += int(uv >= pu)
    c["both"] += int(fv >= pf and uv >= pu)
    c["max_fng_ratio"] = max(c["max_fng_ratio"], float(fv / pf) if pf else 0.0)
    c["max_fund_ratio"] = max(c["max_fund_ratio"], float(uv / pu) if pu else 0.0)
    c["max_fng7"] = float(fv) if c["max_fng7"] is None else max(c["max_fng7"], float(fv))
    c["max_fund7ann"] = float(uv) if c["max_fund7ann"] is None else max(c["max_fund7ann"], float(uv))
for y, c in comp.items():
    c["fng_hot_pct"] = round(c["fng_hot"] / c["days"], 4) if c["days"] else None
    c["fund_hot_pct"] = round(c["fund_hot"] / c["days"], 4) if c["days"] else None
print(f"  分量诊断:{json.dumps(comp, ensure_ascii=False)}", flush=True)

# 触发日:每个过热日之后 30 天内第一次收盘 < MA20
trig_map: dict[str, str] = {}          # 触发日 → 最早的那个过热日
trig_all_h: dict[str, list[str]] = {}
for h in hot:
    hi = IDX[h]
    for j in range(hi + 1, min(hi + TURN_WINDOW + 1, n)):
        d = DATES[j]
        if not math.isnan(ma20[j]) and CLOSE[j] < ma20[j]:
            trig_map.setdefault(d, h)
            trig_all_h.setdefault(d, []).append(h)
            break
trig_days = sorted(trig_map)
print(f"  触发日(去重){len(trig_days)} 天;多个过热日指向同一 d 的 {sum(1 for d in trig_days if len(trig_all_h.get(d, [])) > 1)} 天被合并",
      flush=True)

tickets = run_tickets(trig_days)
print(f"  票数(不叠加){len(tickets)}", flush=True)

# ── 逐票补充:过热日归属 / 山寨篮 ──
alt_df = pd.DataFrame(alt_rows)
alt_df["d"] = pd.to_datetime(alt_df["d"])
alt_df["ret"] = pd.to_numeric(alt_df["ret"], errors="coerce")
alt_piv = alt_df.pivot_table(index="d", columns="style", values="ret", aggfunc="last").sort_index()
alt_got = [s for s in ALT_STYLES if s in alt_piv.columns]
alt_ew = alt_piv[alt_got].mean(axis=1).fillna(0.0)      # 五板块等权日收益
alt_nav = (1.0 + alt_ew).cumprod()
alt_dates = list(alt_nav.index.strftime("%Y-%m-%d"))
alt_idx = {d: i for i, d in enumerate(alt_dates)}


def alt_short_pct(entry_d: str, exit_d: str) -> float | None:
    """做空山寨等权篮在 [进场日, 出场日] 的收益(%)(多空方向:篮跌 ⇒ 空单赚)。"""
    if entry_d not in alt_idx or exit_d not in alt_idx:
        return None
    a, b = alt_idx[entry_d], alt_idx[exit_d]
    if b <= a:
        return None
    return float(-(float(alt_nav.iloc[b]) / float(alt_nav.iloc[a]) - 1.0))


for t in tickets:
    t["overheat_h"] = trig_map.get(t["signal_d"], "")
    t["overheat_h_all"] = "|".join(trig_all_h.get(t["signal_d"], []))
    t["alt_short_pct"] = alt_short_pct(t["entry_d"], t["exit_d"])
    t["alt_short_r_equiv"] = (None if t["alt_short_pct"] is None
                               else t["alt_short_pct"] / (t["r_unit"] / t["entry"]))

# ───────────────────────────── 判据 ─────────────────────────────
print("[5/8] 判据…", flush=True)
res: dict = {"prereg": PREREG, "s809_verbatim": S809_VERBATIM,
             "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
res["data"] = {
    "bars": n, "bar_range": [DATES[0], DATES[-1]], "perp_dup_rows": n_dup,
    "fng_rows": len(fng_rows), "fng_range": [str(fng_s.index.min().date()), str(fng_s.index.max().date())],
    "funding_days": len(fund_bn),
    "funding_range": [min(fund_bn), max(fund_bn)],
    "alt_rows": len(alt_rows), "alt_styles_used": alt_got,
    "alt_range": [alt_dates[0], alt_dates[-1]],
    "cycle_rows": len(cyc), "phase_rows": len(phase), "deterioration_rows": len(det),
    "dvol_rows": len(dv_days), "dvol_window": [dv_days[0], dv_days[-1]],
    "overheat_days": len(hot), "overheat_first": hot[0] if hot else None,
    "overheat_last": hot[-1] if hot else None,
    "trigger_days": len(trig_days),
    "trigger_days_dedup_merged": sum(1 for d in trig_days if len(trig_all_h.get(d, [])) > 1),
    "signal_skipped_overlap": getattr(run_tickets, "skipped_overlap", None),
    "overheat_by_year": {y: sum(1 for d in hot if d[:4] == y) for y in sorted({d[:4] for d in hot})},
}
res["selfcheck_s736"] = selfcheck
res["component_diagnostic"] = comp
res["overheat_detail"] = hot_detail
res["trigger_map"] = trig_map
res["tickets"] = tickets

n_tickets = len(tickets)
avg_r = float(np.mean([t["r_net"] for t in tickets])) if tickets else None
avg_r_px = float(np.mean([t["r_price"] for t in tickets])) if tickets else None
res["summary"] = {
    "n_tickets": n_tickets,
    "avg_r_net": avg_r, "avg_r_price": avg_r_px,
    "median_r_net": float(np.median([t["r_net"] for t in tickets])) if tickets else None,
    "win_rate": float(np.mean([t["r_net"] > 0 for t in tickets])) if tickets else None,
    "total_r_net": float(np.sum([t["r_net"] for t in tickets])) if tickets else None,
    "reasons": {r: sum(1 for t in tickets if t["reason"] == r) for r in ("止盈", "保本", "止损", "时间")},
}

# (a) 票数
verdict_a = n_tickets >= 15
res["judge_a"] = {"rule": "票数 ≥ 15(不足只报不判)", "n_tickets": n_tickets,
                  "pass": bool(verdict_a), "note": ("票数达标,全条判" if verdict_a
                                                   else "票数不足 ⇒ 只报不判(其余仍报数)")}

# (b) 平均 R > 0 且 ab_test 对 0 p < 0.10(逐日 NAV 口径,与 S-736 同)
eval_start = hot[0] if hot else DATES[0]
eval_end = DATES[-1]
for t in tickets:
    t["_fund_day"] = {dd: fund_bn.get(dd, 0.0) for dd in DATES[IDX[t["entry_d"]]:IDX[t["exit_d"]] + 1]}
_days, _nav = sleeve_nav(tickets, eval_start, eval_end)
_rets = pd.Series(_nav, index=pd.Index(_days)).pct_change().fillna(0.0).to_numpy()
ab = ab_test(np.zeros_like(_rets), _rets, mean_block=20.0, n_boot=2000, seed=SEED)
res["ab_vs_zero"] = ab
p_b = ab.get("p_b_le_a")
judge_b_mean = (avg_r is not None and avg_r > 0)
judge_b_p = (p_b is not None and p_b < 0.10)
res["judge_b"] = {"rule": "平均净 R > 0 且 ab_test(对照臂=0)p < 0.10",
                  "avg_r_net": avg_r, "p_b_le_a": p_b, "n_days": ab.get("n_days"),
                  "pass": bool(judge_b_mean and judge_b_p),
                  "note": "门槛 p<0.10 为原文写死(相对 S-736 的 0.05 已是那一档放宽),不二次放宽"}

# 票级符号翻转(辅助;均值不变的块置换在这里退化)
r_tickets = [t["r_net"] for t in tickets]
if len(r_tickets) >= 4:
    try:
        arr = np.asarray(r_tickets, dtype=float)

        def _flip(rng: np.random.Generator) -> float:
            return float(np.mean(arr * rng.choice([-1.0, 1.0], size=arr.size)))

        _null = null_distribution(_flip, 2000, SEED + 1, actual=avg_r)
        res["ticket_signflip_p"] = percentile_of(avg_r, _null)
        res["ticket_signflip_note"] = "辅助统计:票级符号翻转随机化(零假设 = 均值 0);判据 (b) 以 ab_test 为准"
    except NoOpNull as e:  # noqa: PERF203
        res["ticket_signflip_p"] = None
        res["ticket_signflip_why"] = str(e)

# (c) 随机对照
print("[6/8] 随机对照…", flush=True)
pool = [d for d in DATES if eval_start <= d <= eval_end and trig_px(d) and IDX[d] + 1 < n]


def draw_overlap_free(rng: np.random.Generator) -> float:
    order = rng.permutation(len(pool))
    got: list[dict] = []
    last_exit = ""
    for j in order:
        d = pool[int(j)]
        if len(got) >= n_tickets:
            break
        entry_d = DATES[IDX[d] + 1]
        if entry_d <= last_exit:
            continue
        t = simulate(d)
        if t is None:
            continue
        got.append(t)
        last_exit = t["exit_d"]
    if not got:
        return float("nan")
    return float(np.mean([t["r_net"] for t in got]))


def draw_independent(rng: np.random.Generator) -> float:
    pick = rng.choice(len(pool), size=min(n_tickets, len(pool)), replace=False)
    tks = [simulate(pool[int(j)]) for j in np.atleast_1d(pick)]
    tks = [t for t in tks if t]
    if not tks:
        return float("nan")
    return float(np.mean([t["r_net"] for t in tks]))


null_of: dict[str, object] = {}
for name, fn in (("overlap_free", draw_overlap_free), ("independent", draw_independent)):
    try:
        arr = null_distribution(fn, N_NULL, SEED, actual=avg_r)
        arr = arr[np.isfinite(arr)]
        null_of[name] = {
            "n_draws": int(arr.size),
            "mean": float(arr.mean()) if arr.size else None,
            "p90": float(np.percentile(arr, 90)) if arr.size else None,
            "p95": float(np.percentile(arr, 95)) if arr.size else None,
            "pctl_of_actual": percentile_of(avg_r, arr) if arr.size else None,
        }
    except NoOpNull as e:  # noqa: PERF203
        null_of[name] = {"why": str(e)}
res["null_control"] = {
    "pool_days": len(pool), "n_draws": N_NULL, "seed": SEED,
    "window": [eval_start, eval_end],
    "mean_r_net_actual": avg_r,
    "variants": null_of,
    "rule": "实际平均净 R ≥ 对照 90 分位(主口径 = 贪心不重叠)",
}
prim = null_of.get("overlap_free", {})
judge_c = (avg_r is not None and prim.get("pctl_of_actual") is not None
           and prim["pctl_of_actual"] >= 0.90)
res["judge_c"] = {"rule": "实际平均净 R ≥ 随机对照 90 分位(主口径:贪心不重叠)",
                  "actual_avg_r_net": avg_r, "null_p90": prim.get("p90"),
                  "pctl_of_actual": prim.get("pctl_of_actual"),
                  "pass": bool(judge_c)}

# (d) 留一(|R| 最大的一张)
if tickets:
    k = int(np.argmax([abs(t["r_net"]) for t in tickets]))
    loo_mean = float(np.mean([t["r_net"] for j, t in enumerate(tickets) if j != k]))
    judge_d = loo_mean > 0
    res["judge_d"] = {"rule": "对 |净 R| 最大的一张留一,平均净 R 仍 > 0",
                      "dropped_signal_d": tickets[k]["signal_d"], "dropped_r_net": tickets[k]["r_net"],
                      "loo_avg_r_net": loo_mean, "pass": bool(judge_d)}
else:
    res["judge_d"] = {"rule": "留一", "pass": False, "why": "没有票"}

# (e) 逐期
periods = [("2020–21", "2020-01-01", "2022-01-01"), ("2022", "2022-01-01", "2023-01-01"),
           ("2023–24", "2023-01-01", "2025-01-01"), ("2025–26", "2025-01-01", "2027-01-01")]
per = []
for lab, lo, hi in periods:
    sub = [t for t in tickets if lo <= t["signal_d"] < hi]
    per.append({
        "period": lab, "n": len(sub),
        "avg_r_net": float(np.mean([t["r_net"] for t in sub])) if sub else None,
        "avg_r_price": float(np.mean([t["r_price"] for t in sub])) if sub else None,
        "win_rate": float(np.mean([t["r_net"] > 0 for t in sub])) if sub else None,
        "total_r_net": float(np.sum([t["r_net"] for t in sub])) if sub else 0.0,
    })
res["periods"] = per
worst_period = min((p["avg_r_net"] for p in per if p["avg_r_net"] is not None), default=None)
res["judge_e"] = {"rule": "逐期报(原文无数值门槛);辅助按 S-736 同一把尺:任一期平均净 R < −0.3 ⇒ ❌",
                  "pass_primary": True, "worst_period_avg_r_net": worst_period,
                  "pass_s736_ruler": bool(worst_period is not None and worst_period >= -0.3)}

# 副:山寨等权篮(只报)
alt_vals = [t["alt_short_pct"] for t in tickets if t.get("alt_short_pct") is not None]
alt_r = [t["alt_short_r_equiv"] for t in tickets if t.get("alt_short_r_equiv") is not None]
res["alt_basket"] = {
    "rule": "同触发下做空 ① 山寨等权篮(五板块 equal-weight)的平均收益(只报)",
    "n": len(alt_vals),
    "avg_short_pct": float(np.mean(alt_vals)) if alt_vals else None,
    "median_short_pct": float(np.median(alt_vals)) if alt_vals else None,
    "win_rate": float(np.mean([x > 0 for x in alt_vals])) if alt_vals else None,
    "avg_r_equivalent": float(np.mean(alt_r)) if alt_r else None,
    "styles": alt_got,
}

# ── 总判定 ──
only_report = not verdict_a
judges = {"a": res["judge_a"], "b": res["judge_b"], "c": res["judge_c"],
          "d": res["judge_d"], "e": res["judge_e"]}
all_pass = all(bool(j.get("pass")) for j in judges.values())
res["verdicts"] = {k: bool(v.get("pass")) for k, v in judges.items()}
res["only_report"] = bool(only_report)
res["overall"] = {
    "verdict": ("只报不判(票数 < 15)" if only_report else ("✅ 全过" if all_pass else "❌ 未全过")),
    "all_pass": bool(all_pass), "only_report": bool(only_report),
    "trial_count": "做空族 +1",
}

# ───────────────────────────── 产物 ─────────────────────────────
print("[7/8] 写产物…", flush=True)
(HERE / "t333_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2))
csv_path = HERE / "t333_tickets.csv"
cols = ["signal_d", "overheat_h", "overheat_h_all", "entry_d", "exit_d", "entry", "exit",
        "atr14_d", "r_unit", "stop", "target", "reason", "hold_days", "funding_sum",
        "r_price", "r_fund", "r_cost", "r_net", "alt_short_pct", "alt_short_r_equiv"]
with csv_path.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for t in tickets:
        w.writerow({k: t.get(k) for k in cols})
print(f"  写了 {csv_path.name}({len(tickets)} 行)", flush=True)

print("[8/8] 结论…", flush=True)
print(f"  自检 S-736:{'✅' if selfcheck['ok'] else '❌'} "
      f"复现 {selfcheck['repro_n_tickets']} 张 / 平均 {selfcheck['repro_avg_r_net']} "
      f"(参考 {selfcheck['ref_n_tickets']} 张 / {selfcheck['ref_avg_r_net']:.4f})", flush=True)
print(f"  过热日 {len(hot)} → 触发日 {len(trig_days)} → 票 {n_tickets}", flush=True)
print(f"  平均净 R {avg_r} / p(b≤0) {p_b} / 随机对照分位 "
      f"{res['judge_c'].get('pctl_of_actual')} / 留一 {res['judge_d'].get('loo_avg_r_net')}",
      flush=True)
print(f"  总判定: {res['overall']['verdict']}", flush=True)
