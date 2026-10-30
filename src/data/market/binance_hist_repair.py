"""`binance_hist` 统一成一个约定(Binance 现货 USDT 日线)+ 往前补深度(S-698,扩充矢量库的地基)。

## 为什么

2026-10-30 实测(台账 S-698):这个标签下 209 个有 2025-06-15 日线的标的里,**168 个是 U 本位永续的 bar,只有 41 个是现货**;
2026-08-08 起 `deep_panel_collector` 走现货 API 写同一个标签 ⇒ 136 个标的在那一天从永续拼到现货,32 个没有现货对的从那天起停更。
价格只差基差,**成交量差 5–10 倍** —— 所有吃 `close × volume` 的东西(ADV 门槛、R-v2 的放量条件、矢量库的量维)在拼接处看到一道悬崖。
模块文档里写着「bar 约定是源的属性」,而这张表的一个源里装着两个约定(S-106 的形状)。

## 做什么(每个标的,按顺序;任一步不过 ⇒ 这个标的不写,原因进 detail)

1. 现货月档目录(data.binance.vision 静态档,不是 API;同一个取数入口 `get_binance_vision_um_daily(market="spot")`)。
   没有现货对 ⇒ `no_spot_pair`:把它的行**复制**到 `binance_um_hist`(存档),原行不动 —— 名单见 `PERP_ONLY_NOTE`。
2. 读表里这个标的的全部 `binance_hist` 行;取现货月档(上市第一个月 → `CHECK_MONTHS`)。
3. **同一个对的证明**:表里与档里重叠的日子,收盘中位相对差 < 0.5%(基差量级;同名不同币会差几十个百分点),且重叠 ≥ 20 天。
   另外,若 `CHECK_MONTHS`(收集器写现货之后)有重叠,那几个月必须**逐位一致**。
4. 逐日:表里与现货逐位一致的行不动;**不一致的行先原样复制到 `binance_um_hist`,再用现货覆盖**;
   现货有、表里没有的日子补进来(深度 / 洞);表里有、现货没有的日子(永续早于现货上市等)复制存档、原行不动、计数报告。
5. 只写 `LAST_MONTH` 及之前的月份 —— 之后的月份归每日收集器,这里只核不写。

**不删任何一行。** 原来的永续 bar 全在 `binance_um_hist`,要恢复就是一次反向复制。

## 节奏

S3 静态档,4 路并发、每个请求后歇 0.1 秒;每轮最多 `TIME_BUDGET_S` 秒,下一轮接着做(做过的标的按 `VERSION` 记在 loop_attempt 里)。

判活:`select detail->'done' from loop_attempt where loop_name = '_binance_hist_repair_loop' order by at desc limit 1`;
复核:`select count(*) from ohlcv_daily where source = 'binance_um_hist'`;TRX 的第一行应早于 2020-01-15(现货 2018-06 上市)。
"""
from __future__ import annotations

import asyncio
import csv
import io
import re
import statistics
import time
import zipfile
from datetime import datetime, timezone
from typing import Any, Optional

SOURCE = "binance_hist"
ARCHIVE = "binance_um_hist"
VERSION = 1
LOOP_NAME = "_binance_hist_repair_loop"
LAST_MONTH = "2026-08"                 # 2026-08-08 起收集器写现货(自愈窗口会往回改几天);9 月起只核不写
CHECK_MONTHS = ("2026-09",)            # 收集器时代:档必须与表逐位一致
PRICE_TOL = 1e-4                       # 表里是 float4(约 7 位);永续与现货的差在 1e-4 以上
VOL_TOL = 1e-3
SAME_ASSET_MEDIAN = 0.005              # 收盘中位相对差:基差量级;同名不同币差几十个百分点
SAME_ASSET_MIN_DAYS = 20
CONCURRENCY = 4
PAUSE_S = 0.1
TIME_BUDGET_S = 900.0
CHUNK = 2000
WRITES_TABLES = ("ohlcv_daily",)
#: 先只做这几个(拼接的 TRX / ETC、现货的 ADA / BTC、永续独有的 1000SHIB),Seth 用 SQL 核过结果再打开全量。
CANARY = ("TRX", "ETC", "ADA", "BTC", "1000SHIB")
FULL_RUN = False
PERP_ONLY_NOTE = ("S-698:没有现货对的标的(2026-10-30 实测 32 个,如 1000SHIB / 1000LUNC / BTCDOM / LUNA2 / XMR)仍在 binance_hist 里、"
                  "2026-08-08 起停更;它们的 bar 是永续的。面板读取方按 `perp_only` 名单显式排除。")

_MONTH_RE = re.compile(r"-1d-(\d{4}-\d{2})\.zip$")
_KEY_RE = re.compile(r"<Key>([^<]+)</Key>")


# ── 纯函数 ──────────────────────────────────────────────────────────────────

