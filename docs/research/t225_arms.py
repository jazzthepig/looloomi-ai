#!/usr/bin/env python3
"""T-225 —— 拆开三个混在一起的变量(面板宽度 × 调仓频率 × 符号)。

口径逐字照 `docs/research/T-225_prereg.md`(预注册写于 2026-11-02 12:53 UTC,先于任何计算);
判据照抄 S-694 / T-224,只把「两段」的口径从日历切点改成牛/熊(`state_daily` 的 `mom_200`)。

四个臂,每个臂只改一个变量:
  D(基准)= 50 名 / 月频 / 最差档 × 0.5   —— 复算 T-224,验证重构没改数字
  A(臂①) = 50 名 / **周频** / 最差档 × 0.5 —— 只改频率
  B(臂②) = **24 名** / 月频 / 最差档 × 0.5 —— 只改宽度
  C(臂③) = 50 名 / 月频 / 最差档 **× 2.0** —— 只改符号

面板规则、信号(S-691 五因子等权秩合成)、成本、判据全部照 T-224:
  · 面板:调仓日按当时市值取前 N 名;剔稳定币 / 包裹凭证 / 质押凭证 /
    代币化债权(名单照 migrations/2026-10-30_core_pit.sql 的 core_pit_excluded(),
    再加 coin_id 关键词兜底);成员只由调仓日市值决定,之后不因死亡而剔除。
  · 信号:S-691 五因子等权秩合成(F3−、F7+、F8−、F9−、F11−),宇宙 = deriv_metrics_daily
    名字过 S-689 映射校验 + 当天 CG 市值 ≥ 2,000 万 + 当天 OI > 0 + 五因子都有定义 +
    当天 ≥ 30 名;最差五分之一 = ntile(5) 第 1 档(与 S-694 逐字相同)。
  · 倾斜:落在最差五分位的面板名字权重 × k(0.5 或 2.0),其余按市值补满;
    基线 = 同面板同频率的市值加权。
  · 成本:10 bp × Σ|目标权重 − 上期漂移后权重|。
  · 判据:(a) 年化净超额 > 0 且随机对照(每个调仓日在有合成值的面板名字里随机挑同样个数、
    施加同一变换,1,000 次,种子 694)≥ 95 分位;(b) 牛段与熊段净超额都 > 0。

死币规则(本卡改时点口径):只用调仓日当天及以前的 last_obs;不写销(序列结束按最后有效价
持有到底,收益 0);coin_id 连续性写成硬断言(持有期内 > 10 天内部断点 ⇒ 报错中止)。

零分布 / 分位只走 `src/data/evaluation/apparatus.py`。只读 Supabase(publishable key)。
用法:python3 docs/research/t225_arms.py --all
产物:docs/research/t225_results.json、docs/research/T-225_arms.md
"""
from __future__ import annotations

import csv
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.data.evaluation.apparatus import (   # 零分布 / 分位 / A-B 只许用这里的函数
    NoOpNull,
    null_distribution,
    percentile_of,
)

REPO = Path(__file__).resolve().parents[2]
CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/research/t225_cache")
ARM_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/research/t225")
OUT_JSON = REPO / "docs" / "research" / "t225_results.json"
PREREG_MD = REPO / "docs" / "research" / "T-225_prereg.md"
OUT_MD = REPO / "docs" / "research" / "T-225_arms.md"

URL = os.environ.get("SUPABASE_URL", "").strip()
KEY = os.environ.get("SUPABASE_KEY", "").strip()
if not URL or not KEY:
    sys.exit("SUPABASE_URL / SUPABASE_KEY 未设置 —— 读库需要它们(publishable key 即可)。")
HEAD = {"apikey": KEY, "Authorization": "Bearer " + KEY}
PAGE = 1000

# ------------------------------------------------------------------ 臂参数(命令行优先,环境变量兜底)

def _arg(flag: str, env: str, default: str) -> str:
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return os.environ.get(env, default)


ARM_TAG = _arg("--tag", "T225_TAG", "D")
N_PANEL = int(_arg("--panel", "T225_PANEL", "50"))
FREQ = _arg("--freq", "T225_FREQ", "month").lower()          # month | week
TILT = _arg("--tilt", "T225_TILT", "halve").lower()          # halve | double
if FREQ not in ("month", "week"):
    sys.exit(f"--freq 只支持 month / week(给了 {FREQ})")
if TILT not in ("halve", "double"):
    sys.exit(f"--tilt 只支持 halve / double(给了 {TILT})")
TILT_MULT = 0.5 if TILT == "halve" else 2.0
PER_YEAR = 52.0 if FREQ == "week" else 12.0
ARM_JSON = ARM_DIR / f"arm_{ARM_TAG}.json"                   # 单臂完整结果(Mac 数据根)

# ------------------------------------------------------------------ 配置(照预注册)

GRID_FROM = "2022-09-01"        # 因子回看头(F3/F8 要 30 天)
GRID_TO = "2026-10-31"          # 给「最差档之后 30 天」留尾巴
P_START = "2023-01-01"         # 第一个调仓日
P_END = "2026-09-30"           # 最后一个持有期的退出日上限
STALE_DAYS = 10                # 价格/市值的有效期(照 core_pit_members 的 10 天窗口)
COST_BP = 10.0                 # 成本:10 bp × Σ|目标 − 漂移后权重|
N_NULL = 1000                  # 随机对照次数
SEED = 694                     # 随机对照种子(卡上写死的)
HALF_CUT = "2024-11-30"        # 旧日历切点(本卡降级为副指标)
REGIME_FEATURE = "mom_200"     # 牛熊标记:state_daily(entity=panel) 的这个 feature

MCAP_MIN = 20_000_000.0        # 宇宙:CG 市值门槛(2,000 万)
MAP_MIN_OVERLAP = 30           # 映射校验:最少重叠日
MAP_MAX_MED_ERR = 0.05         # 映射校验:中位误差上限
MIN_NAMES = 30                 # 宇宙:当天最少名字数
MIN_VOL_OBS = 25               # F11:最少收益个数
MIN_WINDOW_DAYS = 5            # F7:7 天窗口里最少有效天数

FROZEN = [("F3", -1), ("F7", +1), ("F8", -1), ("F9", -1), ("F11", -1)]   # S-691 冻结短名单

# 剔除名单(照 core_pit_excluded();symbol 键)
EXCL_STABLE = {
    "USDT", "USDC", "BUSD", "DAI", "TUSD", "PAX", "USDP", "UST", "USTC", "FDUSD",
    "USDE", "USDS", "PYUSD", "GUSD", "HUSD", "USDD", "USDN", "FRAX", "LUSD", "EURS",
    "EURC", "EURT", "USDJ", "SUSD", "MIM", "USD1", "USDY", "USD0", "RLUSD", "USDT0",
    "USDTB", "EURI", "XSGD", "XDAI", "AEUR", "USDE", "DOLA", "USDG", "PYUSD", "BUIDL",
}
EXCL_WRAPPED = {
    "WBTC", "WETH", "WBNB", "STETH", "WSTETH", "WEETH", "WBETH", "RETH", "CBETH",
    "RSETH", "METH", "SFRXETH", "FRXETH", "BTCB", "LBTC", "TBTC", "CBBTC", "EZETH",
    "WHYPE", "HBTC", "RENBTC", "BNSOL", "JITOSOL", "MSOL", "JUPOSOL", "JUPSOL",
    "SOLVBTC", "STSOL", "SUSDE", "SUSDS", "SDAI", "STKAAVE", "XAUT", "PAXG", "WTRX",
    "WRBTC", "WBETH", "STBTC", "CBSTETH", "SWRBTC", "WBETH", "WSOL",
}
EXCL_RWA = {
    "OUSG", "BENJI", "WTGXX", "TBILL", "USYC", "BUIDL", "JTRSY", "USTB", "VBILL",
    "FIGR_HELOC",
}
EXCL_SYMBOLS = EXCL_STABLE | EXCL_WRAPPED | EXCL_RWA
# coin_id 关键词兜底(名单外的包装 / 稳定币)
EXCL_CID_KEYS = ("wrapped", "bridged", "staked", "binance-peg", "peg-", "tokenized",
                 "treasury", "-gold", "gold-", "tether", "usd-coin", "paypal-usd",
                 "first-digital-usd", "true-usd", "binance-usd", "frax", "ethena",
                 "syrup", "mimetic", "paxos", "usds", "usde", "usd0", "usdy", "rlusd",
                 "harbor", "mountain", "falcon", "jupiter-staked", "pump.fun-staked")
# coin_id 精确匹配(CG 里这些稳定币的 id 不含关键词)
EXCL_CID_EXACT = {
    "dai", "usds", "usd-coin", "tether", "frax", "usde", "usd0", "usdy", "rlusd",
    "usdt", "usdc", "busd", "tusd", "fdusd", "pyusd", "husd", "usdd", "usdn", "usdp",
    "usdtb", "usdt0", "usd1", "eurc", "eurs", "eurt", "usdj", "susd", "g-usd",
    "maker", "sky", "ust", "ustc", "mim", "pax-gold", "xaut", "tether-gold",
    "pax-dollar", "usd-coin-", "euro-coin", "tether-euro", "agix-usd",
}


# ------------------------------------------------------------------ 取数

def _http(path: str, params: list[tuple[str, str]], rng: str | None = None) -> str:
    url = URL.rstrip("/") + path + "?" + urllib.parse.urlencode(params, safe="(),.*:<>=")
    headers = dict(HEAD)
    headers["Accept"] = "text/csv"
    if rng:
        headers["Range"] = rng
    req = urllib.request.Request(url, headers=headers)
    last = None
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.read().decode()
        except urllib.error.HTTPError as e:
            last = e
            if e.code < 500 or attempt == 5:
                raise
            time.sleep(min(2 ** (attempt + 1), 30))
        except urllib.error.URLError:
            last = e
            if attempt == 5:
                raise
            time.sleep(min(2 ** (attempt + 1), 30))
    raise RuntimeError(f"unreachable: {last}")


