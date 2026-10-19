"""东京主机上录 HL 盘口与成交(T-129)。

只录,不下单 —— 私钥路径(`runner.py` / `core.py` / `install.sh`)完全不碰。
断网不丢:重连连上后补发当天的下一个 10 秒一档与未发的成交;磁盘 < 5 GB 停写并报。
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

log = logging.getLogger("exec_host.recorder")

DEFAULT_WS_URL = "wss://api.hyperliquid.xyz/ws"
DEFAULT_INFO_URL = "https://api.hyperliquid.xyz/info"
DEFAULT_COINS = ("BTC", "ETH", "SOL", "HYPE")
DEFAULT_L2_THROTTLE_S = 10.0
L2_DEPTH = 20
DISK_FREE_MIN_GB = 5.0
# 退避上限 30s —— 比 HL 的 1.0× reconnect 友好得多,失误是带宽而不是断流。
BACKOFF_CAP_S = 30.0
BACKOFF_START_S = 1.0
#: 合并方(10-19):HL 会断开一段时间没收到客户端消息的连接 —— 每 30 秒发一次 {"method": "ping"};
#: 30 个币的盘口 30 秒一条都没有 ⇒ 当作连接已死,重连。
WS_PING_EVERY_S = 30.0
WS_RECV_TIMEOUT_S = 30.0


# ── 时钟与时间工具(注入让测试用假时间) ──────────────────────────────────────
def utc_now_ms(clock: Callable[[], float]) -> int:
    """Monotonic / wall 时钟毫秒时间戳。测试注入 `clock` 给一个假时间。"""
    return int(clock() * 1000)


def utc_day_str(now: dt.datetime) -> str:
    return now.strftime("%Y-%m-%d")


# ── 文件 IO ──────────────────────────────────────────────────────────────────
class GzJsonlWriter:
    """按 UTC 日滚动的 gzip jsonl 写入器。

    同一日追加到同一个文件,跨日切换时先把当前句柄关闭再开新文件 —— 没有跨日的拼接噩梦,
    也没有「先 close 再 open」的中间窗掉消息。
    """

    def __init__(self, base_dir: Path, day: str, kind: str, ext: str = ".jsonl.gz"):
        self.base_dir = Path(base_dir)
        self.day = day
        self.kind = kind  # "l2" or "trades"
        self.ext = ext
        self._fh: Optional[gzip.GzipFile] = None
        self._path: Optional[Path] = None
        self.written = 0

    @property
    def path(self) -> Path:
        return self.base_dir / self.day / f"{self.kind}{self.ext}"

    def _ensure_dir(self) -> None:
        d = self.base_dir / self.day
        d.mkdir(parents=True, exist_ok=True)

    def open(self) -> None:
        if self._fh is not None:
            return
        self._ensure_dir()
        self._path = self.path
        self._fh = gzip.open(self._path, "ab")  # append

    def rollover(self, day: str) -> bool:
        """跨日关闭旧句柄;同日 no-op。返回是否真的切换了文件。"""
        if day == self.day:
            return False
        self.close()
        self.day = day
        return True

    def write(self, line: dict[str, Any]) -> bool:
        """返回是否真的写入(磁盘满时不写)。"""
        if self._fh is None:
            self.open()
        assert self._fh is not None
        data = (json.dumps(line, separators=(",", ":")) + "\n").encode("utf-8")
        self._fh.write(data)
        self.written += 1
        return True

    def flush(self) -> None:
        if self._fh is not None:
            self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.flush()
                self._fh.close()
            finally:
                self._fh = None


# ── 磁盘护栏(可注入让测试用假磁盘) ───────────────────────────────────────────
def _check_disk_free(base_dir: Path, host: Any = None) -> float:
    """返回 base_dir 所在文件系统的剩余 GB。host 可注入假 statvfs。"""
    get_free = getattr(host, "free_gb", None)
    if callable(get_free):
        return float(get_free(base_dir))
    # base_dir 还没创建 —— 第一次写前先 mkdir,disk_usage 也别炸。
    try:
        return shutil.disk_usage(base_dir).free / (1024 ** 3)
    except FileNotFoundError:
        try:
            base_dir.mkdir(parents=True, exist_ok=True)
            return shutil.disk_usage(base_dir).free / (1024 ** 3)
        except OSError:
            # 真没盘 —— 让上层走 disk-halt,不在这抛
            return float("inf")


# ── 名单:env 默认 + 每日按 metaAndAssetCtxs 24h 成交补到前 30 ────────────────
def parse_meta_and_asset_ctxs(raw: Any) -> list[tuple[str, float]]:
    """HL `metaAndAssetCtxs` → [(coin, day_ntl_vlm), ...] 仅永续(descartes 前)。"""
    if not isinstance(raw, list) or len(raw) < 2:
        return []
    universe, ctxs = raw[0], raw[1]
    coins = []
    if isinstance(universe, dict):
        coins = [u.get("name") for u in (universe.get("universe") or [])]
    else:
        coins = [u.get("name") for u in (universe or [])]
    out = []
    for i, ctx in enumerate(ctxs or []):
        if i >= len(coins):
            break
        c = coins[i]
        if not c:
            continue
        if not isinstance(ctx, dict):
            continue
        v = ctx.get("dayNtlVlm") or ctx.get("dayNotionalVolume")
        try:
            v_f = float(v)
        except (TypeError, ValueError):
            continue
        out.append((c, v_f))
    out.sort(key=lambda x: x[1], reverse=True)
    return out


def coin_roster(defaults: Iterable[str], meta: list[tuple[str, float]], top_n: int = 30) -> list[str]:
    """env 默认的币 + 按 24h 成交额补足到 top_n;env 列在前的优先,重复去重。"""
    seen: set[str] = set()
    out: list[str] = []
    for c in defaults:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    for c, _ in meta:
        if len(out) >= top_n:
            break
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


# ── 抽象层:WS + HTTP,测试里换成假实现 ────────────────────────────────────────
class WsApp:
    """Hyperliquid websocket 客户端的最小接口。

    生产实现由调用方注入 `hyperliquid.info(...).ws_app(...)` 或 `websocket._app`;
    测试用 `FakeWs` 喂假消息。
    """

    def send(self, payload: dict[str, Any]) -> None: ...
    def recv(self) -> str: ...   # 收到一条 JSON 文本
    def close(self) -> None: ...


class HttpPoster:
    """metaAndAssetCtxs 拉取(同 info HTTP,不是 ws)。"""
    def post(self, payload: dict[str, Any]) -> Any: ...


# ── 解析 HL ws 流 ────────────────────────────────────────────────────────────
def parse_l2(raw: dict[str, Any]) -> Optional[dict[str, Any]]:
    """`{channel: 'l2Book', data: {coin, levels, time}}` → 20 档 / 20 档 + ts。

    HL 的 `levels` 是 [bids[], asks[]],每个 `[px: str, sz: str, n: int]`。
    """
    if not isinstance(raw, dict) or raw.get("channel") != "l2Book":
        return None
    data = raw.get("data") or {}
    coin = data.get("coin")
    levels = data.get("levels") or []
    if len(levels) < 2 or not coin:
        return None
    bids_raw, asks_raw = levels[0][:L2_DEPTH], levels[1][:L2_DEPTH]
    return {
        "coin": str(coin),
        "time_ms": int(data.get("time") or 0),
        "bids": [[_f(x[0]), _f(x[1]), int(x[2] or 0)] for x in bids_raw if len(x) >= 2],
        "asks": [[_f(x[0]), _f(x[1]), int(x[2] or 0)] for x in asks_raw if len(x) >= 2],
    }


def parse_trade(raw: dict[str, Any]) -> Optional[dict[str, Any]]:
    """`{channel: 'trades', data: [trades...]}` → 单笔成交扁平化。"""
    if not isinstance(raw, dict) or raw.get("channel") != "trades":
        return None
    rows = raw.get("data") or []
    out = []
    for t in rows:
        if not isinstance(t, dict):
            continue
        out.append({
            "coin": str(t.get("coin", "")),
            "side": str(t.get("side", "")),
            "px": _f(t.get("px")),
            "sz": _f(t.get("sz")),
            "time_ms": int(t.get("time") or 0),
            "tid": int(t.get("tid") or t.get("hash") or 0),
        })
    return {"trades": out} if out else None


def _f(x: Any) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ── 重连退避 ────────────────────────────────────────────────────────────────
class Backoff:
    """指数退避,上限 BACKOFF_CAP_S;每收到一条消息或写入成功调用 `note_ok()` 重置。"""

    def __init__(self, start: float = BACKOFF_START_S, cap: float = BACKOFF_CAP_S):
        self.start = start
        self.cap = cap
        self._last = 0.0
        self._n = 0

    def next_delay(self) -> float:
        if self._n == 0:
            self._last = self.start
        else:
            self._last = min(self.cap, self.start * (2 ** (self._n - 1)))
        self._n += 1
        return self._last

    def note_ok(self) -> None:
        self._n = 0
        self._last = 0.0


# ── 核心 Recorder ───────────────────────────────────────────────────────────
class Recorder:
    """盘口 + 成交录写器。

    `coins` 是监控的币列表;有变更时(每日刷新名单) 用 `set_coins` 增量订/退订。
    `base_dir` 是当日 gzip 落盘的根。每天 UTC 00:00 滚动到下一个日期目录。
    """

    def __init__(
        self,
        *,
        base_dir: Path,
        coins: list[str],
        ws: WsApp,
        poster: HttpPoster,
        clock: Callable[[], float] = time.monotonic,
        wallclock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.timezone.utc),
        host: Any = None,
        throttle_s: float = DEFAULT_L2_THROTTLE_S,
        disk_min_gb: float = DISK_FREE_MIN_GB,
    ):
        self.base_dir = Path(base_dir)
        self.coins = list(coins)
        self.ws = ws
        self.poster = poster
        self.clock = clock
        self.wallclock = wallclock
        self.host = host
        self.throttle_s = float(throttle_s)
        self.disk_min_gb = float(disk_min_gb)
        self.backoff = Backoff()
        # last_keep_ts[coin] = ms —— l2Book 节流
        self.last_keep_ts: dict[str, int] = {}
        self.day_str: str = utc_day_str(self.wallclock())
        self._writers: dict[str, dict[str, GzJsonlWriter]] = {}  # coin → {"l2": w, "trades": w}
        self.disk_halted = False

    # ── 公开:订阅 ──────────────────────────────────────────────────────────
    def subscribe_all(self) -> None:
        for c in self.coins:
            self.ws.send({"method": "subscribe", "subscription": {"type": "l2Book", "coin": c}})
            self.ws.send({"method": "subscribe", "subscription": {"type": "trades", "coin": c}})

    def set_coins(self, new_coins: list[str]) -> None:
        keep = self.coins
        nxt = [c for c in new_coins if c]
        added = [c for c in nxt if c not in keep]
        removed = [c for c in keep if c not in nxt]
        for c in removed:
            self.ws.send({"method": "unsubscribe", "subscription": {"type": "l2Book", "coin": c}})
            self.ws.send({"method": "unsubscribe", "subscription": {"type": "trades", "coin": c}})
            self._close_writer(c)
        for c in added:
            self.ws.send({"method": "subscribe", "subscription": {"type": "l2Book", "coin": c}})
            self.ws.send({"method": "subscribe", "subscription": {"type": "trades", "coin": c}})
        self.coins = nxt

    def refresh_roster(self) -> list[str]:
        """每天拉一次 metaAndAssetCtxs 把默认名单补到前 30。"""
        try:
            raw = self.poster.post({"type": "metaAndAssetCtxs"})
        except Exception as e:
            log.warning("[recorder] metaAndAssetCtxs fetch failed: %s", e)
            return self.coins
        meta = parse_meta_and_asset_ctxs(raw)
        new_roster = coin_roster(DEFAULT_COINS, meta, top_n=30)
        if new_roster != self.coins:
            self.set_coins(new_roster)
        return self.coins

    # ── 公开:处理一条 ws 消息 ─────────────────────────────────────────────
    def handle(self, msg: dict[str, Any]) -> bool:
        """返回 True 表示这条消息有被处理(成功 / 命中磁盘护栏);False 表示无记录价值。"""
        ch = msg.get("channel")
        # disk guard 提前查 —— 不然会写半个文件
        if self.disk_halted:
            return False
        free_gb = _check_disk_free(self.base_dir, self.host)
        if free_gb < self.disk_min_gb:
            log.error("[recorder] disk free %.2fGB < %.2fGB — halting writes", free_gb, self.disk_min_gb)
            self.disk_halted = True
            return False
        if ch == "l2Book":
            return self._handle_l2(msg)
        if ch == "trades":
            return self._handle_trades(msg)
        if ch in ("subscriptionResponse", "pong", "ack"):
            return False
        return False

    # ── 内部 ─────────────────────────────────────────────────────────────
    def _maybe_rollover(self) -> None:
        """跨 UTC 日时把 writer 全部切换到新目录。"""
        new_day = utc_day_str(self.wallclock())
        if new_day == self.day_str:
            return
        old = self.day_str
        for per_coin in self._writers.values():
            for w in per_coin.values():
                w.rollover(new_day)
        self.day_str = new_day
        log.info("[recorder] rolled over from %s to %s", old, new_day)

    def _writer_for(self, coin: str, kind: str) -> GzJsonlWriter:
        per_coin = self._writers.setdefault(coin, {})
        # kind 形如 "l2" / "trades";文件名按 acceptance 写 "<coin>.<kind>.jsonl.gz"
        fname = f"{coin}.{kind}" if not kind.startswith(f"{coin}.") else kind
        w = per_coin.get(kind)
        if w is None or w.day != self.day_str:
            if w is not None:
                w.close()
            w = GzJsonlWriter(self.base_dir, self.day_str, fname)
            per_coin[kind] = w
        return w

    def _close_writer(self, coin: str) -> None:
        per_coin = self._writers.pop(coin, None)
        if per_coin:
            for w in per_coin.values():
                w.close()

    def _handle_l2(self, msg: dict[str, Any]) -> bool:
        parsed = parse_l2(msg)
        if not parsed:
            return False
        self._maybe_rollover()
        coin = parsed["coin"]
        ts = parsed["time_ms"]
        last = self.last_keep_ts.get(coin)
        # 节流:同币 10s 以内只留最近一张
        if last is not None and (ts - last) < int(self.throttle_s * 1000) and ts != 0:
            return False
        if ts > 0:
            self.last_keep_ts[coin] = ts
        w = self._writer_for(coin, "l2")
        line = {
            "kind": "l2",
            "ts_local_ms": utc_now_ms(self.clock),
            **parsed,
        }
        ok = w.write(line)
        if ok:
            self.backoff.note_ok()
            w.flush()
        return ok

    def _handle_trades(self, msg: dict[str, Any]) -> bool:
        parsed = parse_trade(msg)
        if not parsed:
            return False
        self._maybe_rollover()
        # trades 按 coin 分桶写(避免一个文件被多币写入、文件名带币是对的)
        # 这里简化:同一批多币成交按 coin 分别落盘
        written_any = False
        for t in parsed["trades"]:
            coin = t.get("coin") or ""
            if not coin:
                continue
            w = self._writer_for(coin, "trades")
            line = {
                "kind": "trade",
                "ts_local_ms": utc_now_ms(self.clock),
                **t,
            }
            if w.write(line):
                written_any = True
                w.flush()
        if written_any:
            self.backoff.note_ok()
        return written_any

    def rotate_day_if_needed(self) -> None:
        # 仅供测试用
        self._maybe_rollover()

    def close(self) -> None:
        for per_coin in self._writers.values():
            for w in per_coin.values():
                w.close()
        self._writers.clear()


# ── 入口:real ws 实现 + 编排 ───────────────────────────────────────────────
def _load_ws_app(url: str, headers: dict[str, str]) -> WsApp:
    """生产 ws 客户端(懒加载,让测试不必装 hyperliquid SDK)。"""
    import websocket  # hyperliquid SDK 自带;避免硬依赖,放进口时点
    # 合并方(10-19):recv 加超时 —— 连接静默死掉时 recv 会永远阻塞,超时抛错才会走重连。
    ws = websocket.create_connection(url, header=[f"{k}: {v}" for k, v in headers.items()], timeout=WS_RECV_TIMEOUT_S)
    return _StdWs(ws)


class _StdWs(WsApp):
    def __init__(self, raw: Any):
        self._raw = raw

    def send(self, payload: dict[str, Any]) -> None:
        self._raw.send(json.dumps(payload))

    def recv(self) -> str:
        return self._raw.recv()

    def close(self) -> None:
        try:
            self._raw.close()
        except Exception:
            pass


def _load_poster(url: str, timeout_s: float = 5.0) -> HttpPoster:
    import urllib.request
    return _UrllibPoster(url, timeout_s)


class _UrllibPoster(HttpPoster):
    def __init__(self, url: str, timeout_s: float):
        self._url = url
        self._t = timeout_s

    def post(self, payload: dict[str, Any]) -> Any:
        req = urllib.request.Request(
            self._url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self._t) as r:  # noqa: S310 — recorder-only network
            raw = r.read()
        try:
            return json.loads(raw)
        except ValueError:
            return None


# ── 解析 env ───────────────────────────────────────────────────────────────
def _coins_from_env(env_name: str = "RECORDER_COINS") -> list[str]:
    raw = os.environ.get(env_name, "")
    if not raw:
        return list(DEFAULT_COINS)
    out = [c.strip() for c in raw.split(",") if c.strip()]
    return out or list(DEFAULT_COINS)


def run(base_dir: str = "/var/lib/cometcloud/rec",
        ws_url: str = DEFAULT_WS_URL,
        info_url: str = DEFAULT_INFO_URL) -> None:  # pragma: no cover — production loop
    """生产入口:连接 ws、订阅、循环处理;由 systemd 拉起。"""
    import signal
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log.info("[recorder] starting; base_dir=%s ws=%s", base_dir, ws_url)
    coins = _coins_from_env()
    rec = Recorder(
        base_dir=Path(base_dir),
        coins=coins,
        ws=_load_ws_app(ws_url, {}),
        poster=_load_poster(info_url),
    )
    rec.subscribe_all()
    # 合并方(10-19):启动时就把名单补到前 30(原来要等 24 小时,第一天只录 4 个币)
    try:
        rec.refresh_roster()
    except Exception as e:
        log.warning("[recorder] initial roster refresh failed: %s", e)

    stopping = {"v": False}

    def _stop(*_a: Any) -> None:
        stopping["v"] = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    last_refresh = time.monotonic()
    last_ping = time.monotonic()
    refresh_every = 24 * 3600
    while not stopping["v"]:
        if time.monotonic() - last_ping > WS_PING_EVERY_S:
            try:
                rec.ws.send({"method": "ping"})
            except Exception as e:
                log.warning("[recorder] ping failed: %s", e)
            last_ping = time.monotonic()
        # 刷新名单:每天一次(用单调时钟,断电不影响)
        if time.monotonic() - last_refresh > refresh_every:
            try:
                rec.refresh_roster()
            except Exception as e:
                log.warning("[recorder] roster refresh failed: %s", e)
            last_refresh = time.monotonic()
        try:
            txt = rec.ws.recv()
        except Exception as e:
            delay = rec.backoff.next_delay()
            log.warning("[recorder] ws recv failed (%s); backoff %.1fs", e, delay)
            time.sleep(delay)
            try:
                rec.ws.close()
            except Exception:
                pass
            rec.ws = _load_ws_app(ws_url, {})
            rec.subscribe_all()
            continue
        try:
            rec.handle(json.loads(txt))
        except Exception as e:
            log.warning("[recorder] bad ws message (%s): %r", e, txt[:120])
            continue
    log.info("[recorder] shutting down")
    rec.close()


# 合并方(10-19):systemd 用 `python -m src.exec_host.recorder` 拉起 —— 没有这一段,进程导入完就退出、每 15 秒被重启一次。
if __name__ == "__main__":
    run(base_dir=os.environ.get("RECORDER_REC_DIR", "/var/lib/cometcloud/rec"))
