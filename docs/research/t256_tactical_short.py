"""T-256 —— 战术空单回放(S-736 预注册):条件出现才开、到目标就撤、浮盈保本。

**卡上的 acceptance 就是下面的 PREREG;先写下来再算,只算一次,不挑量、不挑参数。**

用法:python3 docs/research/t256_tactical_short.py
产物:docs/research/T-256_tactical_short.md + docs/research/t256_results.json
数据:只读 Supabase + Deribit DVOL 缓存;缓存目录 /Volumes/CometCloudAI/cometcloud-local/research/t256。
纪律:不改代码、不做 DDL、不入库;零分布/盈亏只用 src/data/evaluation/apparatus.py。
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))

from src.data.evaluation.apparatus import (  # noqa: E402
    NoOpNull,
    ab_test,
    null_distribution,
    percentile_of,
)

U = os.environ["SUPABASE_URL"]
K = os.environ["SUPABASE_KEY"]
H = {"apikey": K, "Authorization": "Bearer " + K, "Prefer": "count=exact"}
CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/research/t256")
DVOL_CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/_cache/t229")

COST_BPS = 7.5            # 每次开 / 关 7.5bp
STOP_ATR = 1.5            # 止损 = 进场价 + 1.5 × ATR14(d)
TP_ATR = 2.5              # 止盈 = 进场价 − 2.5 × ATR14(d)  ⇒ 目标 +1.67R
TIME_STOP = 15            # 时间止损 15 根
RISK_PCT = 0.005          # 每票风险 0.5% 净值
MAX_NOTIONAL = 0.50       # 名义 ≤ 净值 50%
DVOL_TRIG = 0.70          # DVOL 一年分位触发线
DET_PCT = 20              # 恶化分扩张 20 分位
MIN_DET_OBS = 250         # 扩张分位最少观测数
SEED = 736
N_NULL = 1000
MA_N = 20
ATR_N = 14

PREREG = """# T-256 —— 战术空单回放(S-736 预注册,先写下来再算)

**问题(Jazz 11-06)**「不是长期开着……赚到目标收益就要撤,不可以亏钱」—— T-252 问错了问题。
本卡把空腿做成**一张票**:条件出现才开、到目标就撤、浮盈之后保本。

**窗口**:信号日 d 从 2021-03-24(DVOL 起点)到 2026-10-31(DVOL 最后一天);bar 来自
`perp_bv_daily`(Binance U 本位永续 BTCUSDT,2019-12-31 → 2026-11-04)。

**触发(d 日收盘,三条同时满足,全部只用 d 及之前的数据):**
① 流动性变差:`cycle_vector_daily.phase = turning`,**或** `deterioration` ≤ 截至 d 的**扩张 20 分位**
   (扩张窗口 = 截至 d 的全部恶化分观测,线性插值分位;观测数 ≥ 250 才可用;**不用全样本分位**);
② 不确定性:BTC DVOL 一年分位 ≥ 0.70(分位 = 过去 365 日(不含当日)观测里 ≤ 当日值的比例,
   分母 = 窗口内实际观测数;当天没有 DVOL ⇒ 不触发);
③ 价格确认:BTC 永续收盘 < 20 日均线(MA20 含当日)。**已有一张票在场 ⇒ 不叠加**(下一张票的进场日
   必须晚于上一张的出场日)。

**票(BTCUSDT 永续):** d+1 开盘进空;ATR14(d) = Wilder RMA(TR),TR 用 h/l 与前收;
止损 = 进场价 + 1.5×ATR14(d);止盈 = 进场价 − 2.5×ATR14(d)(到价即平,目标 +1.667R);
R 单位 = 1.5×ATR14(d);**浮盈达 +1R(价 ≤ 进场价 − R 单位)后止损移到进场价(保本)**;
时间止损 15 根(第 15 根收盘平);**同一根 bar 既碰止损又碰止盈 ⇒ 按止损算(保守)**;
跳空开盘越过止损 ⇒ 按开盘价成交(更差);跳空开盘越过止盈 ⇒ 按开盘价成交(更好);
同一根 bar 内先触及 +1R 又回到进场价 ⇒ 保守按保本出场(0R)。
成本 7.5bp × 2;资金费按持有期实计(空方收正费率),日合计 = Binance `v_funding_daily`
(funding_rate × n 求和),HL `hl_funding_hourly` 作对照口径。
每票风险 0.5% 净值,名义 = 0.5%×净值 ÷(1.5×ATR/进场价),截到 ≤ 净值 50%。

