"""东京云主机:每 15 分钟记录 Hyperliquid 头部账户的持仓(T-130)。

## 它做什么

每隔 15 分钟一次:
1. **名单**(每天最多取一次):优先 `GET https://stats-data.hyperliquid.xyz/Mainnet/leaderboard`,
   按 30 天 PnL 排序 + 账户净值 ≥ 100 万美元,取前 200 名 / 有效地址。
   取不到或返回空 ⇒ `/var/lib/cometcloud/whales_addresses.txt`(一行一个地址),文件也没有则这一轮不轮询。
3. **轮询**:对名单里每个地址 `POST https://api.hyperliquid.xyz/info`
   `{type: clearinghouseState, user: <addr>}` → 解析 `assetPositions[]`,
   把每个币一条记录 append 到 `/var/lib/cometcloud/rec/whales/YYYY-MM-DD.jsonl.gz`。
4. **节流**:每轮 ≤ 200 次,每地址最多重试 2 次,单地址失败 / 单条记录失败不破坏整轮。
5. **不读私钥、不写 Supabase、不读执行器状态**:与 T-015 执行器解耦,纯观察。

## 不在它里面

- 不发任何签名请求(只 POST `info` 公共端点)
- 不修改交易所仓位
- 不与执行器共享状态 —— exec_host.whales 与 exec_host.runner 是同一个包里平行的两个模块
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

log = logging.getLogger("exec_host.whales")

LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
INFO_URL = "https://api.hyperliquid.xyz/info"
DEFAULT_ADDRESS_FILE = Path("/var/lib/cometcloud/whales_addresses.txt")
DEFAULT_REC_DIR = Path("/var/lib/cometcloud/rec/whales")
DEFAULT_TOP_N = 200
DEFAULT_AV_MIN_USD = 1_000_000
DEFAULT_RETRY = 2
DEFAULT_ROUND_BUDGET = 200
DEFAULT_REQUEST_TIMEOUT = 15.0
DEFAULT_INTER_REQUEST_SLEEP_S = 0.05  # 5% 余量;HL info 公共端点实测 ≈ 0.3s/req


# ── 时间 ─────────────────────────────────────────────────────────────────────
def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def utc_today(now: dt.datetime) -> str:
    return now.astimezone(dt.timezone.utc).date().isoformat()


# ── 名单 ─────────────────────────────────────────────────────────────────────
def _row_field(row: dict, window: str, key: str) -> float:
    for w, p in row.get("windowPerformances", []):
        if w == window and isinstance(p, dict):
            try:
                return float(p.get(key, 0) or 0)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def select_addresses(
    rows: Iterable[dict],
    top_n: int = DEFAULT_TOP_N,
    av_min_usd: float = DEFAULT_AV_MIN_USD,
) -> list[str]:
    """按 30 天 PnL 取前 N 且账户净值 ≥ 阈值的地址;去重保序。"""
    seen: set[str] = set()
    picked: list[str] = []
    # 注意:addresses 是字符串,leaderboard 直接给大小写不敏感的 hex;统一小写去重
    indexed: list[tuple[float, str, float]] = []
    for r in rows:
        addr = (r.get("ethAddress") or "").strip().lower()
        if not addr or addr in seen:
            continue
        seen.add(addr)
        try:
            av = float(r.get("accountValue", 0) or 0)
        except (TypeError, ValueError):
            av = 0.0
        if av < av_min_usd:
            continue
        mp = _row_field(r, "month", "pnl")
        indexed.append((mp, addr, av))
    # 30d PnL 降序:NaN/undefined 当成 -inf
    indexed.sort(key=lambda x: x[0], reverse=True)
    for _, addr, _ in indexed:
        if len(picked) >= top_n:
            break
        picked.append(addr)
    return picked


# ── 网络:仅用 stdlib urllib,与执行器同段独立超时 ─────────────────────────────
class Fetcher:
    """可注入 fetch,便于测试用 fake。"""

    def __init__(self, timeout: float = DEFAULT_REQUEST_TIMEOUT):
        self.timeout = timeout

    def leaderboard(self, url: str = LEADERBOARD_URL) -> Any:
        req = urllib.request.Request(url, headers={"User-Agent": "cometcloud-whales/1"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            raw = r.read()
        return json.loads(raw)

    def info(self, payload: dict, url: str = INFO_URL) -> Any:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json", "User-Agent": "cometcloud-whales/1"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            raw = r.read()
        return json.loads(raw)


def load_addresses_from_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    out: list[str] = []
    seen: set[str] = set()
    for line in path.read_text().splitlines():
        a = line.strip().lower()
        if not a or a.startswith("#") or a in seen:
            continue
        if not (a.startswith("0x") and len(a) == 42):
            continue
        seen.add(a)
        out.append(a)
    return out


# ── 名单缓存(一天取一次) ─────────────────────────────────────────────────────
def addresses_for_round(
    now: dt.datetime,
    fetcher: Fetcher,
    cache: dict[str, Any],
    address_file: Path = DEFAULT_ADDRESS_FILE,
    top_n: int = DEFAULT_TOP_N,
    av_min_usd: float = DEFAULT_AV_MIN_USD,
) -> tuple[list[str], str]:
    """返回 (list, source)。source ∈ {"leaderboard","file","empty","leaderboard_error","file_error"}。"""
    today = utc_today(now)
    last = cache.get("addresses_for_date")
    last_list = cache.get("addresses") or []
    if last == today and last_list:
        return list(last_list), "cache"

    source = "empty"
    addrs: list[str] = []
    try:
        rows = fetcher.leaderboard()
        rows_iter = (rows.get("leaderboardRows") if isinstance(rows, dict) else None) or []
        addrs = select_addresses(rows_iter, top_n=top_n, av_min_usd=av_min_usd)
        if addrs:
            source = "leaderboard"
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, json.JSONDecodeError) as e:
        log.warning("leaderboard fetch failed: %s:%s", type(e).__name__, str(e)[:160])
        source = "leaderboard_error"

    if not addrs:
        try:
            addrs = load_addresses_from_file(address_file)
            source = "file" if addrs else "file_error" if source.endswith("error") else "empty"
        except OSError as e:
            log.warning("address file read failed: %s:%s", type(e).__name__, str(e)[:160])
            source = "file_error"

    cache["addresses_for_date"] = today
    cache["addresses"] = list(addrs)
    cache["addresses_source"] = source
    return list(addrs), source


# ── 单地址轮询 ───────────────────────────────────────────────────────────────
def _round_value(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    return round(v, 8)


def parse_clearinghouse(addr: str, raw: Any, ts_ms: int) -> list[dict]:
    """raw: info clearinghouseState 返回;产出一条或多条 record(无仓 → []).
    record 字段:ts, address, coin, szi, entryPx, positionValue, unrealizedPnl,
                leverage, leverage_type, marginUsed, accountValue.
    """
    if not isinstance(raw, dict):
        return []
    positions = raw.get("assetPositions") or []
    margin = raw.get("marginSummary") or {}
    av = _round_value(margin.get("accountValue"))
    out: list[dict] = []
    for entry in positions:
        if not isinstance(entry, dict):
            continue
        p = entry.get("position") or {}
        if not isinstance(p, dict):
            continue
        coin = p.get("coin")
        szi = _round_value(p.get("szi"))
        if not coin or szi is None or szi == 0:
            continue
        lev = p.get("leverage") or {}
        lev_val = _round_value(lev.get("value"))
        rec = {
            "ts": ts_ms,
            "address": addr,
            "coin": coin,
            "szi": szi,
            "entryPx": _round_value(p.get("entryPx")),
            "positionValue": _round_value(p.get("positionValue")),
            "unrealizedPnl": _round_value(p.get("unrealizedPnl")),
            "leverage": lev_val,
            "leverageType": (lev.get("type") if isinstance(lev, dict) else None),
            "marginUsed": _round_value(p.get("marginUsed")),
            "accountValue": av,
        }
        out.append(rec)
    return out


def fetch_one(
    addr: str,
    fetcher: Fetcher,
    retries: int = DEFAULT_RETRY,
) -> tuple[Optional[list[dict]], Optional[str]]:
    """返回 (records, error_msg)。records 为 None 表示失败。"""
    last_err: Optional[str] = None
    for i in range(retries + 1):
        try:
            raw = fetcher.info({"type": "clearinghouseState", "user": addr})
            ts_ms = int(time.time() * 1000)
            return parse_clearinghouse(addr, raw, ts_ms), None
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, json.JSONDecodeError) as e:
            last_err = f"{type(e).__name__}: {str(e)[:160]}"
            if i < retries:
                time.sleep(0.5 * (i + 1))
    return None, last_err


# ── 落盘 ─────────────────────────────────────────────────────────────────────
def _rec_path(rec_dir: Path, day: str) -> Path:
    return rec_dir / f"{day}.jsonl.gz"


def append_records(records: Iterable[dict], rec_dir: Path, day: str) -> int:
    """追加到 gzipped JSONL;原子写:打开、写、关闭。返回写入条数(0 也算正常)。"""
    if not records:
        return 0
    rec_dir.mkdir(parents=True, exist_ok=True)
    p = _rec_path(rec_dir, day)
    n = 0
    with gzip.open(p, "at", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")))
            f.write("\n")
            n += 1
    return n


# ── 一轮 ─────────────────────────────────────────────────────────────────────
def run_round(
    now: dt.datetime,
    fetcher: Optional[Fetcher] = None,
    cache: Optional[dict[str, Any]] = None,
    rec_dir: Path = DEFAULT_REC_DIR,
    address_file: Path = DEFAULT_ADDRESS_FILE,
    round_budget: int = DEFAULT_ROUND_BUDGET,
    top_n: int = DEFAULT_TOP_N,
    av_min_usd: float = DEFAULT_AV_MIN_USD,
    sleep_between: float = DEFAULT_INTER_REQUEST_SLEEP_S,
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """一轮:取名单 → 逐地址拉 → 解析 → 落盘;统计 ok/fail/empty。

    返回 stats(dict):
        - addresses(int) 名单大小
        - source(str) "leaderboard" / "file" / "empty" / "file_error" / "leaderboard_error"
        - queried(int) 本轮处理过的地址数(≤ addresses/2)
        - records(int) 写入条数
        - ok(int) 拉成功的地址数
        - empty(int) 拉成功但 0 仓位的地址数
        - failed(int) 拉失败的地址数
        - errors(list[str]) 失败原因截断,前 5 条
        - day(str) UTC 日期
    """
    fetcher = fetcher or Fetcher()
    cache = cache if cache is not None else {}
    today = utc_today(now)
    addrs, source = addresses_for_round(
        now, fetcher, cache,
        address_file=address_file, top_n=top_n, av_min_usd=av_min_usd,
    )
    if not addrs:
        log.warning("no addresses (source=%s); skipping round", source)
        return {"addresses": 0, "queried": 0, "ok": 0, "empty": 0, "failed": 0, "records": 0,
                "errors": [], "source": source, "day": today}

    budget = min(round_budget, len(addrs))
    errors: list[str] = []
    ok = empty = failed = 0
    all_records: list[dict] = []
    for i in range(budget):
        a = addrs[i]
        recs, err = fetch_one(a, fetcher)
        if err is None:
            ok += 1
            if not recs:
                empty += 1
            else:
                all_records.extend(recs)
        else:
            failed += 1
            if len(errors) < 5:
                errors.append(f"{a}: {err}")
        if sleep_between > 0 and i + 1 < budget:
            time.sleep(sleep_between)

    n_written = append_records(all_records, rec_dir, today)
    return {
        "addresses": len(addrs),
        "queried": budget,
        "ok": ok,
        "empty": empty,
        "failed": failed,
        "records": n_written,
        "errors": errors,
        "source": source,
        "day": today,
        "_ts_epoch": int(clock()),
    }


# ── 入口 ─────────────────────────────────────────────────────────────────────
def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="CometCloud 云主机鲸鱼持仓轮询(T-130,每 15 分钟)")
    ap.add_argument("--once", action="store_true", help="只跑一轮")
    ap.add_argument("--interval-s", type=int, default=15 * 60, help="循环间隔(秒)")
    ap.add_argument("--rec-dir", type=Path, default=DEFAULT_REC_DIR)
    ap.add_argument("--address-file", type=Path, default=DEFAULT_ADDRESS_FILE)
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    fetcher = Fetcher()
    cache: dict[str, Any] = {}
    if args.once:
        log.info("whales --once · rec_dir=%s", args.rec_dir)
        stats = run_round(utcnow(), fetcher, cache, rec_dir=args.rec_dir,
                          address_file=args.address_file)
        log.info("round stats: %s", json.dumps({k: v for k, v in stats.items() if k != "errors"}))
        return 0 if stats.get("failed", 0) == 0 or stats.get("ok", 0) > 0 else 1

    log.info("whales loop · every %ss", args.interval_s)
    while True:
        try:
            stats = run_round(utcnow(), fetcher, cache,
                              rec_dir=args.rec_dir, address_file=args.address_file)
            log.info("round stats: %s", json.dumps({k: v for k, v in stats.items() if k != "errors"}))
        except Exception as e:                                            # noqa: BLE001
            log.exception("round failed: %s", e)
        time.sleep(args.interval_s)


if __name__ == "__main__":
    raise SystemExit(main())