def parse_month_keys(xml: bytes) -> list[str]:
    """现货月档目录页 → 'YYYY-MM' 升序(去掉 .CHECKSUM)。"""
    x = xml.decode("utf-8", errors="replace")
    return sorted({m.group(1) for k in _KEY_RE.findall(x) if (m := _MONTH_RE.search(k))})


def parse_spot_zip(blob: bytes) -> dict[str, tuple[float, float, float, float, float]]:
    """现货 klines 月档 → {UTC 日期: (o, h, l, c, 基础币成交量)}。时间戳是开盘时刻(2025 起部分档是微秒)。"""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = [n for n in z.namelist() if n.endswith(".csv")]
        if not names:
            raise ValueError("zip 里没有 csv")
        text = z.read(names[0]).decode("utf-8", errors="replace")
    out: dict[str, tuple[float, float, float, float, float]] = {}
    for r in csv.reader(io.StringIO(text)):
        if not r or not r[0].strip().isdigit():
            continue
        try:
            t = int(r[0])
            t = t // 1000 if t > 10 ** 14 else t
            d = datetime.fromtimestamp(t / 1000, tz=timezone.utc).date().isoformat()
            o, h, l, c, v = (float(x) for x in r[1:6])
        except (IndexError, ValueError):
            continue
        if c > 0:
            out[d] = (o, h, l, c, v)
    return out


def _rel(a: float, b: float) -> float:
    return abs(a - b) / max(abs(b), 1e-300)


def same_bar(row: dict, bar: tuple[float, float, float, float, float]) -> bool:
    """表里的一行与现货档的一根是不是同一根(逐位,容 float4 的舍入)。"""
    try:
        o, h, l, c, v = (float(row[k]) for k in ("open", "high", "low", "close", "volume"))
    except (KeyError, TypeError, ValueError):
        return False
    return (all(_rel(x, y) <= PRICE_TOL for x, y in ((o, bar[0]), (h, bar[1]), (l, bar[2]), (c, bar[3])))
            and _rel(v, bar[4]) <= VOL_TOL)


def plan_symbol(sym: str, table: dict[str, dict], spot: dict[str, tuple], last_month: str = LAST_MONTH,
                check_months: tuple[str, ...] = CHECK_MONTHS) -> dict[str, Any]:
    """纯函数。一个标的:表里的行(按日)+ 现货 bar(按日)→ 要存档的、要覆盖的、要补的,以及判定。"""
    both = sorted(d for d in table if d in spot)
    if len(both) < SAME_ASSET_MIN_DAYS:
        return {"verdict": "too_little_overlap", "overlap_days": len(both)}
    gaps = [_rel(float(table[d]["close"]), spot[d][3]) for d in both]
    med = statistics.median(gaps)
    if med > SAME_ASSET_MEDIAN:
        return {"verdict": "not_same_asset", "overlap_days": len(both), "median_close_gap": round(med, 5)}
    chk = [d for d in both if d[:7] in check_months]
    if chk and not all(same_bar(table[d], spot[d]) for d in chk):
        bad = [d for d in chk if not same_bar(table[d], spot[d])]
        return {"verdict": "collector_era_mismatch", "overlap_days": len(both), "bad_days": bad[:5]}
    writable = lambda d: d[:7] <= last_month                              # noqa: E731
    mismatch = [d for d in both if writable(d) and not same_bar(table[d], spot[d])]
    missing = sorted(d for d in spot if d not in table and writable(d))
    extra = sorted(d for d in table if d not in spot and writable(d))
    asset_class = next((r.get("asset_class") for r in table.values() if r.get("asset_class")), "Crypto")

    def spot_row(d: str) -> dict:
        o, h, l, c, v = spot[d]
        return {"symbol": sym, "asset_class": asset_class, "trade_date": d, "open": o, "high": h, "low": l,
                "close": c, "volume": v, "source": SOURCE}

    def archive_row(d: str) -> dict:
        r = table[d]
        return {"symbol": sym, "asset_class": r.get("asset_class") or asset_class, "trade_date": d,
                **{k: float(r[k]) for k in ("open", "high", "low", "close", "volume")}, "source": ARCHIVE}

    return {"verdict": "ok", "overlap_days": len(both), "median_close_gap": round(med, 6),
            "archive": [archive_row(d) for d in mismatch + extra],
            "write": [spot_row(d) for d in mismatch + missing],
            "n_overwrite": len(mismatch), "n_insert": len(missing), "n_nonspot_extra": len(extra),
            "first_before": min(table) if table else None,
            "first_after": min([*table, *missing]) if (table or missing) else None}


def done_from(rows: list[dict], version: int = VERSION) -> dict[str, str]:
    """前几轮做过的标的(同一版本)。"""
    done: dict[str, str] = {}
    for r in rows or []:
        det = r.get("detail") or {}
        if det.get("v") != version:
            continue
        for s, v in (det.get("done") or {}).items():
            done.setdefault(s, v)
    return done


# ── 一轮 ────────────────────────────────────────────────────────────────────