**R 的口径(写死):** 价格 R = (进场价 − 出场价) ÷ R 单位;净 R = 价格 R + 资金费 R − 成本 R
(成本 R = 2×7.5bp×进场价 ÷ R 单位;资金费 R = 持有期日资金费合计 × 进场价 ÷ R 单位)。
**判据 (a)–(e) 全部用净 R 判**(价格 R 同时报出来);最差单票的下限 −1.2R 因此含成本与跳空。

**判据(全部满足才 ✅;✅ ⇒ 开纸面臂 short_tactical,不动钱;动钱另由 Jazz 定):**
(a) 票数 ≥ 20(不足 ⇒ 只报不判);(b) 平均净 R > 0 且块自助(`apparatus.ab_test`,对照臂 = 0)p < 0.05;
(c) 随机对照:同样的出场规则、同等票数的随机进场日(1,000 次,种子 736,**只在 ③ 价格确认成立的日子里抽**),
    随机臂用同一套出场规则与同一票数(贪心不重叠),平均净 R ≥ 对照 95 分位 —— 否则「条件」没有用;
(d) 最长连亏 ≤ 5 张、最差单票 ≥ −1.2R;(e) 逐期(2021 / 2022 / 2023-24 / 2025-26)报,任一期平均净 R < −0.3 ⇒ ❌。
**副(只报不判):** ①(majors 指数长持)叠加本战术空腿后的回撤削减;止盈 2.0 / 3.0 ATR 两个敏感度。

**诚实:** 「不可以亏钱」做不到 —— 止损单会被触发、跳空会穿止损。这条规则做的是把每张票的亏损封在
−1R 附近、浮盈之后封到 0,判据 (d) 把这一点写成可检验的数。