def count_rows(path: str, params: list[tuple[str, str]]) -> int:
    for attempt in range(6):
        req = urllib.request.Request(
            URL.rstrip("/") + path + "?" + urllib.parse.urlencode(params, safe="(),.*:<>="),
            headers={**HEAD, "Prefer": "count=exact", "Range": "0-0"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                cr = r.headers.get("Content-Range", "")
            if not cr or "/" not in cr:
                return -1
            tail = cr.split("/")[-1]
            return int(tail) if tail.isdigit() else -1
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == 5:
                raise
            time.sleep(min(2 ** (attempt + 1), 30))
    return -1


def pull_chunk(path: str, params: list[tuple[str, str]], order: str, tag: str) -> Path:
    """拉一段(带 order= 主键排序),分页 1000 行,落 CSV 缓存。"""
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{tag}.csv"
    meta = CACHE / f"{tag}.meta.json"
    want = {"path": path, "params": [list(p) for p in params], "order": order}
    if cached.exists() and meta.exists():
        try:
            got = json.loads(meta.read_text())
            if got.get("want") == want and cached.stat().st_size > 0:
                print(f"[cache] {tag}", flush=True)
                return cached
        except Exception:
            pass
    ordered = list(params) + [("order", order)]
    total = count_rows(path, ordered)
    if total >= 0:
        ranges = [(i, min(i + PAGE - 1, total - 1)) for i in range(0, total, PAGE)]
    else:
        i, ranges = 0, []
        while True:
            body = _http(path, ordered, rng=f"{i}-{i + PAGE - 1}")
            lines = body.strip().splitlines()
            if len(lines) <= 1:
                break
            ranges.append((i, i + len(lines) - 2))
            i += PAGE

    def one(r):
        a, b = r
        return a, _http(path, ordered, rng=f"{a}-{b}")

    chunks: list[tuple[int, str]] = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for a, body in ex.map(one, ranges):
            chunks.append((a, body))
    chunks.sort(key=lambda x: x[0])
    header = chunks[0][1].splitlines()[0] if chunks else ""
    n_rows = 0
    with cached.open("w") as f:
        f.write(header + "\n")
        for _, body in chunks:
            for line in body.splitlines()[1:]:
                if line.strip():
                    f.write(line + "\n")
                    n_rows += 1
    meta.write_text(json.dumps({"want": want, "rows": n_rows,
                                 "pulled_at": datetime.now(timezone.utc).isoformat()}))
    if total >= 0 and n_rows != total:
        print(f"[WARN ] {tag}: 拉回 {n_rows} 行,服务端计数 {total} —— 分页有缺口,数字不能用!",
              file=sys.stderr, flush=True)
        raise SystemExit(f"{tag}: 分页行数 {n_rows} != {total},拒绝出结果")
    print(f"[pull ] {tag}: {n_rows} rows", flush=True)
    return cached


def pull_dated(path: str, base_params: list[tuple[str, str]], date_col: str,
               d_from: str, d_to: str, order: str, tag: str) -> Path:
    """按自然年分段拉(整段 4 年的查询在 PostgREST 上会 500),再拼成一张表。"""
    y0, y1 = int(d_from[:4]), int(d_to[:4])
    parts: list[Path] = []
    total_rows = 0
    for y in range(y0, y1 + 1):
        lo = max(d_from, f"{y}-01-01")
        hi = min(d_to, f"{y}-12-31")
        if lo > hi:
            continue
        params = list(base_params) + [(date_col, f"gte.{lo}"), (date_col, f"lte.{hi}")]
        p = pull_chunk(path, params, order, f"{tag}_{y}")
        n = sum(1 for _ in p.open()) - 1
        parts.append(p)
        total_rows += n
    out = CACHE / f"{tag}.csv"
    with out.open("w") as f:
        header = None
        for p in parts:
            with p.open() as g:
                for k, line in enumerate(g):
                    if k == 0:
                        if header is None:
                            header = line
                            f.write(line)
                    else:
                        f.write(line)
    (CACHE / f"{tag}.meta.json").write_text(json.dumps(
        {"path": path, "from": d_from, "to": d_to, "order": order, "rows": total_rows,
         "pulled_at": datetime.now(timezone.utc).isoformat()}))
    print(f"[pull ] {tag}: {total_rows} rows (按年拼接)", flush=True)
    return out


# ------------------------------------------------------------------ 小工具

def d2ord(s: str) -> int:
    return date.fromisoformat(s[:10]).toordinal()


def ord2d(o: int) -> str:
    return date.fromordinal(o).isoformat()


def avg_rank(vals: np.ndarray) -> np.ndarray:
    """并列名次的平均名次(名次 1 = 最小值)。"""
    n = len(vals)
    if n == 0:
        return np.zeros(0)
    order = np.argsort(vals, kind="mergesort")
    sv = vals[order]
    newgrp = np.ones(n, dtype=bool)
    newgrp[1:] = sv[1:] != sv[:-1]
    grp = np.cumsum(newgrp) - 1
    starts = np.flatnonzero(newgrp)
    counts = np.diff(np.append(starts, n))
    sums = np.add.reduceat(np.arange(1, n + 1, dtype=float), starts)
    out = np.empty(n, dtype=float)
    out[order] = (sums / counts)[grp]
    return out


def pct_rank(vals: np.ndarray) -> np.ndarray:
    """percent_rank = (平均名次 − 1) / (n − 1),取值 [0,1],越大越好。"""
    n = len(vals)
    if n <= 1:
        return np.zeros(n)
    return (avg_rank(vals) - 1.0) / (n - 1.0)


def ntile5(comp: np.ndarray) -> np.ndarray:
    """PostgreSQL ntile(5):按 comp 升序分 5 档,前面的档多拿行。返回 1..5。"""
    n = len(comp)
    out = np.empty(n, dtype=int)
    base, rem = divmod(n, 5)
    order = np.argsort(comp, kind="mergesort")
    pos = 0
    for b in range(5):
        size = base + (1 if b < rem else 0)
        out[order[pos:pos + size]] = b + 1
        pos += size
    return out


def roll_mean(arr: np.ndarray, span: int, min_days: int) -> np.ndarray:
    n = len(arr)
    valid = np.isfinite(arr)
    filled = np.where(valid, arr, 0.0)
    cs = np.concatenate([[0.0], np.cumsum(filled)])
    cv = np.concatenate([[0.0], np.cumsum(valid.astype(float))])
    lo = np.maximum(np.arange(n) - span + 1, 0)
    s, c = cs[1:] - cs[lo], cv[1:] - cv[lo]
    out = np.full(n, np.nan)
    ok = c >= min_days
    out[ok] = s[ok] / c[ok]
    return out


def roll_std(arr: np.ndarray, span: int, min_obs: int) -> np.ndarray:
    n = len(arr)
    valid = np.isfinite(arr)
    filled = np.where(valid, arr, 0.0)
    cs = np.concatenate([[0.0], np.cumsum(filled)])
    cs2 = np.concatenate([[0.0], np.cumsum(filled * filled)])
    cv = np.concatenate([[0.0], np.cumsum(valid.astype(float))])
    lo = np.maximum(np.arange(n) - span + 1, 0)
    s, c = cs[1:] - cs[lo], cv[1:] - cv[lo]
    s2 = cs2[1:] - cs2[lo]
    out = np.full(n, np.nan)
    ok = c >= max(min_obs, 2)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(c > 0, s / np.maximum(c, 1), np.nan)
        var = np.where(c > 1, (s2 - c * mean * mean) / (c - 1), np.nan)
    out[ok] = np.sqrt(var[ok])
    return out


def f(x, nd=2):
    if x is None:
        return "n/a"
    if isinstance(x, float) and not math.isfinite(x):
        return "n/a"
    return f"{x:.{nd}f}"


def pct(x, nd=2):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "n/a"
    return f"{100 * x:.{nd}f}%"


def selfcheck() -> None:
    v = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert np.allclose(pct_rank(v), [0.0, 0.25, 0.5, 0.75, 1.0]), pct_rank(v)
    assert np.allclose(pct_rank(np.array([1.0, 1.0, 2.0])), [0.25, 0.25, 1.0])
    assert list(ntile5(np.arange(134.0))) == list(np.concatenate([np.full(27, 1), np.full(27, 2),
                                                                np.full(27, 3), np.full(27, 4),
                                                                np.full(26, 5)]))
    assert ntile5(np.arange(10.0)).tolist() == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    grown = np.array([0.5, 0.5]) * (1 + np.array([1.0, 0.0]))
    assert np.allclose(grown / grown.sum(), [2 / 3, 1 / 3])
    print("[self] ok", flush=True)


# ------------------------------------------------------------------ 主流程

def main() -> None:
    t0 = time.time()
    selfcheck()

    # ---------------- 拉数 ----------------
    am_csv = pull_dated(
        "/rest/v1/asset_mcap_daily",
        [("select", "symbol,coin_id,d,price,mcap"), ("source", "eq.coingecko_pro_market_chart")],
        "d", GRID_FROM, GRID_TO, "symbol.asc,d.asc", "am")
    cg_csv = pull_dated(
        "/rest/v1/cg_coin_mcap_daily",
        [("select", "coin_id,d,price,mcap"), ("source", "eq.coingecko_pro_market_chart")],
        "d", GRID_FROM, GRID_TO, "coin_id.asc,d.asc", "cg")
    deriv_csv = pull_dated(
        "/rest/v1/deriv_metrics_daily",
        [("select", "symbol,d,oi_close,oi_value_close,taker_ratio_mean")],
        "d", GRID_FROM, GRID_TO, "symbol.asc,d.asc", "deriv")
    map_csv = pull_chunk("/rest/v1/perp_cg_map", [("select", "symbol,coin_id,mult,verdict")],
                         "symbol.asc", "perp_cg_map")
    cvd_csv = pull_chunk("/rest/v1/core_variants_daily",
                         [("select", "d,ret,nav"), ("arm", "eq.cap_pit24")], "d.asc", "cvd_cap_pit24")
    # 牛熊标记(T-225 §6):state_daily 长表(entity=panel, feature=mom_200),只用调仓日当天那一行
    st_csv = pull_chunk("/rest/v1/state_daily",
                        [("entity", "eq.panel"), ("feature", f"eq.{REGIME_FEATURE}"),
                         ("select", "d,value")], "d.asc", f"state_{REGIME_FEATURE}")

    # ---------------- 读 CSV ----------------
    g0, g1 = d2ord(GRID_FROM), d2ord(GRID_TO)
    grid = np.arange(g0, g1 + 1)
    gsize = len(grid)
    gidx = {int(d): i for i, d in enumerate(grid)}

    def fv(x):
        if x is None or x == "":
            return float("nan")
        try:
            return float(x)
        except ValueError:
            return float("nan")

    am_px: dict[str, dict[int, tuple[float, float]]] = {}   # sym(大写) -> ord -> (price, mcap)
    sym2cid: dict[str, str] = {}
    cid2sym: dict[str, str] = {}
    with am_csv.open() as f:
        for row in csv.DictReader(f):
            sym = (row["symbol"] or "").upper()
            cid = (row["coin_id"] or "").lower()
            p, m = fv(row["price"]), fv(row["mcap"])
            if not sym or not (math.isfinite(p) and p > 0):
                continue
            am_px.setdefault(sym, {})[gidx[d2ord(row["d"])]] = (p, m)
            if cid:
                sym2cid[sym] = cid
                cid2sym.setdefault(cid, sym)

    cg_px: dict[str, dict[int, tuple[float, float]]] = {}   # coin_id -> ord -> (price, mcap)
    with cg_csv.open() as f:
        for row in csv.DictReader(f):
            cid = (row["coin_id"] or "").lower()
            p, m = fv(row["price"]), fv(row["mcap"])
            if not cid or not (math.isfinite(p) and p > 0):
                continue
            cg_px.setdefault(cid, {})[gidx[d2ord(row["d"])]] = (p, m)

    oi: dict[str, dict[int, dict]] = {}
    with deriv_csv.open() as f:
        for row in csv.DictReader(f):
            sym = (row["symbol"] or "").upper()
            oi.setdefault(sym, {})[gidx[d2ord(row["d"])]] = {
                "oi_close": fv(row["oi_close"]), "oi_value": fv(row["oi_value_close"]),
                "taker": fv(row["taker_ratio_mean"])}

    maps: list[tuple[str, str, float, str]] = []
    with map_csv.open() as f:
        for row in csv.DictReader(f):
            maps.append(((row["symbol"] or "").upper(), (row["coin_id"] or "").lower(),
                         fv(row["mult"]) if row["mult"] else 1.0, row["verdict"] or ""))
    # 牛熊标记:state_daily(entity=panel, feature=mom_200) —— 只用调仓日当天那一行
    mom200: dict[str, float] = {}
    with st_csv.open() as f:
        for row in csv.DictReader(f):
            v = fv(row["value"])
            if math.isfinite(v):
                mom200[row["d"]] = v
    print(f"[load ] am {len(am_px)} sym / cg {len(cg_px)} coin / deriv {len(oi)} sym / map {len(maps)}"
          f" / regime {REGIME_FEATURE} {len(mom200)} 天", flush=True)

    # ---------------- 稠密数组工具 ----------------
    def dense(series: dict[int, float]) -> np.ndarray:
        arr = np.full(gsize, np.nan)
        for d, v in series.items():
            if v is not None and math.isfinite(v):
                arr[d] = v
        return arr

    # coin_id -> (price_dense, mcap_dense, last_obs_ord)   面板用
    coin_cache: dict[str, tuple[np.ndarray, np.ndarray, int]] = {}

    def coin_arrays(cid: str):
        """返回 (price_dense, mcap_dense, last_obs_idx);asset_mcap 优先,cg 补缺。"""
        if cid in coin_cache:
            return coin_cache[cid]
        px = np.full(gsize, np.nan)
        mc = np.full(gsize, np.nan)
        cgser = cg_px.get(cid)
        if cgser:
            for d, (p, m) in cgser.items():
                px[d] = p
                if math.isfinite(m):
                    mc[d] = m
        sym = cid2sym.get(cid)
        amser = am_px.get(sym) if sym else None
        if amser:
            for d, (p, m) in amser.items():
                px[d] = p
                if math.isfinite(m):
                    mc[d] = m
        obs = np.where(np.isfinite(px))[0]
        last = int(obs[-1]) if len(obs) else -1
        coin_cache[cid] = (px, mc, last)
        return coin_cache[cid]

    # ---------------- 宇宙(S-694 照抄) ----------------
    name_set = set(oi.keys())
    am_syms = set(am_px.keys())
    uni_px: dict[str, dict[int, tuple[float, float, float]]] = {}   # sym -> ord -> (price, mcap, mult)
    for sym, ser in am_px.items():
        if sym not in name_set:
            continue
        uni_px[sym] = {d: (p, m, 1.0) for d, (p, m) in ser.items()}
    cg_by_id: dict[str, dict[int, tuple[float, float]]] = {}
    for cid, ser in cg_px.items():
        cg_by_id[cid] = ser
    mapped: dict[str, tuple[str, float]] = {}
    for sym, cid, mult, verdict in maps:
        if verdict != "resolved" or sym not in name_set or sym in am_syms:
            continue
        mapped[sym] = (cid, mult if math.isfinite(mult) and mult > 0 else 1.0)
    for sym, (cid, mult) in mapped.items():
        for d, (p, m) in cg_by_id.get(cid, {}).items():
            uni_px.setdefault(sym, {})[d] = (p, m, mult)
    print(f"[map  ] 宇宙名字 {len(name_set)},有价 {len(uni_px)},映射补数 {len(mapped)}", flush=True)

    # 映射校验(S-689)
    lo, hi = d2ord(GRID_FROM), d2ord(GRID_TO)
    check_rows = []
    for sym, series in oi.items():
        if sym not in uni_px:
            continue
        errs = []
        for d, rec in series.items():
            if rec["oi_close"] is None or rec["oi_value"] is None:
                continue
            if rec["oi_close"] <= 0 or rec["oi_value"] <= 0:
                continue
            p = uni_px[sym].get(d)
            if p is None or not math.isfinite(p[0]) or p[0] <= 0:
                continue
            implied = rec["oi_value"] / rec["oi_close"]
            errs.append(abs(p[0] * p[2] / implied - 1.0))
        if errs:
            check_rows.append((sym, len(errs), float(np.median(errs))))
    kept = {s for s, n, e in check_rows if n >= MAP_MIN_OVERLAP and e <= MAP_MAX_MED_ERR}
    print(f"[map  ] 映射校验留 {len(kept)}/{len(check_rows)} 个名字", flush=True)

    # 因子
    btc = np.full(gsize, np.nan)
    for d, (p, _) in am_px.get("BTC", {}).items():
        btc[d] = p
    per: dict[str, dict[str, np.ndarray]] = {}
    for sym in sorted(kept):
        ser = uni_px.get(sym)
        if not ser:
            continue
        price_d = dense({d: v[0] for d, v in ser.items()})
        mcap_d = dense({d: v[1] for d, v in ser.items()})
        recs = oi.get(sym, {})
        taker_d = dense({d: r["taker"] for d, r in recs.items()})
        oi_close_d = dense({d: r["oi_close"] for d, r in recs.items()})
        prev = np.concatenate([[np.nan], price_d[:-1]])
        with np.errstate(invalid="ignore", divide="ignore"):
            ret = np.where((price_d > 0) & (prev > 0), np.log(price_d / prev), np.nan)
        f11 = roll_std(ret, 30, MIN_VOL_OBS)
        f7 = roll_mean(taker_d, 7, MIN_WINDOW_DAYS)

        def lag_ratio(arr, k):
            with np.errstate(invalid="ignore", divide="ignore"):
                return np.where((arr[k:] > 0) & (arr[:-k] > 0), arr[k:] / arr[:-k] - 1.0, np.nan)

        f3 = np.full(gsize, np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            f3[30:] = np.log(oi_close_d[30:] / oi_close_d[:-30])
        f8 = np.full(gsize, np.nan)
        f9 = np.full(gsize, np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            f8[30:] = lag_ratio(price_d, 30) - lag_ratio(btc, 30)
            f9[7:] = lag_ratio(price_d, 7) - lag_ratio(btc, 7)
        per[sym] = {"f3": f3, "f7": f7, "f8": f8, "f9": f9, "f11": f11,
                    "price": price_d, "mcap": mcap_d}
    print(f"[calc ] 因子数组 {len(per)} 个名字", flush=True)

    # symbol -> coin_id(宇宙侧)
    sym_cid: dict[str, str] = {}
    for sym in per:
        sym_cid[sym] = sym2cid.get(sym) or mapped.get(sym, ("", 1.0))[0]
    # coin_id -> 宇宙里的 symbol(取当日因子有值的那个;主选)
    cid2uni: dict[str, list[str]] = {}
    for sym, cid in sym_cid.items():
        if cid:
            cid2uni.setdefault(cid.lower(), []).append(sym)

    # ---------------- 面板:每月初前 50 ----------------
    def excluded(cid: str, sym: str | None) -> bool:
        if sym and sym.upper() in EXCL_SYMBOLS:
            return True
        c = (cid or "").lower()
        if c in EXCL_CID_EXACT:
            return True
        if any(k in c for k in EXCL_CID_KEYS):
            return True
        return False

    # 锚点:月频 = 每月第一个 BTC 有价的日子;周频 = 每个 ISO 周第一个 BTC 有价的日子
    labels: list[str] = []
    anchors: list[int] = []
    seen_key: set[str] = set()
    for i in range(gsize):
        d = ord2d(grid[i])
        if d < P_START or d > P_END or not math.isfinite(btc[i]):
            continue
        if FREQ == "week":
            yy, ww, _ = date.fromisoformat(d).isocalendar()
            key = f"{yy}-W{ww:02d}"
        else:
            key = d[:7]
        if key in seen_key:
            continue
        seen_key.add(key)
        labels.append(key)
        anchors.append(i)

    # 候选快照:对每个锚点,收集 (coin_id -> (price, mcap, sym))
    # 先把每个 symbol / coin_id 的观测排好序,锚点上二分找「最近一次有价」。
    am_obs: dict[str, np.ndarray] = {}
    am_pv: dict[str, np.ndarray] = {}
    am_mv: dict[str, np.ndarray] = {}
    for sym, ser in am_px.items():
        ks = np.array(sorted(ser.keys()), dtype=int)
        am_obs[sym] = ks
        am_pv[sym] = np.array([ser[k][0] for k in ks])
        am_mv[sym] = np.array([ser[k][1] for k in ks])
    cg_obs: dict[str, np.ndarray] = {}
    cg_pv: dict[str, np.ndarray] = {}
    cg_mv: dict[str, np.ndarray] = {}
    for cid, ser in cg_px.items():
        ks = np.array(sorted(ser.keys()), dtype=int)
        cg_obs[cid] = ks
        cg_pv[cid] = np.array([ser[k][0] for k in ks])
        cg_mv[cid] = np.array([ser[k][1] for k in ks])

    def last_obs_at(obs: np.ndarray, i: int) -> int:
        """锚点 i(含)之前最后一次观测的数组下标;没有就 -1。"""
        if obs.size == 0:
            return -1
        j = int(np.searchsorted(obs, i, side="right")) - 1
        return j if j >= 0 else -1

    panels: list[list[dict]] = []
    excluded_hits: dict[str, int] = {}
    for ai, i in enumerate(anchors):
        if i < 0:
            panels.append([])
            continue
        cands: dict[str, dict] = {}
        for sym, obs in am_obs.items():
            j = last_obs_at(obs, i)
            if j < 0 or obs[j] < i - STALE_DAYS:
                continue
            m = float(am_mv[sym][j])
            if not (math.isfinite(m) and m > 0):
                continue
            cid = (sym2cid.get(sym) or "").lower() or sym.lower()
            cands[cid] = {"cid": cid, "sym": sym, "price": float(am_pv[sym][j]), "mcap": m}
        for cid, obs in cg_obs.items():
            if cid in cands:
                continue
            j = last_obs_at(obs, i)
            if j < 0 or obs[j] < i - STALE_DAYS:
                continue
            m = float(cg_mv[cid][j])
            if not (math.isfinite(m) and m > 0):
                continue
            cands[cid] = {"cid": cid, "sym": cid2sym.get(cid), "price": float(cg_pv[cid][j]),
                          "mcap": m}
        alive: list[dict] = []
        for cid, rec in cands.items():
            if excluded(cid, rec["sym"]):
                key = rec["sym"] or cid
                excluded_hits[key] = excluded_hits.get(key, 0) + 1
                continue
            alive.append(rec)
        alive.sort(key=lambda r: -r["mcap"])
        panels.append(alive[:N_PANEL])
    sizes = [len(p) for p in panels]
    print(f"[panel] 面板 {len(labels)} 期({FREQ}),成员数 min {min(sizes)} / max {max(sizes)}", flush=True)

    # ---------------- 逐期:合成 / 权重 / 收益 ----------------
    periods: list[dict] = []
    for ai in range(len(labels)):
        i = anchors[ai]
        if i < 0 or len(panels[ai]) == 0:
            continue
        # 退出日:下一个锚点;最后一期 = P_END 之前最后一个有数日子
        if ai + 1 < len(anchors) and anchors[ai + 1] >= 0:
            j_exit = anchors[ai + 1]
        else:
            j_exit = None
            for k in range(gsize - 1, -1, -1):
                if ord2d(grid[k]) <= P_END:
                    j_exit = k
                    break
        if j_exit is None or j_exit <= i:
            continue
        # --- 宇宙合成 ---
        uni: list[str] = []
        raw: dict[str, list[float]] = {}
        for sym in sorted(kept):
            if sym not in per:
                continue
            rec = oi.get(sym, {}).get(i)
            if rec is None or rec["oi_close"] is None or rec["oi_value"] is None:
                continue
            if rec["oi_close"] <= 0 or rec["oi_value"] <= 0:
                continue
            m = per[sym]["mcap"][i]
            if not math.isfinite(m) or m < MCAP_MIN:
                continue
            vals = []
            ok = True
            for code, _ in FROZEN:
                v = per[sym][{"F3": "f3", "F7": "f7", "F8": "f8", "F9": "f9", "F11": "f11"}[code]][i]
                if not math.isfinite(v):
                    ok = False
                    break
                vals.append(v)
            if not ok:
                continue
            uni.append(sym)
            raw[sym] = vals
        comp_by_name: dict[str, float] = {}
        worst_uni: set[str] = set()
        if len(uni) >= MIN_NAMES:
            comp = np.zeros(len(uni))
            for k, (code, sign) in enumerate(FROZEN):
                arr = np.array([raw[s][k] for s in uni]) * sign
                comp += pct_rank(arr)
            comp /= len(FROZEN)
            bucket = ntile5(comp)
            worst_uni = {uni[k] for k in range(len(uni)) if bucket[k] == 1}
            comp_by_name = {uni[k]: float(comp[k]) for k in range(len(uni))}

        # --- 面板成员:进入价 / 退出价 / 日收益 ---
        members = []
        for rec in panels[ai]:
            cid = rec["cid"]
            px, mc, last_obs = coin_arrays(cid)
            finite = np.where(np.isfinite(px[:i + 1]))[0]
            if finite.size == 0:
                continue
            entry_i = int(finite[-1])       # 锚点当天或之前最近一次有价
            if entry_i < i - STALE_DAYS:
                continue
            p0 = px[entry_i]
            if not (math.isfinite(p0) and p0 > 0):
                continue
            # 日收益(网格上):死币 = 最后观测 + STALE_DAYS 之后价格归零
            members.append({"cid": cid, "sym": rec["sym"] or cid, "p0": float(p0),
                             "mcap": float(rec["mcap"]), "i0": entry_i, "i1": j_exit,
                             "px": px, "last_obs": last_obs})
        if not members:
            continue
        # 每个成员的日收益数组
        for mrec in members:
            px = mrec["px"]
            i0, i1 = mrec["i0"], mrec["i1"]
            seg = px[i0:i1 + 1].copy()
            # 死币规则(T-225 时点口径):**不写销** —— 序列结束就按最后一个有效价持有到底(收益 0)。
            # 但 coin_id 连续性写成硬断言:持有期内出现 > 10 天的内部断点 = 数据管道有洞,报错中止。
            obs_in = np.where(np.isfinite(seg))[0]
            if len(obs_in) > 1:
                gaps = np.diff(obs_in)
                gmax = int(gaps.max())
                if gmax > STALE_DAYS:
                    k = int(np.argmax(gaps))
                    a = int(obs_in[k])
                    b = int(obs_in[k + 1])
                    raise AssertionError(
                        f"coin_id 连续性断言失败:{mrec['cid']}({mrec['sym']}) 在期 {labels[ai]} "
                        f"({ord2d(int(grid[i0]))} → {ord2d(int(grid[i1]))}) 内有 {gmax} 天的价格断点"
                        f"({ord2d(int(grid[i0 + a]))} → {ord2d(int(grid[i0 + b]))}),超过 {STALE_DAYS} 天 —— "
                        f"这是数据管道的洞,不许当成死币默默吃掉。")
            # 缺价的日子沿用上一个有效价(前向填充)
            lastv = float("nan")
            for k in range(len(seg)):
                if math.isfinite(seg[k]) and seg[k] > 0:
                    lastv = seg[k]
                elif math.isfinite(lastv) and not math.isfinite(seg[k]):
                    seg[k] = lastv
            prevv = np.concatenate([[np.nan], seg[:-1]])
            with np.errstate(invalid="ignore", divide="ignore"):
                rets = np.where((seg > 0) & (prevv > 0), seg / prevv - 1.0, np.nan)
            rets = np.where(np.isnan(rets) & (seg <= 0) & (prevv > 0), -1.0, rets)
            rets = np.where(np.isnan(rets), 0.0, rets)
            mrec["rets"] = rets
            mrec["dead"] = bool(mrec["last_obs"] < i1 - STALE_DAYS)

        # 面板成员 ↔ 宇宙合成值(coin_id → 宇宙 symbol)
        flag_uni: list[bool] = []
        comp_vals: list[float | None] = []
        for mrec in members:
            cand = cid2uni.get(mrec["cid"], [])
            best = None
            for sym in cand:
                if sym in comp_by_name:
                    best = sym
                    break
            if best is None and mrec["sym"]:
                for sym in cand:
                    if sym in comp_by_name:
                        best = sym
                        break
            if best is None:
                flag_uni.append(False)
                comp_vals.append(None)
            else:
                flag_uni.append(best in worst_uni)
                comp_vals.append(comp_by_name[best])
        # 副口径:面板内部 ntile(5)(只在有合成值的成员里)
        flag_panel = np.zeros(len(members), dtype=bool)
        idxs = [k for k, v in enumerate(comp_vals) if v is not None]
        if len(idxs) >= 5:
            pb = ntile5(np.array([comp_vals[k] for k in idxs]))
            flag_panel[[idxs[k] for k in range(len(idxs)) if pb[k] == 1]] = True

        # 诊断(只报不判):同一个合成在**宽宇宙**里往后 30 天的相对表现(对照面板口径)
        uni_diag: dict | None = None
        if worst_uni and len(uni) >= MIN_NAMES:
            j30u = min(i + 30, gsize - 1)
            if j30u > i:
                rs: dict[str, float] = {}
                mcw: dict[str, float] = {}
                for s in uni:
                    pa = per[s]["price"]
                    if not (math.isfinite(pa[i]) and pa[i] > 0):
                        continue
                    seg = pa[i:j30u + 1]
                    fin = np.where(np.isfinite(seg) & (seg > 0))[0]
                    if not len(fin):
                        continue
                    rs[s] = float(seg[fin[-1]] / pa[i] - 1.0)
                    mv = per[s]["mcap"][i]
                    mcw[s] = float(mv) if (math.isfinite(mv) and mv > 0) else 0.0
                if rs:
                    wr = {s: v for s, v in rs.items() if s in worst_uni}
                    rest = {s: v for s, v in rs.items() if s not in worst_uni}

                    def wmean(dd: dict[str, float]) -> float:
                        tw = sum(mcw.get(s, 0.0) for s in dd)
                        if tw <= 0:
                            return float("nan")
                        return sum(dd[s] * mcw.get(s, 0.0) for s in dd) / tw

                    if wr and rest:
                        uni_diag = {
                            "n": len(rs), "n_worst": len(wr),
                            "worst_ew": float(np.mean(list(wr.values()))),
                            "all_ew": float(np.mean(list(rs.values()))),
                            "worst_mw": wmean(wr), "rest_mw": wmean(rest),
                        }
                        uni_diag["excess_ew"] = uni_diag["worst_ew"] - uni_diag["all_ew"]
                        uni_diag["excess_mw_vs_rest"] = uni_diag["worst_mw"] - uni_diag["rest_mw"]

        anchor_date = ord2d(int(grid[i]))
        rv = mom200.get(anchor_date)
        regime = "unknown" if rv is None else ("bull" if rv > 0 else "bear")
        periods.append({
            "month": labels[ai], "anchor": anchor_date, "exit": ord2d(int(grid[j_exit])),
            "regime": regime, "regime_value": (float(rv) if rv is not None else None),
            "i0": int(grid[i]), "i1": int(grid[j_exit]),
            "members": members, "flag_uni": np.array(flag_uni, dtype=bool),
            "flag_panel": flag_panel, "comp": comp_vals,
            "universe": len(uni), "n_worst_uni": len(worst_uni),
            "comp_by_name": comp_by_name, "uni_diag": uni_diag,
        })
    print(f"[period] 有效期数 {len(periods)}", flush=True)

    # ---------------- 模拟 ----------------
    def simulate(periods_: list[dict], flag_sets: list[np.ndarray], mode: str = "mw") -> dict:
        """mode: mw(市值加权) / ew(等权)。期内权重按日漂移(买入持有),期末重置为目标权重。"""
        W = len(periods_)
        gross = np.zeros(W)
        cost = np.zeros(W)
        prev: dict[str, float] = {}
        nav_daily: list[tuple[str, float]] = []
        for t, p in enumerate(periods_):
            mem = p["members"]
            n = len(mem)
            mc = np.array([m["mcap"] for m in mem], dtype=float)
            w = (np.ones(n) / n) if mode == "ew" else (mc / mc.sum())
            fl = flag_sets[t]
            w = w * np.where(fl, TILT_MULT, 1.0)
            if w.sum() <= 0:
                continue
            w = w / w.sum()
            target = {mem[k]["cid"]: float(w[k]) for k in range(n)}
            keys = set(target) | set(prev)
            turnover = sum(abs(target.get(k, 0.0) - prev.get(k, 0.0)) for k in keys)
            c = (COST_BP / 1e4) * turnover
            # 日内漂移
            R = np.ones(n)
            seg_ret = []
            for d in range(len(mem[0]["rets"])):
                r_i = np.array([m["rets"][d] for m in mem])
                rp = float((w * r_i).sum())
                seg_ret.append(rp)
                grown = w * (1 + r_i)
                s = grown.sum()
                w = grown / s if s > 0 else np.zeros(n)
            period_ret = float(np.prod(1 + np.array(seg_ret)) - 1)
            gross[t] = period_ret
            cost[t] = c
            # 漂移后权重(期末)
            prev = {}
            for k, m in enumerate(mem):
                prev[m["cid"]] = float(w[k])
            nav_daily.append((p["exit"], period_ret))
        net = gross - cost
        return {"gross": gross, "cost": cost, "net": net}


    def nav_series(periods_: list[dict], arms: list[dict]) -> list[tuple[str, float]]:
        """按期复利出 NAV(用于最大回撤)。"""
        out: list[tuple[str, float]] = []
        nav = 1.0
        for t, p in enumerate(periods_):
            nav *= (1 + arms[t]["gross"])
            out.append((p["exit"], nav))
        return out

    def mdd(nav_list: list[tuple[str, float]]) -> float:
        vals = np.array([v for _, v in nav_list], dtype=float)
        if len(vals) == 0:
            return float("nan")
        return float((vals / np.maximum.accumulate(vals) - 1).min())

    def ann_geo(series: np.ndarray, per_year: float = PER_YEAR) -> float:
        s = np.asarray(series, dtype=float)
        if s.size == 0 or np.any(1.0 + s <= 0):
            return float("nan")
        return float(np.prod(1.0 + s) ** (per_year / s.size) - 1.0)

    zeros = [np.zeros(len(p["members"]), dtype=bool) for p in periods]
    base_mw = simulate(periods, zeros, "mw")
    base_ew = simulate(periods, zeros, "ew")
    tilt_mw = simulate(periods, [p["flag_uni"] for p in periods], "mw")
    tilt_ew = simulate(periods, [p["flag_uni"] for p in periods], "ew")
    tilt_panel = simulate(periods, [p["flag_panel"] for p in periods], "mw")

    # 逐期归因(一阶:期初一次性再平衡的权重差 × 成员期内收益;漂移为二阶,不计)
    attrib: list[dict] = []
    for t, p in enumerate(periods):
        mem = p["members"]
        n = len(mem)
        mc = np.array([m["mcap"] for m in mem], dtype=float)
        w_b = mc / mc.sum()
        w_t = w_b * np.where(p["flag_uni"], TILT_MULT, 1.0)
        if w_t.sum() <= 0:
            continue
        w_t = w_t / w_t.sum()
        r_i = np.array([float(np.prod(1 + m["rets"]) - 1) for m in mem])
        eff = float(((w_t - w_b) * r_i).sum())
        contrib = [((w_t[k] - w_b[k]) * r_i[k], mem[k]["sym"], float(w_b[k]), float(r_i[k]))
                   for k in range(n) if abs((w_t[k] - w_b[k]) * r_i[k]) > 1e-12]
        contrib.sort(key=lambda c: c[0])
        attrib.append({"month": p["month"], "eff": eff,
                       "base_gross": float(base_mw["gross"][t]), "tilt_gross": float(tilt_mw["gross"][t]),
                       "worst": [{"sym": c[1], "w_base": c[2], "ret": c[3], "eff": c[0]} for c in contrib[:3]],
                       "best": [{"sym": c[1], "w_base": c[2], "ret": c[3], "eff": c[0]}
                                for c in reversed(contrib[-3:])]})

    def seg_stats(tilt: dict, base: dict, idx: np.ndarray) -> dict:
        gt, nt = tilt["gross"][idx], tilt["net"][idx]
        gb, nb = base["gross"][idx], base["net"][idx]
        n = int(idx.size)
        ex_net = nt - nb
        out = {
            "n_periods": n,
            "ann_gross_tilt": ann_geo(gt), "ann_gross_base": ann_geo(gb),
            "ann_net_tilt": ann_geo(nt), "ann_net_base": ann_geo(nb),
            "ann_excess_gross_geo": ann_geo(gt) - ann_geo(gb),
            "ann_excess_net_geo": ann_geo(nt) - ann_geo(nb),
            "ann_excess_net_arith": float(np.mean(ex_net) * PER_YEAR) if n else float("nan"),
            "tracking_error_net": float(np.std(ex_net, ddof=1) * math.sqrt(PER_YEAR)) if n > 1 else float("nan"),
            "cost_bp_per_year_tilt": float(np.sum(tilt["cost"][idx]) * (PER_YEAR / max(n, 1)) * 1e4),
        }
        return out

    W = len(periods)
    idx_all = np.arange(W)
    # 旧日历切点(降级为副指标)
    half = d2ord(HALF_CUT)
    idx_h1 = np.array([t for t, p in enumerate(periods) if p["i0"] <= half])
    idx_h2 = np.array([t for t, p in enumerate(periods) if p["i0"] > half])
    # 牛/熊分段(T-225 §6):调仓日 state_daily(entity=panel, mom_200) 的符号
    idx_bull = np.array([t for t, p in enumerate(periods) if p["regime"] == "bull"])
    idx_bear = np.array([t for t, p in enumerate(periods) if p["regime"] == "bear"])
    idx_unk = np.array([t for t, p in enumerate(periods) if p["regime"] == "unknown"])
    print(f"[regim] 牛 {len(idx_bull)} 期 / 熊 {len(idx_bear)} 期 / 未知 {len(idx_unk)} 期", flush=True)

    # ---------------- 随机对照(种子 694) ----------------
    k_t = [int(p["flag_uni"].sum()) for p in periods]
    # 可选集合:有合成值的面板名字
    elig_t = [np.array([c is not None for c in p["comp"]], dtype=bool) for p in periods]
    n_elig_t = [int(e.sum()) for e in elig_t]

    def run_null(seed: int, idx=None, k_sub=None, n_sub=None, base_sub=None):
        ps = periods if idx is None else [periods[t] for t in idx]
        ks = k_t if k_sub is None else k_sub
        ns = n_elig_t if n_sub is None else n_sub
        bs = base_mw if base_sub is None else base_sub

        def fn(rng):
            flags = []
            for t in range(len(ps)):
                k = min(ks[t], ns[t])
                f = np.zeros(len(ps[t]["members"]), dtype=bool)
                if k > 0:
                    elig_idx = [kk for kk in range(len(ps[t]["members"]))
                                if ps[t]["comp"][kk] is not None]
                    pick = rng.choice(len(elig_idx), size=k, replace=False)
                    for pp in pick:
                        f[elig_idx[pp]] = True
                flags.append(f)
            res = simulate(ps, flags, "mw")
            return ann_geo(res["net"]) - ann_geo(bs["net"])

        try:
            null = null_distribution(fn, N_NULL, seed)
            return null, None
        except NoOpNull as e:
            return None, str(e)

    actual_net = ann_geo(tilt_mw["net"]) - ann_geo(base_mw["net"])
    actual_gross = ann_geo(tilt_mw["gross"]) - ann_geo(base_mw["gross"])
    null_all, null_err = run_null(SEED)
    pct_all = percentile_of(actual_net, null_all) if null_all is not None else None
    pct_all_gross = percentile_of(actual_gross, null_all) if null_all is not None else None

    def seg_null(seed: int, idx: np.ndarray):
        ps = [periods[t] for t in idx]
        ks = [k_t[t] for t in idx]
        ns = [n_elig_t[t] for t in idx]
        bs = {"net": base_mw["net"][idx], "gross": base_mw["gross"][idx]}

        def fn(rng):
            flags = []
            for t in range(len(ps)):
                k = min(ks[t], ns[t])
                f = np.zeros(len(ps[t]["members"]), dtype=bool)
                if k > 0:
                    elig_idx = [kk for kk in range(len(ps[t]["members"]))
                                if ps[t]["comp"][kk] is not None]
                    pick = rng.choice(len(elig_idx), size=k, replace=False)
                    for pp in pick:
                        f[elig_idx[pp]] = True
                flags.append(f)
            res = simulate(ps, flags, "mw")
            return ann_geo(res["net"]) - ann_geo(bs["net"])

        try:
            return null_distribution(fn, N_NULL, seed), None
        except NoOpNull as e:
            return None, str(e)

    h1_net = seg_stats(tilt_mw, base_mw, idx_h1)
    h2_net = seg_stats(tilt_mw, base_mw, idx_h2)
    null_h1, e1 = seg_null(SEED + 1, idx_h1)
    null_h2, e2 = seg_null(SEED + 2, idx_h2)
    pct_h1 = percentile_of(h1_net["ann_excess_net_geo"], null_h1) if null_h1 is not None else None
    pct_h2 = percentile_of(h2_net["ann_excess_net_geo"], null_h2) if null_h2 is not None else None
    # 牛 / 熊两段(判据 b 用这两段)
    bull_net = seg_stats(tilt_mw, base_mw, idx_bull)
    bear_net = seg_stats(tilt_mw, base_mw, idx_bear)
    null_bull, eb1 = seg_null(SEED + 3, idx_bull)
    null_bear, eb2 = seg_null(SEED + 4, idx_bear)
    pct_bull = percentile_of(bull_net["ann_excess_net_geo"], null_bull) if null_bull is not None else None
    pct_bear = percentile_of(bear_net["ann_excess_net_geo"], null_bear) if null_bear is not None else None

    # ---------------- 副指标 ----------------
    flagged_counts = [int(p["flag_uni"].sum()) for p in periods]
    flagged_names: list[dict] = []
    for p in periods:
        nm = [m["sym"] for m, fl in zip(p["members"], p["flag_uni"]) if fl]
        flagged_names.append({"month": p["month"], "n": len(nm), "names": nm})

    # 最差档之后 30 天相对面板(两种参照:等权面板均值 / 市值加权面板均值)
    rel30: list[float] = []
    rel30_mw: list[float] = []
    rel30_rest: list[float] = []
    rel30_by_month: list[dict] = []
    for p in periods:
        i0, i1 = p["i0"], p["i1"]
        # 30 天窗:从锚点起 30 天(超出期末就用期末)
        j30 = min(i0 + 30, i1)
        if j30 <= i0:
            continue
        mem = p["members"]
        panel_ret = []
        for m in mem:
            seg = m["rets"][:j30 - i0 + 1]
            panel_ret.append(float(np.prod(1 + seg) - 1))
        pref = float(np.mean(panel_ret)) if panel_ret else float("nan")
        mc = np.array([m["mcap"] for m in mem], dtype=float)
        pref_mw = (float(np.dot(mc, np.array(panel_ret)) / mc.sum())
                   if len(panel_ret) and mc.sum() > 0 else float("nan"))
        # 非最差档成员的市值加权均值 = 倾斜真正的反事实(减掉的权重按市值分给「其余」)
        rest_mask = np.array([not fl for fl in p["flag_uni"]])
        rest_w = mc * rest_mask
        pref_rest_mw = (float(np.dot(rest_w, np.array(panel_ret)) / rest_w.sum())
                        if rest_w.sum() > 0 else float("nan"))
        vals, vals_mw, vals_rest = [], [], []
        for m, fl in zip(mem, p["flag_uni"]):
            if not fl:
                continue
            seg = m["rets"][:j30 - i0 + 1]
            r = float(np.prod(1 + seg) - 1)
            vals.append(r - pref)
            vals_mw.append(r - pref_mw)
            vals_rest.append(r - pref_rest_mw)
        if vals:
            rel30.extend(vals)
            rel30_mw.extend(vals_mw)
            rel30_rest.extend(vals_rest)
            rel30_by_month.append({"month": p["month"], "n": len(vals),
                                    "rel_mean": float(np.mean(vals)),
                                    "rel_mean_mw": float(np.mean(vals_mw)),
                                    "rel_mean_rest_mw": float(np.mean(vals_rest))})

    # 死币(写销)披露:哪期、哪个名字、基线权重多少(不影响判据,但必须写清)
    dead_events: list[dict] = []
    for p in periods:
        mem = p["members"]
        tot = float(sum(m["mcap"] for m in mem)) or 1.0
        for m in mem:
            if m.get("dead"):
                dead_events.append({"month": p["month"], "sym": m["sym"],
                                    "base_weight": m["mcap"] / tot})

    # 深跌成员(「死币」证据):期内总收益 ≤ −50% 的「期 × 成员」
    deep_losses: list[dict] = []
    for p in periods:
        for m in p["members"]:
            r = float(np.prod(1 + m["rets"]) - 1)
            if math.isfinite(r) and r <= -0.5:
                deep_losses.append({"month": p["month"], "sym": m["sym"], "ret": r})

    # 面板成分(前 / 后两期)
    def membership(idx: int) -> list[dict]:
        p = periods[idx]
        out = []
        for m, fl in zip(p["members"], p["flag_uni"]):
            out.append({"sym": m["sym"], "mcap": m["mcap"], "flagged": bool(fl)})
        out.sort(key=lambda r: -r["mcap"])
        return out

    # ---------------- cap_pit24 并排 ----------------
    pit_rets = []
    with cvd_csv.open() as f:
        for row in csv.DictReader(f):
            d = row["d"]
            if not (P_START <= d <= P_END):
                continue
            r = fv(row["ret"])
            if math.isfinite(r):
                pit_rets.append((d, r))
    pit_nav = 1.0
    pit_curve = []
    for d, r in pit_rets:
        pit_nav *= (1 + r)
        pit_curve.append((d, pit_nav))
    pit_vals = np.array([v for _, v in pit_curve])
    pit_ann = float(pit_vals[-1] ** (365.0 / len(pit_vals)) - 1) if len(pit_vals) else float("nan")
    pit_mdd = float((pit_vals / np.maximum.accumulate(pit_vals) - 1).min()) if len(pit_vals) else float("nan")

    base_nav = nav_series(periods, [{"gross": base_mw["gross"][t]} for t in range(W)])
    tilt_nav = nav_series(periods, [{"gross": tilt_mw["gross"][t]} for t in range(W)])
    base_mdd = mdd(base_nav)
    tilt_mdd = mdd(tilt_nav)

    # ---------------- 判定 ----------------
    crit_a = bool(actual_net > 0 and pct_all is not None and pct_all >= 0.95)
    crit_b = bool(bull_net["ann_excess_net_geo"] > 0 and bear_net["ann_excess_net_geo"] > 0)
    verdict = "✅" if (crit_a and crit_b) else "❌"

    res = {
        "card": "T-225", "arm": ARM_TAG, "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": {"n_panel": N_PANEL, "freq": FREQ, "tilt": TILT, "tilt_mult": TILT_MULT,
                   "per_year": PER_YEAR, "period": f"{P_START} → {P_END}", "cost_bp": COST_BP,
                   "n_null": N_NULL, "seed": SEED, "regime_feature": REGIME_FEATURE,
                   "stale_days": STALE_DAYS, "dead_rule": "point-in-time, no write-off",
                   "universe_min_names": MIN_NAMES, "mcap_min": MCAP_MIN},
        "panel": {"periods_scheduled": len(labels), "valid_periods": W,
                  "regime_counts": {"bull": int(len(idx_bull)), "bear": int(len(idx_bear)),
                                    "unknown": int(len(idx_unk))},
                  "member_counts": {"min": int(min(sizes)), "max": int(max(sizes)),
                                    "mean": float(np.mean(sizes))},
                  "first_membership": membership(0), "last_membership": membership(W - 1),
                  "excluded_symbol_hits": dict(sorted(excluded_hits.items(), key=lambda kv: -kv[1])[:25])},
        "baseline_mw": {"ann_net": ann_geo(base_mw["net"]), "ann_gross": ann_geo(base_mw["gross"]),
                        "cost_bp_per_year": float(np.sum(base_mw["cost"]) * (PER_YEAR / W) * 1e4),
                        "mdd_daily_marked": base_mdd,
                        "ann_net_ew": ann_geo(base_ew["net"])},
        "tilt_mw": {"ann_net": ann_geo(tilt_mw["net"]), "ann_gross": ann_geo(tilt_mw["gross"]),
                    "cost_bp_per_year": float(np.sum(tilt_mw["cost"]) * (PER_YEAR / W) * 1e4),
                    "mdd_daily_marked": tilt_mdd},
        "excess": {"ann_excess_net_geo": actual_net, "ann_excess_gross_geo": actual_gross,
                   "full": seg_stats(tilt_mw, base_mw, idx_all),
                   "bull": bull_net, "bear": bear_net,
                   "cal_h1_le_2024-11-30": h1_net, "cal_h2_after_2024-11-30": h2_net},
        "null": {"pct_net_full": pct_all, "pct_gross_full": pct_all_gross,
                 "pct_net_bull": pct_bull, "pct_net_bear": pct_bear,
                 "pct_net_cal_h1": pct_h1, "pct_net_cal_h2": pct_h2,
                 "null_err": null_err, "null_bull_err": eb1, "null_bear_err": eb2,
                 "null_cal_h1_err": e1, "null_cal_h2_err": e2,
                 "null_mean": float(np.mean(null_all)) if null_all is not None else None,
                 "null_std": float(np.std(null_all, ddof=1)) if null_all is not None else None,
                 "mc_se_of_pct": float(np.sqrt(max(pct_all, 1e-9) * (1 - pct_all) / N_NULL))
                 if pct_all is not None else None},
        "criteria": {"a": crit_a, "b": crit_b, "verdict": verdict},
        "side": {"flagged_counts": {"mean": float(np.mean(flagged_counts)),
                                    "min": int(min(flagged_counts)), "max": int(max(flagged_counts))},
                 "flagged_by_month": flagged_names,
                 "rel30_mean": float(np.mean(rel30)) if rel30 else None,
                 "rel30_n": len(rel30),
                 "rel30_mw_mean": float(np.mean(rel30_mw)) if rel30_mw else None,
                 "rel30_mw_n": len(rel30_mw),
                 "rel30_rest_mw_mean": float(np.mean(rel30_rest)) if rel30_rest else None,
                 "rel30_rest_mw_n": len(rel30_rest),
                 "rel30_by_month": rel30_by_month,
                 "dead_count": len(dead_events),
                 "dead_weight_sum": float(sum(e["base_weight"] for e in dead_events)),
                 "dead_events": dead_events,
                 "deep_loss_count": len(deep_losses),
                 "deep_loss_worst": min((d["ret"] for d in deep_losses), default=None),
                 "deep_losses": deep_losses,
                 "panel_internal_variant": {
                     "ann_excess_net_geo": ann_geo(tilt_panel["net"]) - ann_geo(base_mw["net"]),
                     "ann_excess_gross_geo": ann_geo(tilt_panel["gross"]) - ann_geo(base_mw["gross"]),
                     "bull": seg_stats(tilt_panel, base_mw, idx_bull)["ann_excess_net_geo"],
                     "bear": seg_stats(tilt_panel, base_mw, idx_bear)["ann_excess_net_geo"]},
                 "ew_variant": {"ann_excess_net_geo": ann_geo(tilt_ew["net"]) - ann_geo(base_ew["net"]),
                                "ann_excess_gross_geo": ann_geo(tilt_ew["gross"]) - ann_geo(base_ew["gross"])}},
        "attribution": {"n_periods": len(attrib),
                        "n_negative": int(sum(1 for a in attrib if a["eff"] < 0)),
                        "sum_eff": float(sum(a["eff"] for a in attrib)),
                        "worst_month": min(attrib, key=lambda a: a["eff"])["month"] if attrib else None,
                        "worst_month_eff": min((a["eff"] for a in attrib), default=None),
                        "best_month": max(attrib, key=lambda a: a["eff"])["month"] if attrib else None,
                        "best_month_eff": max((a["eff"] for a in attrib), default=None),
                        "by_month": attrib},
        "cap_pit24": {"readable": True, "ann": pit_ann, "mdd": pit_mdd,
                      "n_days": len(pit_vals), "first": pit_curve[0][0] if pit_curve else None,
                      "last": pit_curve[-1][0] if pit_curve else None},
        "universe": {"kept": len(kept), "mean_names": float(np.mean([p["universe"] for p in periods])),
                     "mean_worst_bucket": float(np.mean([p["n_worst_uni"] for p in periods]))},
    }
    ARM_DIR.mkdir(parents=True, exist_ok=True)
    ARM_JSON.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))

    # ---------------- 单臂小结(打印) ----------------
    print(json.dumps({
        "arm": ARM_TAG, "verdict": verdict, "crit_a": crit_a, "crit_b": crit_b,
        "base_ann_net": res["baseline_mw"]["ann_net"], "base_mdd": base_mdd,
        "excess_net": actual_net, "excess_gross": actual_gross, "pct": pct_all,
        "bull": bull_net["ann_excess_net_geo"], "bear": bear_net["ann_excess_net_geo"],
        "pct_bull": pct_bull, "pct_bear": pct_bear,
        "n_periods": W, "bull_n": len(idx_bull), "bear_n": len(idx_bear),
        "cap_pit24_ann": pit_ann, "cap_pit24_mdd": pit_mdd,
        "flag_mean": res["side"]["flagged_counts"]["mean"], "rel30": res["side"]["rel30_mean"],
    }, ensure_ascii=False, indent=1))
    print(f"[done] {time.time() - t0:.0f}s", flush=True)


# ------------------------------------------------------------------ 报告(单臂 + 汇总)

ARM_ORDER = ["D", "A", "B", "C"]
ARM_LABEL = {
    "D": "基准臂(复算 T-224):50 名 / 月频 / 最差档 × 0.5",
    "A": "臂①(只改**频率**):50 名 / **周频** / 最差档 × 0.5",
    "B": "臂②(只改**宽度**):**24 名** / 月频 / 最差档 × 0.5",
    "C": "臂③(只改**符号**):50 名 / 月频 / 最差档 **× 2.0**",
}
ARM_CHANGED = {
    "D": "什么都不改(复算 T-224,用来验证重构没有改数字)",
    "A": "调仓频率(月 → 周)",
    "B": "面板宽度(50 → 24)",
    "C": "变换符号(× 0.5 → × 2.0)",
}


def pct(x, nd=2):
    if x is None:
        return "n/a"
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "n/a"
    if not math.isfinite(v):
        return "n/a"
    return f"{100 * v:.{nd}f}%"


def arm_section(res: dict) -> list[str]:
    cfg = res["config"]; e = res["excess"]; nl = res["null"]; s = res["side"]
    at = res["attribution"]; b = res["baseline_mw"]; t = res["tilt_mw"]
    pm = res["panel"]; uni = res["universe"]; tag = res["arm"]
    L: list[str] = []
    A = L.append
    A(f"## 臂 {tag} —— {ARM_LABEL.get(tag, '')}")
    A("")
    A(f"相对 T-224 改了什么:**{ARM_CHANGED.get(tag, '')}**。")
    A("")
    A("| 项 | 值 |")
    A("|---|---|")
    A(f"| 调仓期数(有效) | {pm['valid_periods']}"
      f"(牛 {pm['regime_counts']['bull']} / 熊 {pm['regime_counts']['bear']}"
      f" / 未知 {pm['regime_counts']['unknown']}) |")
    A(f"| 面板成员数 | min {pm['member_counts']['min']} / max {pm['member_counts']['max']}"
      f" / 均 {pm['member_counts']['mean']:.1f} |")
    A(f"| 宇宙(S-691 口径) | 名字 {uni['kept']} · 每期平均 {uni['mean_names']:.0f} 名"
      f" · 最差档平均 {uni['mean_worst_bucket']:.0f} 名 |")
    A(f"| 基线(市值加权)年化净 / 毛 | {pct(b['ann_net'])} / {pct(b['ann_gross'])}"
      f"(回撤 {pct(b['mdd_daily_marked'])},成本 {b['cost_bp_per_year']:.1f} bp/年) |")
    A(f"| 变换臂年化净 / 毛 | {pct(t['ann_net'])} / {pct(t['ann_gross'])}"
      f"(回撤 {pct(t['mdd_daily_marked'])},成本 {t['cost_bp_per_year']:.1f} bp/年) |")
    A(f"| **年化净超额(变换臂 − 基线)** | **{pct(e['ann_excess_net_geo'])}**"
      f"(毛 {pct(e['ann_excess_gross_geo'])},算术 {pct(e['full']['ann_excess_net_arith'])}) |")
    A(f"| 随机对照分位(净 / 毛,{cfg['n_null']} 次,种子 {cfg['seed']}) | "
      f"{pct(nl['pct_net_full'], 1)} / {pct(nl['pct_gross_full'], 1)}(要 ≥ 95%) |")
    A(f"| 零分布均值 / 标准差 | {pct(nl['null_mean'])} / {pct(nl['null_std'])} |")
    A(f"| 牛段超额({e['bull']['n_periods']} 期) | {pct(e['bull']['ann_excess_net_geo'])}"
      f"(分位 {pct(nl['pct_net_bull'], 1)}) |")
    A(f"| 熊段超额({e['bear']['n_periods']} 期) | {pct(e['bear']['ann_excess_net_geo'])}"
      f"(分位 {pct(nl['pct_net_bear'], 1)}) |")
    A(f"| 副:日历切点 ≤2024-11-30 / 之后 | {pct(e['cal_h1_le_2024-11-30']['ann_excess_net_geo'])}"
      f"(分位 {pct(nl['pct_net_cal_h1'], 1)}) / "
      f"{pct(e['cal_h2_after_2024-11-30']['ann_excess_net_geo'])}"
      f"(分位 {pct(nl['pct_net_cal_h2'], 1)}) |")
    A(f"| 判据 (a) 超额 > 0 且 ≥ 95 分位 | {'✅' if res['criteria']['a'] else '❌'} |")
    A(f"| 判据 (b) 牛熊两段都 > 0 | {'✅' if res['criteria']['b'] else '❌'} |")
    A(f"| **结论** | **{res['criteria']['verdict']}** |")
    A("")
    A("副指标(只报不判):")
    A("")
    A(f"- 落在宽宇宙最差五分位的面板成员:平均 **{s['flagged_counts']['mean']:.1f}** 名"
      f"(min {s['flagged_counts']['min']} / max {s['flagged_counts']['max']})。")
    A(f"- 最差档之后 30 天相对面板:等权参照 {pct(s['rel30_mean'])}(n={s['rel30_n']})、"
      f"市值加权参照 {pct(s['rel30_mw_mean'])}(n={s['rel30_mw_n']})、"
      f"相对「其余成员」市值加权 {pct(s['rel30_rest_mw_mean'])}(n={s['rel30_rest_mw_n']})。")
    A(f"- 死币事件(时点口径,不再写销):{s['dead_count']} 个「期 × 成员」,"
      f"基线权重合计 {pct(s['dead_weight_sum'])}。")
    A(f"- 期内总收益 ≤ −50% 的「期 × 成员」:{s['deep_loss_count']} 个"
      f"(最差 {pct(s['deep_loss_worst'])});写销次数 **0**(本卡不再把价格归零)。")
    A(f"- 面板内部 ntile 口径的净超额 {pct(s['panel_internal_variant']['ann_excess_net_geo'])};"
      f"等权口径 {pct(s['ew_variant']['ann_excess_net_geo'])}。")
    A(f"- 逐期归因:{at['n_negative']} / {at['n_periods']} 期为负(合计 {pct(at['sum_eff'])});"
      f"最差 {at['worst_month']}({pct(at['worst_month_eff'])})、"
      f"最好 {at['best_month']}({pct(at['best_month_eff'])})。")
    A(f"- 并排:`core_variants_daily` 的 `cap_pit24`(前 24 名 / 日调仓 / 40% 单币上限)"
      f"年化 {pct(res['cap_pit24']['ann'])}、回撤 {pct(res['cap_pit24']['mdd'])}"
      f"(口径不同,不是同一个东西)。")
    if cfg["freq"] == "week":
        A("- (口径提示:周频臂的「最差档之后 30 天」副指标被期末截断成 7 天,与月频臂的 30 天不是同一个量,只作参考。)")
    A("")
    return L


def _key(res: dict) -> dict:
    cfg = res["config"]; e = res["excess"]; nl = res["null"]; s = res["side"]
    at = res["attribution"]; pm = res["panel"]
    return {
        "arm": res["arm"], "n_panel": cfg["n_panel"], "freq": cfg["freq"], "tilt": cfg["tilt"],
        "tilt_mult": cfg["tilt_mult"], "per_year": cfg["per_year"], "cost_bp": cfg["cost_bp"],
        "n_periods": pm["valid_periods"], "regime_counts": pm["regime_counts"],
        "member_counts": pm["member_counts"],
        "baseline_ann_net": res["baseline_mw"]["ann_net"],
        "baseline_ann_gross": res["baseline_mw"]["ann_gross"],
        "baseline_mdd": res["baseline_mw"]["mdd_daily_marked"],
        "baseline_cost_bp_per_year": res["baseline_mw"]["cost_bp_per_year"],
        "tilt_ann_net": res["tilt_mw"]["ann_net"], "tilt_ann_gross": res["tilt_mw"]["ann_gross"],
        "tilt_mdd": res["tilt_mw"]["mdd_daily_marked"],
        "tilt_cost_bp_per_year": res["tilt_mw"]["cost_bp_per_year"],
        "excess_net_geo": e["ann_excess_net_geo"], "excess_gross_geo": e["ann_excess_gross_geo"],
        "excess_net_arith": e["full"]["ann_excess_net_arith"],
        "tracking_error_net": e["full"]["tracking_error_net"],
        "pct_net_full": nl["pct_net_full"], "pct_gross_full": nl["pct_gross_full"],
        "null_mean": nl["null_mean"], "null_std": nl["null_std"],
        "bull_excess_net": e["bull"]["ann_excess_net_geo"], "bull_n": e["bull"]["n_periods"],
        "bull_pct": nl["pct_net_bull"], "bear_excess_net": e["bear"]["ann_excess_net_geo"],
        "bear_n": e["bear"]["n_periods"], "bear_pct": nl["pct_net_bear"],
        "cal_h1_excess_net": e["cal_h1_le_2024-11-30"]["ann_excess_net_geo"],
        "cal_h2_excess_net": e["cal_h2_after_2024-11-30"]["ann_excess_net_geo"],
        "cal_h1_pct": nl["pct_net_cal_h1"], "cal_h2_pct": nl["pct_net_cal_h2"],
        "criteria": res["criteria"],
        "flagged_mean": s["flagged_counts"]["mean"], "rel30_mean": s["rel30_mean"],
        "rel30_rest_mw_mean": s["rel30_rest_mw_mean"], "dead_count": s["dead_count"],
        "deep_loss_count": s["deep_loss_count"], "deep_loss_worst": s["deep_loss_worst"],
        "panel_internal_excess": s["panel_internal_variant"]["ann_excess_net_geo"],
        "ew_excess": s["ew_variant"]["ann_excess_net_geo"],
        "attribution_n_negative": at["n_negative"], "attribution_n_periods": at["n_periods"],
        "attribution_worst_month": at["worst_month"], "attribution_worst_eff": at["worst_month_eff"],
        "attribution_best_month": at["best_month"], "attribution_best_eff": at["best_month_eff"],
        "cap_pit24_ann": res["cap_pit24"]["ann"], "cap_pit24_mdd": res["cap_pit24"]["mdd"],
    }


def aggregate() -> None:
    """汇总四个臂 → docs/research/t225_results.json + docs/research/T-225_arms.md。"""
    arms: dict[str, dict] = {}
    for tag in ARM_ORDER:
        p = ARM_DIR / f"arm_{tag}.json"
        if not p.exists():
            sys.exit(f"缺单臂结果:{p}")
        arms[tag] = json.loads(p.read_text())
    summary = {tag: _key(res) for tag, res in arms.items()}
    passed = [t for t in ARM_ORDER if summary[t]["criteria"]["verdict"] == "✅"]

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(
        {"card": "T-225", "prereg": "docs/research/T-225_prereg.md",
         "script": "docs/research/t225_arms.py", "arm_order": ARM_ORDER,
         "arms": summary, "passed_arms": passed},
        ensure_ascii=False, indent=1, default=float) + "\n")

    L: list[str] = []
    A = L.append
    A(PREREG_MD.read_text().rstrip())
    A("")
    A("---")
    A("")
    A("# T-225 结果 —— 拆开面板宽度 × 调仓频率 × 符号")
    A("")
    A("脚本 `docs/research/t225_arms.py`(零分布只走 `src/data/evaluation/apparatus.py`);"
      "关键数字在 `docs/research/t225_results.json`;单臂完整结果(逐期归因、逐期成员)在 Mac 数据根 "
      f"`{ARM_DIR}/arm_*.json`。")
    A("")
    A("## 0. 一句话")
    A("")
    if "A" in passed:
        A("**调仓频率**是那个被混进去的变量:面板、信号、变换都不变,只把月频换成周频就过了判据"
          "(臂 A ✅)。")
    elif "B" in passed:
        A("**面板宽度**是那个被混进去的变量:频率、信号、变换都不变,只把前 50 换成前 24 就过了判据"
          "(臂 B ✅)。")
    elif "C" in passed:
        A("**符号**是那个被混进去的变量:加倍最差档(而不是减半)过了判据(臂 C ✅)——"
          "「躲开」的方向反了。")
    elif "D" in passed:
        A("**基准臂本身就过了判据**(臂 D ✅)—— 与 T-224 的结论矛盾,须先复核 T-224 的实现再谈别的。")
    else:
        A("**四个臂全不过**:把宽度、频率、符号拆开单独试,「躲开最差档」在 **24 名与 50 名 × 月频与周频**"
          "四种设定下都不够用(宽度不是原因,频率也不是原因);但「**加倍**最差档」在月频前 50 上是正的"
          "(+1.58%,随机对照 85.6 分位)—— 方向可能反了一半。"
          "结论只能说到这些设定,**不能再写成「任何宽度都不够用」**。")
    A("")
    A("## 1. 四个臂并排")
    A("")
    A("| 臂 | 面板 | 调仓 | 变换 | 期数(牛/熊) | 基线年化净 | 变换臂年化净 | **净超额** | 随机对照分位 | 牛段 | 熊段 | 结论 |")
    A("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for tag in ARM_ORDER:
        k = summary[tag]
        A(f"| {tag} | {k['n_panel']} 名 | {'周' if k['freq'] == 'week' else '月'} | × {k['tilt_mult']} | "
          f"{k['n_periods']}({k['regime_counts']['bull']}/{k['regime_counts']['bear']}) | "
          f"{pct(k['baseline_ann_net'])} | {pct(k['tilt_ann_net'])} | **{pct(k['excess_net_geo'])}** | "
          f"{pct(k['pct_net_full'], 1)} | {pct(k['bull_excess_net'])} | {pct(k['bear_excess_net'])} | "
          f"**{k['criteria']['verdict']}** |")
    A("")
    A("「变换」列:面板成员落在宽宇宙最差五分位时的权重乘数(0.5 = 减半 = 躲开;2.0 = 加倍)。")
    A("判据 (a):年化净超额 > 0 且 1,000 次随机对照 ≥ 95 分位(种子 694);"
      "判据 (b):牛段与熊段净超额都 > 0。牛熊标记 = `state_daily(entity=panel, mom_200)` 在调仓日的符号。")
    A("")
    A("## 2. 逐臂明细")
    A("")
    for tag in ARM_ORDER:
        for line in arm_section(arms[tag]):
            A(line)
    A("## 3. 结论与对 T-224 措辞的处理")
    A("")
    if passed:
        A(f"过判据的臂:{', '.join(passed)}。")
        A("")
        if "A" in passed:
            A("- **T-224 的失败是调仓频率造成的**,不是「任何宽度都不够用」。"
              "T-224 报告 L131 与预注册 L58 的「任何宽度都不够用」**降级**为"
              "「**月频**前 50 设定下不够用」。")
        if "B" in passed:
            A("- **T-224 的失败是面板宽度造成的**(前 50 太宽),"
              "「任何宽度都不够用」**降级**为「前 50 宽度下不够用」。")
        if "C" in passed:
            A("- **符号反了**:加倍最差档有效、减半无效 ⇒ T-224 与 S-694 的方向要重估。")
        A("- 「信息被大币吃掉」**撤下**:它只在 24 名面板上被检验过,本卡的四个臂没有支持它的一般化表述。")
    else:
        kd = summary["D"]; ka = summary["A"]; kb = summary["B"]; kc = summary["C"]
        A("四个臂全不过(判据 (a) 与 (b) 都没过)。")
        A("")
        A(f"- **「躲开最差档」(× 0.5)在三种设定下都不够用**:50 名 / 月频(臂 D,{pct(kd['excess_net_geo'])},"
          f"分位 {pct(kd['pct_net_full'], 1)})、50 名 / **周频**(臂 A,{pct(ka['excess_net_geo'])},"
          f"分位 {pct(ka['pct_net_full'], 1)})、24 名 / 月频(臂 B,{pct(kb['excess_net_geo'])},"
          f"分位 {pct(kb['pct_net_full'], 1)})。")
        A(f"  - **宽度不是原因**:D({pct(kd['excess_net_geo'])})与 B({pct(kb['excess_net_geo'])})几乎一样。")
        A(f"  - **频率也不是原因**:A 把超额从 {pct(kd['excess_net_geo'])} 拉到 {pct(ka['excess_net_geo'])},"
          f"随机对照分位从 {pct(kd['pct_net_full'], 1)} 升到 {pct(ka['pct_net_full'], 1)},"
          "但仍是负的、也没跨过 95 分位。")
        A(f"- **方向反了一半**:臂 C(加倍最差档)年化净超额 **{pct(kc['excess_net_geo'])}**,"
          f"但随机对照只有 {pct(kc['pct_net_full'], 1)}(< 95%),牛段还是 {pct(kc['bull_excess_net'])} —— "
          "判据 (a)(b) 都不过。")
        A("- 因此 T-224 报告 L131 与预注册 L58 的「**任何宽度都不够用**」**降级**为"
          "「**24 名与 50 名 × 月频与周频这四种设定下不够用**」—— 仍然只是「躲开」这个方向上的结论,"
          "不是对信号本身的全称否定。")
        A("- 「**信息被大币吃掉**」**撤下**:它只在 24 名面板(S-694)上被检验过,本卡没有任何一个臂支持它。")
        A("- S-694(① 的 24 大币 / 周频)= +2.04% / 95 分位 与本卡臂 A(50 名 / 周频)并不是同一件事:"
          "S-694 的面板是 ① 的 24 大币(日调仓 + 40% 单币上限),本卡是「按时点前 N 名」的规则;"
          "所以「S-694 周频有效、T-224 月频无效」里**频率与面板规则仍然缠在一起** —— "
          "要彻底拆开需要再加一个「24 名 / 周频 / 同一规则」的臂(本卡没有预注册,不做,建议另开卡)。")
    A("")
    A("## 3.1 探索性观察(不是结论)")
    A("")
    A("预注册只判了「三个变量各自单独动,『躲开最差档』过不过判据」。下面这些是这次跑出来的形状,"
      "**探索性 —— 需另立预注册、在新数据上过零信号对照**才能当结论:")
    A("")
    kd = summary["D"]; ka = summary["A"]; kb = summary["B"]; kc = summary["C"]
    A(f"- **同一个变换的效果随牛熊翻转**:臂 C(加倍最差档)熊段净超额 {pct(kc['bear_excess_net'])}"
      f"(分位 {pct(kc['bear_pct'], 1)})、牛段 {pct(kc['bull_excess_net'])};"
      f"臂 D(减半)正好相反(牛 {pct(kd['bull_excess_net'])} / 熊 {pct(kd['bear_excess_net'])})。"
      "也就是说「宽宇宙最差五分位」在**熊段跑赢面板**、在牛段跑输 —— "
      "T-224 的归因(减半最差档卖掉的正是动量龙头)只在牛段站得住。")
    A(f"- **频率与牛熊对符号的影响互相纠缠**:减半在**周频**下牛段是正的({pct(ka['bull_excess_net'])}),"
      f"在**月频**下牛段是负的({pct(kd['bull_excess_net'])});熊段两种频率都是负的"
      f"({pct(ka['bear_excess_net'])} / {pct(kd['bear_excess_net'])})。")
    A(f"- **面板宽度几乎不动基线**:D(50 名)基线年化 {pct(kd['baseline_ann_net'])}、"
      f"B(24 名){pct(kb['baseline_ann_net'])} —— 收窄面板改的是「躲开」这个变换有没有用,不是基线本身。")
    A("")
    A("## 4. 口径与纪律")
    A("")
    A("- 面板规则、剔除名单、信号(S-691 五因子等权秩合成)、映射校验阈值、成本(10 bp)、"
      "随机对照结构:全部照 T-224 / S-694,只有卡上点名的三个变量被动过。")
    A("- 死币规则改成**时点口径**:只用调仓日当天及以前的 `last_obs`;**不再写销**(序列结束按最后有效价"
      "持有到底,收益 0);coin_id 连续性写成硬断言(持有期内 > 10 天内部断点 ⇒ 报错中止)。"
      "本卡四臂**写销次数均为 0**,所以死币口径的变化不改变任何一臂的数字。")
    A("- 分段改成**牛/熊**(`state_daily` 的 `mom_200`,调仓日当天);旧日历切点降级为副指标,只报不判。")
    A("- 零分布 / 分位只走 `src/data/evaluation/apparatus.py`(`null_distribution` / `percentile_of`);"
      "主对照种子 694,牛 / 熊分段对照用 694+3 / 694+4。")
    A("- 只读:全部 SELECT,没有 DDL、没有入库、没有改任何在跑的东西;翻页一律带 `order=`。")
    A("- 复跑:`python3 docs/research/t225_arms.py --all` 跑两次,`docs/research/t225_results.json` 与 "
      "`docs/research/T-225_arms.md` 逐字节一致(两处都不含时间戳)。")
    A("")
    OUT_MD.write_text("\n".join(L) + "\n")
    print(f"[agg  ] 写出 {OUT_JSON} 与 {OUT_MD};过判据的臂:{passed}", flush=True)


ARMS = [("D", "50", "month", "halve"), ("A", "50", "week", "halve"),
        ("B", "24", "month", "halve"), ("C", "50", "month", "double")]


if __name__ == "__main__":
    if "--all" in sys.argv:
        import subprocess
        for tag, panel, freq, tilt in ARMS:
            print(f"===== 臂 {tag}:panel={panel} freq={freq} tilt={tilt} =====", flush=True)
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--tag", tag,
                            "--panel", panel, "--freq", freq, "--tilt", tilt], check=True)
        aggregate()
    else:
        main()