async def _months(pair: str) -> list[str]:
    from src.data.market.data_layer import get_binance_vision_um_daily
    xml = await get_binance_vision_um_daily("klines", pair, "", monthly=True, index=True, market="spot")
    return parse_month_keys(xml or b"")


async def _spot_bars(pair: str, months: list[str]) -> dict[str, tuple]:
    from src.data.market.data_layer import get_binance_vision_um_daily
    sem = asyncio.Semaphore(CONCURRENCY)
    out: dict[str, tuple] = {}

    async def one(m: str):
        async with sem:
            blob = await get_binance_vision_um_daily("klines", pair, m, monthly=True, market="spot")
            await asyncio.sleep(PAUSE_S)
        if blob:
            out.update(parse_spot_zip(blob))
    await asyncio.gather(*[one(m) for m in months])
    return out


async def _upsert(rows: list[dict]) -> Optional[str]:
    from src.api.store import supabase_upsert_table
    for i in range(0, len(rows), CHUNK):
        r = await supabase_upsert_table("ohlcv_daily", rows[i:i + CHUNK], on_conflict="symbol,trade_date,source")
        if not r:
            return f"写入失败(第 {i // CHUNK + 1} 批):{(getattr(r, 'why', '') or '')[:160]}"
    return None


async def repair_symbol(sym: str) -> dict[str, Any]:
    from src.data.style.header import _read_all
    pair = f"{sym}USDT"
    months = await _months(pair)
    rows = await _read_all("ohlcv_daily", {"select": "symbol,asset_class,trade_date,open,high,low,close,volume",
                                           "source": f"eq.{SOURCE}", "symbol": f"eq.{sym}", "order": "trade_date.asc"})
    table = {str(r["trade_date"])[:10]: r for r in rows or []}
    if not months:
        arch = [{"symbol": sym, "asset_class": r.get("asset_class") or "Crypto", "trade_date": d,
                 **{k: float(r[k]) for k in ("open", "high", "low", "close", "volume")}, "source": ARCHIVE}
                for d, r in table.items() if r.get("close") is not None]
        why = await _upsert(arch) if arch else None
        return {"verdict": "error" if why else "no_spot_pair", "archived": len(arch), **({"why": why} if why else {})}
    want = [m for m in months if m <= max(LAST_MONTH, *CHECK_MONTHS)]
    spot = await _spot_bars(pair, want)
    p = plan_symbol(sym, table, spot)
    if p["verdict"] != "ok":
        return p
    why = await _upsert(p["archive"]) if p["archive"] else None          # 先存档,存不进去就不覆盖
    if not why and p["write"]:
        why = await _upsert(p["write"])
    out = {k: v for k, v in p.items() if k not in ("archive", "write")}
    out["spot_months"] = len(want)
    if why:
        out.update({"verdict": "error", "why": why})
    return out


async def run_once(time_budget: float = TIME_BUDGET_S, symbols: Optional[list[str]] = None) -> dict[str, Any]:
    from src.data.market.deep_panel_collector import deep_panel_symbols_detailed
    from src.data.market.source_policy import MARKET_DATA, assert_purpose_source
    t0 = time.monotonic()
    from src.data.signals.hl_book_daily import _supabase_get
    prev = await _supabase_get(f"loop_attempt?select=at,detail&loop_name=eq.{LOOP_NAME}&order=at.desc&limit=80")
    done = done_from(prev or [])
    if symbols is None:
        syms, detail, _latest = await deep_panel_symbols_detailed()
        if syms is None:
            return {"ok": False, "v": VERSION, "why": f"标的名单读不到:{str(detail)[:160]}", "done": {}}
    else:
        syms = symbols
    todo = [s for s in syms if s not in done or done[s] == "error"]
    if not FULL_RUN:
        todo = [s for s in CANARY if s in todo or (symbols is None and s not in done)]
    assert_purpose_source(MARKET_DATA, SOURCE, n_assets=max(len(todo), 1),
                          job="S-698 binance_hist spot rewrite + depth (data.binance.vision spot archive)", secondary_ok=True)
    this: dict[str, str] = {}
    notes: dict[str, Any] = {}
    for s in todo:
        if time.monotonic() - t0 > time_budget:
            break
        try:
            r = await repair_symbol(s)
        except Exception as e:                                           # noqa: BLE001 — 一个标的炸了,下一个照做
            r = {"verdict": "error", "why": f"{type(e).__name__}: {str(e)[:160]}"}
        this[s] = r["verdict"]
        if r["verdict"] != "ok" or r.get("n_overwrite") or r.get("n_insert"):
            notes[s] = {k: r[k] for k in ("verdict", "n_overwrite", "n_insert", "n_nonspot_extra", "first_before",
                                          "first_after", "archived", "why", "median_close_gap", "overlap_days")
                        if k in r}
    left = [s for s in todo if s not in this]
    return {"ok": not any(v == "error" for v in this.values()), "v": VERSION, "done": this, "notes": notes,
            "remaining": len(left), "already_done": len(done), "elapsed_s": round(time.monotonic() - t0, 1)}