**试验计数:④ 空头族 +1(T-252 为描述,不计)。**
"""


# ───────────────────────────── 数据 ─────────────────────────────
def pull(table: str, query: str, step: int = 1000) -> list[dict]:
    rows: list[dict] = []
    off, total = 0, -1
    while True:
        h = dict(H)
        h["Range"] = f"{off}-{off + step - 1}"
        req = urllib.request.Request(f"{U}/rest/v1/{table}?{query}", headers=h)
        with urllib.request.urlopen(req, timeout=300) as resp:
            cr = resp.headers.get("Content-Range", "")
            body = json.loads(resp.read())
        rows.extend(body)
        if "/" in cr:
            total = int(cr.split("/")[-1])
        off += len(body)
        if not body or total < 0 or off >= total:
            break
    return rows


def load(name: str, table: str, query: str) -> list[dict]:
    p = CACHE / f"{name}.json"
    if p.exists():
        rows = json.loads(p.read_text())
        print(f"  cache {name}: {len(rows)} rows")
        return rows
    rows = pull(table, query)
    CACHE.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows))
    print(f"  pulled {name}: {len(rows)} rows")
    return rows


def dvol_daily() -> dict[str, float]:
    """Deribit DVOL 日线 close。复用 T-229 的缓存(同一个上游、同一个口径)+ 现抓一遍补到最新完整日。"""
    out: dict[str, float] = {}
    p = DVOL_CACHE / "deribit_dvol_btc_daily.json"
    if p.exists():
        out.update({k: float(v) for k, v in json.loads(p.read_text()).items()})
        print(f"  dvol 缓存 {p}: {len(out)} 行")
    url = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
    fresh: dict[str, float] = {}
    a = dt.date(2021, 1, 1)
    end = dt.date.today()
    try:
        while a <= end:
            b = min(a + dt.timedelta(days=364), end)
            q = (f"?currency=BTC&resolution=1D&start_timestamp={int(dt.datetime.combine(a, dt.time(), dt.timezone.utc).timestamp() * 1000)}"
                 f"&end_timestamp={int(dt.datetime.combine(b, dt.time(23, 59), dt.timezone.utc).timestamp() * 1000)}")
            req = urllib.request.Request(url + q, headers={"User-Agent": "cometcloud-research/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                res = json.loads(resp.read()).get("result") or {}
            for row in res.get("data") or []:
                if isinstance(row, (list, tuple)) and len(row) >= 5:
                    day = dt.datetime.fromtimestamp(int(row[0]) / 1000, tz=dt.timezone.utc).date().isoformat()
                    fresh[day] = float(row[4])
            a = b + dt.timedelta(days=1)
        out.update(fresh)
        print(f"  dvol 现抓: {len(fresh)} 行,合并后 {len(out)} 行")
    except Exception as e:  # noqa: BLE001
        print(f"  dvol 现抓失败({type(e).__name__}),只用缓存")
    if not out:
        raise SystemExit("拿不到 DVOL")
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "deribit_dvol_btc_daily_merged.json").write_text(json.dumps(out))
    return out


print("[1/7] 读数据…", flush=True)
perp = load("perp_btc", "perp_bv_daily",
            "select=d,o,h,l,c,pair,symbol,recorded_at&pair=eq.BTCUSDT&order=d.asc,recorded_at.asc")
cyc = load("cycle", "cycle_vector_daily",
           "select=d,phase,deterioration,shift,shift_pct,n_components&order=d.asc")
vf = load("v_funding_btc", "v_funding_daily",
          "select=d,symbol,funding_rate,n&symbol=eq.BTC&order=d.asc,symbol.asc")
hl = load("hl_funding_btc", "hl_funding_hourly", "select=t,coin,rate,premium&coin=eq.BTC&order=t.asc")
sty = load("style_majors", "style_index_pit_daily",
           "select=d,level,ret,style,weighting,dimension,members,n_members,computed_at"
           "&style=eq.majors&weighting=eq.cap&order=d.asc")
dvol = dvol_daily()

bars: list[dict] = []
for r in perp:
    if any(r.get(k) is None for k in ("o", "h", "l", "c")):
        continue
    bars.append({"d": str(r["d"])[:10], "o": float(r["o"]), "h": float(r["h"]),
                 "l": float(r["l"]), "c": float(r["c"])})
bars.sort(key=lambda x: x["d"])
assert len(bars) == len({b["d"] for b in bars}), "perp 有重复日"
DATES = [b["d"] for b in bars]
IDX = {d: i for i, d in enumerate(DATES)}
OPEN = np.array([b["o"] for b in bars], dtype=float)
HIGH = np.array([b["h"] for b in bars], dtype=float)
LOW = np.array([b["l"] for b in bars], dtype=float)
CLOSE = np.array([b["c"] for b in bars], dtype=float)
print(f"  bars: {len(bars)} {DATES[0]} → {DATES[-1]}")

# 资金费:日合计
fund_bn: dict[str, float] = {}
for r in vf:
    dd = str(r["d"])[:10]
    n = int(r.get("n") or 1)
    fund_bn[dd] = fund_bn.get(dd, 0.0) + float(r["funding_rate"]) * n
fund_hl: dict[str, float] = {}
for r in hl:
    dd = str(r["t"])[:10]
    fund_hl[dd] = fund_hl.get(dd, 0.0) + float(r["rate"])

phase: dict[str, str] = {}
det: dict[str, float] = {}
for r in cyc:
    dd = str(r["d"])[:10]
    ph = r.get("phase")
    if ph:
        phase[dd] = str(ph)
    if r.get("deterioration") is not None:
        det[dd] = float(r["deterioration"])
print(f"  cycle: {len(cyc)} rows, phase 覆盖 {len(phase)}, 恶化分 {len(det)}")

# ── 指标(全部只用到 d 及之前) ──
print("[2/7] 算指标…", flush=True)
n = len(bars)
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

# DVOL 一年分位(过去 365 日,不含当日)
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


# 恶化分的扩张 20 分位(截至 d,线性插值)
det_days = sorted(det)
det_exp_p20: dict[str, float] = {}
buf: list[float] = []
for d in det_days:
    buf.append(det[d])
    if len(buf) >= MIN_DET_OBS:
        det_exp_p20[d] = float(np.percentile(np.asarray(buf, dtype=float), DET_PCT))
det_first_ok = min(det_exp_p20) if det_exp_p20 else None
print(f"  ATR14 首值 {DATES[ATR_N]};MA20 首值 {DATES[MA_N - 1]};"
      f" 扩张分位首日 {det_first_ok};DVOL {dv_days[0]} → {dv_days[-1]}")


def trig_liq(d: str) -> tuple[bool, str]:
    """① 流动性变差。"""
    if phase.get(d) == "turning":
        return True, "turning"
    p = det_exp_p20.get(d)
    if p is not None and det.get(d) is not None and det[d] <= p:
        return True, f"det<=p20({det[d]:.4f}<={p:.4f})"
    return False, ""


def trig_dvol(d: str) -> tuple[bool, float | None]:
    q = dvol_pct(d)
    if q is None:
        return False, None
    return q >= DVOL_TRIG, q


def trig_px(d: str) -> bool:
    i = IDX[d]
    return bool(not math.isnan(ma20[i]) and CLOSE[i] < ma20[i])


# ── 票 ─────────────────────────────
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


def run_tickets(signal_days: list[str], tp_atr: float = TP_ATR,
                fund_map: dict[str, float] | None = None) -> list[dict]:
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
        t = simulate(d, tp_atr=tp_atr, fund_map=fund_map)
        if t is None:
            continue
        out.append(t)
        open_until = t["exit_d"]
    run_tickets.skipped_overlap = skipped  # type: ignore[attr-defined]
    return out


# ── 触发 ─────────────────────────────
print("[3/7] 找信号日…", flush=True)
sig_all: list[str] = []
sig_reason: dict[str, str] = {}
elig_px: list[str] = []                   # ③ 成立的日子(随机对照的抽样池)
n_turn = n_det = 0
for d in DATES:
    if not (dv_days[0] <= d <= dv_days[-1]):
        continue
    ok_px = trig_px(d)
    if ok_px:
        elig_px.append(d)
    liq, why = trig_liq(d)
    if why == "turning":
        n_turn += 1
    elif why:
        n_det += 1
    ok_dv, q = trig_dvol(d)
    if liq and ok_dv and ok_px:
        sig_all.append(d)
        sig_reason[d] = why
print(f"  窗口 {dv_days[0]} → {dv_days[-1]};③ 成立 {len(elig_px)} 天;"
      f"① turning {n_turn} 天 / 恶化分分位 {n_det} 天;三条全中 {len(sig_all)} 天")
tickets = run_tickets(sig_all)
print(f"  票数(不叠加) {len(tickets)}")

# ── 断言 ─────────────────────────────
print("[4/7] 断言…", flush=True)
asserts: list[dict] = []


def chk(name: str, ok: bool, detail: str) -> None:
    asserts.append({"assertion": name, "ok": bool(ok), "detail": detail})


# A1 ATR 只用 d 及之前:for 每个信号日,重算一次只用前 d 根的 ATR,必须一致
bad = 0
for t in tickets:
    i = IDX[t["signal_d"]]
    tr2 = [max(HIGH[j] - LOW[j], abs(HIGH[j] - CLOSE[j - 1]), abs(LOW[j] - CLOSE[j - 1]))
           for j in range(1, i + 1)]
    if i < ATR_N:
        bad += 1
        continue
    a2 = float(np.mean(tr2[:ATR_N]))            # 种子在 bar 14
    for k in range(ATR_N, len(tr2)):            # Wilder RMA 递推
        a2 = (a2 * (ATR_N - 1) + tr2[k]) / ATR_N
    if abs(a2 - t["atr14_d"]) > 1e-9:
        bad += 1
chk("A1 ATR14(d) 只用 d 及之前的 bar", bad == 0, f"{len(tickets)} 张票重算,不一致 {bad} 张")

# A2 MA20 只含 d 及之前
bad = 0
for d in elig_px:
    i = IDX[d]
    m = float(np.mean(CLOSE[i - MA_N + 1:i + 1]))
    if abs(m - ma20[i]) > 1e-9:
        bad += 1
chk("A2 MA20 只含 d 及之前的收盘", bad == 0, f"{len(elig_px)} 天重算,不一致 {bad} 天")

# A3 DVOL 分位只用 (d−365, d)
bad = 0
for d in DATES:
    if d in dv_idx:
        q = dvol_pct(d)
        i = dv_idx[d]
        lo = (dt.date.fromisoformat(d) - dt.timedelta(days=365)).isoformat()
        j = int(np.searchsorted(dv_days, lo, side="left"))
        w = dv_vals[j:i]
        if w.size == 0:
            continue
        q2 = float(np.sum(w <= dv_vals[i]) / w.size)
        if q is None or abs(q - q2) > 1e-12:
            bad += 1
chk("A3 DVOL 一年分位只 (d−365, d) 的观测", bad == 0, f"不一致 {bad} 天")

# A4 扩张分位只用 d 及之前的恶化分 + 观测数 ≥ 250
bad = 0
for d, p in det_exp_p20.items():
    obs = [det[x] for x in det_days if x <= d]
    if len(obs) < MIN_DET_OBS:
        bad += 1
    elif abs(float(np.percentile(np.asarray(obs), DET_PCT)) - p) > 1e-9:
        bad += 1
chk("A4 恶化分扩张分位只用 d 及之前、观测 ≥ 250", bad == 0,
    f"{len(det_exp_p20)} 个分位点重算,不一致 {bad}")

# A5 进场 = d+1 开盘;出场 ≥ 进场;持有 ≤ 15 根
bad = 0
for t in tickets:
    i = IDX[t["signal_d"]]
    if abs(OPEN[i + 1] - t["entry"]) > 1e-9 or t["entry_d"] != DATES[i + 1]:
        bad += 1
    if IDX[t["exit_d"]] < i + 1 or t["hold_days"] > TIME_STOP:
        bad += 1
chk("A5 d+1 开盘进场、出场不早于进场、持有 ≤ 15 根", bad == 0, f"不一致 {bad} 张")

# A6 不重叠
ov = 0
for a, b in zip(tickets, tickets[1:]):
    if b["entry_d"] <= a["exit_d"]:
        ov += 1
chk("A6 场上只有一张票(不叠加)", ov == 0, f"重叠 {ov} 对")

# A7 每张票止损/止盈价由 ATR 定,R 单位 = 1.5 ATR
bad = 0
for t in tickets:
    if abs(t["r_unit"] - STOP_ATR * t["atr14_d"]) > 1e-9:
        bad += 1
    if abs(t["stop"] - (t["entry"] + t["r_unit"])) > 1e-9:
        bad += 1
    if abs(t["target"] - (t["entry"] - TP_ATR * t["atr14_d"])) > 1e-9:
        bad += 1
chk("A7 止损 = 进场 + 1.5ATR、止盈 = 进场 − 2.5ATR、R 单位 = 1.5ATR", bad == 0, f"不一致 {bad} 张")

# A8 每张票的出场原因与价格自洽
bad = 0
for t in tickets:
    if t["reason"] == "止盈" and t["exit"] > t["target"] + 1e-6:
        bad += 1
    if t["reason"] == "止损" and t["exit"] < t["stop"] - 1e-6:
        bad += 1
    if t["reason"] == "保本" and abs(t["exit"] - t["entry"]) > 1e-6:
        bad += 1
chk("A8 出场原因与出场价自洽(止盈 ≥ 目标价、止损 ≤ 止损价、保本 = 进场价)", bad == 0, f"不一致 {bad} 张")

for a in asserts:
    print(f"  [{'OK ' if a['ok'] else 'FAIL'}] {a['assertion']} — {a['detail']}")
assert all(a["ok"] for a in asserts), "断言没过,不出结论"

# ── 袖套 NAV(逐日盯市) ─────────────────────────────
def sleeve_nav(tks: list[dict]) -> tuple[list[str], np.ndarray, dict]:
    """返回 (日期, 每日 NAV, 明细)。每票风险 0.5% 净值(按进场当时的净值),名义 ≤ 净值 50%。"""
    day_start = dv_days[0]
    day_end = dv_days[-1]
    if tks:
        day_end = max(day_end, max(t["exit_d"] for t in tks))
    days = [d for d in DATES if day_start <= d <= day_end]
    cash = 1.0                     # 已实现权益(含已扣的往返成本)
    open_t: dict | None = None
    nav = []
    detail = {}
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
        detail[d] = {"cash": cash, "unreal": unreal}
    return days, np.array(nav), detail


# 资金费按日给到票上(持仓日 = 进场日 … 出场日)
for t in tickets:
    t["_fund_day"] = {dd: fund_bn.get(dd, 0.0) for dd in DATES[IDX[t["entry_d"]]:IDX[t["exit_d"]] + 1]}

print("[5/7] 判据…", flush=True)
res: dict = {"prereg": PREREG, "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
res["data"] = {
    "bars": len(bars), "bar_range": [DATES[0], DATES[-1]],
    "window": [dv_days[0], dv_days[-1]], "dvol_rows": len(dv_days),
    "cycle_rows": len(cyc), "phase_rows": len(phase), "deterioration_rows": len(det),
    "deterioration_p20_full_sample": float(np.percentile(np.asarray([det[x] for x in det_days]), DET_PCT)),
    "eligible_px_days": len(elig_px), "signal_days": len(sig_all),
    "days_liq_turning": n_turn, "days_liq_det_p20": n_det,
    "signal_turning": sum(1 for d in sig_all if sig_reason[d] == "turning"),
    "signal_det_p20": sum(1 for d in sig_all if sig_reason[d] != "turning"),
    "signal_skipped_overlap": getattr(run_tickets, "skipped_overlap", None),
    "signals_per_year": {y: sum(1 for d in sig_all if d[:4] == y) for y in sorted({d[:4] for d in sig_all})},
    "det_exp_p20_first": det_first_ok,
    "funding_days_bn": len(fund_bn), "funding_days_hl": len(fund_hl),
}
res["assertions"] = asserts
for t in tickets:
    t["trigger_reason"] = sig_reason.get(t["signal_d"], "")
    t["dvol_pct_1y"] = dvol_pct(t["signal_d"])
    t["dvol_close"] = dvol.get(t["signal_d"])

# (a) 票数
n_tickets = len(tickets)
res["tickets"] = tickets
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

# (b) 平均 R > 0 且块自助 p < 0.05 —— ab_test(对照臂 = 0)
days, nav, _ = sleeve_nav(tickets)
nav_s = pd.Series(nav, index=pd.Index(days))
rets = nav_s.pct_change().fillna(0.0).to_numpy()
ab = ab_test(np.zeros_like(rets), rets, mean_block=20.0, n_boot=2000, seed=SEED)
res["ab_vs_zero"] = ab
# 票级随机化(辅助):符号翻转零分布(均值不变的块置换在这里是退化的 —— 置换不改均值)
r_tickets = [t["r_net"] for t in tickets]
if len(r_tickets) >= 4:
    try:
        arr = np.asarray(r_tickets, dtype=float)

        def draw(rng):
            signs = rng.choice([-1.0, 1.0], size=arr.size)
            return float(np.mean(arr * signs))

        null = null_distribution(draw, 2000, SEED + 1, actual=avg_r)
        res["ticket_signflip_p"] = percentile_of(avg_r, null)
        res["ticket_signflip_note"] = "辅助统计:票级符号翻转随机化(零假设 = 均值 0);判据 (b) 以 ab_test 为准"
    except NoOpNull as e:  # noqa: PERF203
        res["ticket_signflip_p"] = None
        res["ticket_signflip_why"] = str(e)

# (c) 随机对照:同样出场规则、同等票数、只在 ③ 成立的日子里抽
print("[6/7] 随机对照…", flush=True)
pool = [d for d in elig_px if IDX[d] + 1 < n]
rng = np.random.default_rng(SEED)
null_means: list[float] = []
null_overlap_free: list[float] = []
for _ in range(N_NULL):
    # c1:独立抽样,不加不重叠约束
    pick = rng.choice(len(pool), size=min(n_tickets, len(pool)), replace=False)
    tks = [simulate(pool[int(j)]) for j in np.atleast_1d(pick)]
    tks = [t for t in tks if t]
    if tks:
        null_means.append(float(np.mean([t["r_net"] for t in tks])))
    # c2:贪心不重叠(与实际同构)
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
    if got:
        null_overlap_free.append(float(np.mean([t["r_net"] for t in got])))
null_arr = np.array(null_overlap_free)
null_ind = np.array(null_means)
res["null_control"] = {
    "pool_days": len(pool), "n_draws": N_NULL, "seed": SEED,
    "mean_r_net_actual": avg_r,
    "null_overlap_free_mean": float(null_arr.mean()) if null_arr.size else None,
    "null_overlap_free_p95": float(np.percentile(null_arr, 95)) if null_arr.size else None,
    "null_overlap_free_pctl_of_actual": percentile_of(avg_r, null_arr) if null_arr.size else None,
    "null_independent_mean": float(null_ind.mean()) if null_ind.size else None,
    "null_independent_p95": float(np.percentile(null_ind, 95)) if null_ind.size else None,
    "null_independent_pctl_of_actual": percentile_of(avg_r, null_ind) if null_ind.size else None,
}

# (d) 最长连亏、最差单票
loss_run = best_run = 0
for t in tickets:
    if t["r_net"] < 0:
        loss_run += 1
        best_run = max(best_run, loss_run)
    else:
        loss_run = 0
worst = min((t["r_net"] for t in tickets), default=None)
res["drawdown_of_tickets"] = {"max_consecutive_losses": best_run, "worst_ticket_r_net": worst}

# (e) 逐期
periods = [("2021", "2021-01-01", "2022-01-01"), ("2022", "2022-01-01", "2023-01-01"),
           ("2023-24", "2023-01-01", "2025-01-01"), ("2025-26", "2025-01-01", "2027-01-01")]
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

# ── 副(只报不判) ─────────────────────────────
print("[7/7] 副项…", flush=True)
# 副1:①(majors 长持)叠加战术空腿后的回撤削减
core = {}
for r in sty:
    if r.get("level") is not None:
        core[str(r["d"])[:10]] = float(r["level"])
core_days = [d for d in DATES if d in core]
if core_days:
    base = core[core_days[0]]
    core_nav = np.array([core[d] / base for d in core_days])
    sleeve_ret = pd.Series(nav, index=pd.Index(days)).pct_change().fillna(0.0)
    aligned = sleeve_ret.reindex(core_days).fillna(0.0).to_numpy()
    comb_nav = core_nav * np.cumprod(1.0 + aligned)

    def maxdd(x: np.ndarray) -> float:
        peak = np.maximum.accumulate(x)
        return float(np.min(x / peak - 1.0))

    res["side_hedge"] = {
        "core": "style_index_pit_daily style=majors weighting=cap (① 长持)",
        "core_range": [core_days[0], core_days[-1]],
        "core_maxdd": maxdd(core_nav),
        "core_total": float(core_nav[-1] - 1.0),
        "combined_maxdd": maxdd(comb_nav),
        "combined_total": float(comb_nav[-1] - 1.0),
        "dd_reduction_pp": (maxdd(core_nav) - maxdd(comb_nav)) * 100.0,
        "sleeve_total_ret": float(nav[-1] - 1.0),
        "sleeve_maxdd": maxdd(nav),
        "n_days": len(core_days),
    }

# 副2:止盈 2.0 / 3.0 ATR
sens = {}
for tp in (2.0, 3.0):
    tk = run_tickets(sig_all, tp_atr=tp)
    sens[f"tp_{tp}"] = {
        "n_tickets": len(tk),
        "avg_r_net": float(np.mean([t["r_net"] for t in tk])) if tk else None,
        "avg_r_price": float(np.mean([t["r_price"] for t in tk])) if tk else None,
        "win_rate": float(np.mean([t["r_net"] > 0 for t in tk])) if tk else None,
        "total_r_net": float(np.sum([t["r_net"] for t in tk])) if tk else None,
        "reasons": {r: sum(1 for t in tk if t["reason"] == r) for r in ("止盈", "保本", "止损", "时间")},
    }
res["sensitivity_tp"] = sens

# HL 资金费对照口径
tk_hl = run_tickets(sig_all, fund_map=fund_hl)
res["funding_sensitivity_hl"] = {
    "n_tickets": len(tk_hl),
    "avg_r_net_hl": float(np.mean([t["r_net"] for t in tk_hl])) if tk_hl else None,
    "avg_r_net_bn": avg_r,
}

# ── 判据判定 ─────────────────────────────
verdicts = {}
verdicts["(a) 票数 ≥ 20"] = {
    "ok": n_tickets >= 20, "value": n_tickets, "need": "≥ 20",
    "note": "" if n_tickets >= 20 else "票数不足 ⇒ 只报不判",
}
p_b = ab.get("p_b_le_a") if isinstance(ab, dict) else None
verdicts["(b) 平均净 R > 0 且块自助 p < 0.05"] = {
    "ok": bool(avg_r is not None and avg_r > 0 and p_b is not None and p_b < 0.05),
    "avg_r_net": avg_r, "p_b_le_a": p_b, "ab_verdict": ab.get("verdict") if isinstance(ab, dict) else None,
    "n_days": ab.get("n_days") if isinstance(ab, dict) else None,
    "cum_b": ab.get("cum_b") if isinstance(ab, dict) else None,
    "ticket_signflip_p": res.get("ticket_signflip_p"),
}
nc = res["null_control"]
verdicts["(c) 随机对照 ≥ 95 分位"] = {
    "ok": bool(nc["null_overlap_free_p95"] is not None and avg_r is not None
               and avg_r >= nc["null_overlap_free_p95"]),
    "actual_avg_r_net": avg_r, "null_p95": nc["null_overlap_free_p95"],
    "null_pctl_of_actual": nc["null_overlap_free_pctl_of_actual"],
    "independent_p95": nc["null_independent_p95"],
    "independent_pctl": nc["null_independent_pctl_of_actual"],
}
verdicts["(d) 最长连亏 ≤ 5、最差单票 ≥ −1.2R"] = {
    "ok": bool(best_run <= 5 and worst is not None and worst >= -1.2),
    "max_consecutive_losses": best_run, "worst_ticket_r_net": worst,
}
bad_periods = [p for p in per if p["avg_r_net"] is not None and p["avg_r_net"] < -0.3]
verdicts["(e) 逐期平均净 R ≥ −0.3"] = {
    "ok": not bad_periods, "bad_periods": [p["period"] for p in bad_periods], "periods": per,
}
res["verdicts"] = verdicts
res["overall"] = "✅ 全过(可开纸面臂 short_tactical,不动钱)" if all(v["ok"] for v in verdicts.values()) else \
    "❌ 未全过(不立臂)"

out_json = REPO / "docs/research/t256_results.json"
out_json.write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str))
print(f"\n写了 {out_json}")
print(json.dumps({"summary": res["summary"], "verdicts": verdicts}, ensure_ascii=False, indent=2, default=str))
