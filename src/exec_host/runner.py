"""东京云主机上的执行器进程(T-015 / TRADE_PATH §4–§5)。systemd 拉起:`python -m src.exec_host.runner`。

## 为什么它不在 Railway 上

HL API 钱包的私钥只放在这台主机的 `/etc/cometcloud/executor.env`(Jazz 亲手填,600 root),
不经过 Seth、不经过任何 lane、不进 Railway(TRADE_PATH §4)。Railway 有库、有信号;主机有钥匙、有盘口。
两边只通过两个口子说话(`/internal/executor/plan`、`/internal/executor/report`,EXECUTOR_TOKEN)。

## 它每 30 秒做的事

1. 发件箱 → Railway(落盘的 JSON;Railway 不在就留着,恢复后按顺序补写 —— TRADE_PATH §4)。
2. 计划:UTC 00:05 起每 5 分钟取一次,直到拿到「昨天收盘」的计划;之后每 15 分钟刷新一次(只为一键停)。
3. 每天一轮(asof 换了就跑):读**真实**余额与盘口 → 订单 → 意图先落发件箱(下单之前)→
   `live` 才下 IOC 限价单 → 每个意图一个结果。`dry_run` 到意图为止,不碰私钥。
4. 每 60 秒:盘中灾难止损(现价 < 计划里的止损线 ⇒ 全平)。**只用缓存的计划,不需要 Railway 在线。**
5. 每小时一次心跳(`loop_attempt` 里 `executor_host`)。

## 两个停

- `/var/lib/cometcloud/HALT` 存在 ⇒ 不下任何单(主机上 `touch` 即生效);
- Railway 一键停(`POST /internal/executor/halt`,Jazz 的 INTERNAL_TOKEN)⇒ 下一次取计划时生效(≤ 15 分钟)。
停着时照样算、照样记意图,只是不提交 —— 停的时候也要知道「本来会做什么」。

## 只调用一种写操作

本包对交易所只调用 `order`(IOC 限价)。不划转、不提币、不改杠杆 —— `tests/test_exec_host.py` 按 AST 守着这一条。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import socket
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from src.data.execution.fill_log import BUY, SELL
from src.exec_host import core

log = logging.getLogger("exec_host")
DEFAULT_API = "https://web-production-0cdf76.up.railway.app"
LOOP_S = 30
STOP_EVERY_S = 60
HEARTBEAT_EVERY_S = 3600
PLAN_WAIT_EVERY_S = 300
PLAN_REFRESH_EVERY_S = 900
PLAN_FROM_UTC = (0, 5)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def asof_for(now: dt.datetime) -> str:
    return (now.astimezone(dt.timezone.utc).date() - dt.timedelta(days=1)).isoformat()


class Config:
    def __init__(self, env: Optional[dict] = None):
        env = dict(os.environ if env is None else env)
        self.mode = env.get("EXECUTOR_MODE", "dry_run").strip()
        if self.mode not in ("dry_run", "live"):
            raise SystemExit(f"EXECUTOR_MODE 必须是 dry_run 或 live,收到 {self.mode!r}")
        self.account = env.get("HL_ACCOUNT_ADDRESS", "").strip()
        if not (self.account.startswith("0x") and len(self.account) == 42):
            raise SystemExit("HL_ACCOUNT_ADDRESS 必须是主钱包地址(0x + 40 位)")
        self.token = env.get("EXECUTOR_TOKEN", "").strip()
        if not self.token:
            raise SystemExit("EXECUTOR_TOKEN 未设置")
        self.api = env.get("EXECUTOR_API_BASE", DEFAULT_API).strip().rstrip("/")
        self.nav_cap = float(env.get("EXECUTOR_MAX_NAV_USD", "3000"))
        self.slip_bps = float(env.get("EXECUTOR_MAX_SLIP_BPS", "50"))
        self.stop_slip_bps = float(env.get("EXECUTOR_STOP_SLIP_BPS", "150"))
        self.state_dir = Path(env.get("EXECUTOR_STATE_DIR", "/var/lib/cometcloud"))
        self.host = env.get("EXECUTOR_HOST_NAME") or socket.gethostname()
        # 私钥不进 Config:只在 live 模式建交易客户端的那一刻从环境变量里读一次(Venue.exchange)

    @property
    def halt_file(self) -> Path:
        return self.state_dir / "HALT"


# ── Railway ─────────────────────────────────────────────────────────────────
class Railway:
    def __init__(self, base: str, token: str, timeout: float = 20.0):
        self.base, self.token, self.timeout = base, token, timeout

    def _req(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body, default=str).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={
            "X-Executor-Token": self.token, "Content-Type": "application/json",
            "User-Agent": "cometcloud-exec-host/1"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            return e.code, e.read()[:800].decode(errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            return 0, f"{type(e).__name__}: {e}"

    def plan(self) -> tuple[int, Any]:
        return self._req("GET", "/internal/executor/plan")

    def report(self, payload: dict) -> tuple[int, Any]:
        return self._req("POST", "/internal/executor/report", payload)


# ── 落盘:发件箱与状态 ──────────────────────────────────────────────────────
class Outbox:
    """Railway 不在时本地缓存、恢复后按顺序补写。422(校验拒绝)挪进 rejected/ 留证,不无限重发;
    其他失败(网络、5xx、403/404 —— 配置或部署问题)原地等,下一轮再试。"""

    def __init__(self, d: Path):
        self.d = d
        (d / "rejected").mkdir(parents=True, exist_ok=True)

    def put(self, payload: dict) -> Path:
        p = self.d / f"{time.time_ns()}-{payload.get('kind', 'x')}.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, default=str, ensure_ascii=False))
        os.replace(tmp, p)
        return p

    def pending(self) -> list[Path]:
        return sorted(self.d.glob("*.json"))

    def flush(self, railway: Railway) -> dict[str, int]:
        sent = rejected = 0
        for p in self.pending():
            code, resp = railway.report(json.loads(p.read_text()))
            if 200 <= code < 300:
                p.unlink()
                sent += 1
            elif code == 422:
                os.replace(p, self.d / "rejected" / p.name)
                rejected += 1
                log.error("report rejected (kept in rejected/): %s", str(resp)[:400])
            else:
                log.warning("report not delivered (%s), will retry: %s", code, str(resp)[:200])
                break
        return {"sent": sent, "rejected": rejected, "pending": len(self.pending())}


class State:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, Any] = {}
        if path.exists():
            try:
                self.data = json.loads(path.read_text())
            except ValueError:
                log.error("state file unreadable, starting empty: %s", path)

    def get(self, k: str, default: Any = None) -> Any:
        return self.data.get(k, default)

    def set(self, **kw: Any) -> None:
        self.data.update(kw)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, default=str, ensure_ascii=False))
        os.replace(tmp, self.path)


# ── Hyperliquid ─────────────────────────────────────────────────────────────
class Venue:
    """读:主账户余额(公开地址)、盘口、中间价、成交。写:只有 `order`,且只在 live 模式。"""

    def __init__(self, cfg: Config, info: Any = None, exchange: Any = None):
        self.cfg = cfg
        if info is None:
            from hyperliquid.info import Info
            from hyperliquid.utils import constants
            info = Info(constants.MAINNET_API_URL, skip_ws=True)
        self.info = info
        self._exchange = exchange

    def _poster(self, payload: dict, timeout: Any = None) -> Any:
        return self.info.post("/info", payload)

    def balances(self) -> dict:
        return core.parse_balances(self.info.spot_user_state(self.cfg.account))

    def quotes(self) -> dict:
        from src.data.execution.dry_run import _spot_quotes_sync
        from src.data.venues.hl_spot import HlSpotClient
        return _spot_quotes_sync(HlSpotClient(poster=self._poster))

    def mids(self, pairs: dict[str, str]) -> dict[str, float]:
        allm = self.info.all_mids() or {}
        return {s: float(allm[p]) for s, p in pairs.items() if p in allm}

    def fills_since(self, t_ms: int) -> list[dict]:
        return self.info.user_fills_by_time(self.cfg.account, t_ms) or []

    def exchange(self) -> Any:
        if self.cfg.mode != "live":
            raise RuntimeError("dry_run 不建交易客户端,也不读私钥")
        if self._exchange is None:
            from eth_account import Account
            from hyperliquid.exchange import Exchange
            from hyperliquid.utils import constants
            wallet = Account.from_key(os.environ["HL_API_WALLET_PRIVATE_KEY"])
            self._exchange = Exchange(wallet, constants.MAINNET_API_URL, account_address=self.cfg.account)
        return self._exchange

    def order(self, pair: str, side: str, qty: float, limit_px: float, cloid: str) -> Any:
        from hyperliquid.utils.types import Cloid
        return self.exchange().order(pair, side == BUY, qty, limit_px, {"limit": {"tif": "Ioc"}}, cloid=Cloid(cloid))


# ── 执行器 ──────────────────────────────────────────────────────────────────
class Executor:
    def __init__(self, cfg: Config, venue: Venue, railway: Railway, clock=utcnow):
        self.cfg, self.venue, self.railway, self.clock = cfg, venue, railway, clock
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        self.state = State(cfg.state_dir / "state.json")
        self.outbox = Outbox(cfg.state_dir / "outbox")
        self._last: dict[str, float] = {}
        self.settle_s = 1.0          # 下单后等成交记录落到 userFills 再取手续费

    # 停
    def halted(self) -> tuple[bool, str]:
        if self.cfg.halt_file.exists():
            return True, f"本地 {self.cfg.halt_file}"
        if self.state.get("railway_halted"):
            return True, "Railway 一键停"
        return False, ""

    def _report(self, kind: str, **kw: Any) -> None:
        self.outbox.put({"mode": self.cfg.mode, "kind": kind, "host": self.cfg.host, **kw})

    # 计划
    def refresh_plan(self, now: dt.datetime) -> None:
        plan = self.state.get("plan") or {}
        want = asof_for(now)
        have_today = plan.get("asof") == want
        after_open = (now.hour, now.minute) >= PLAN_FROM_UTC
        every = PLAN_REFRESH_EVERY_S if (have_today or not after_open) and plan else PLAN_WAIT_EVERY_S
        if time.time() - self._last.get("plan", 0) < every:
            return
        self._last["plan"] = time.time()
        code, resp = self.railway.plan()
        if code != 200 or not isinstance(resp, dict):
            log.warning("plan fetch failed (%s): %s", code, str(resp)[:200])
            return
        if resp.get("halt_status") in ("hit", "miss"):
            if bool(resp.get("halted")) != bool(self.state.get("railway_halted")):
                log.warning("Railway halt flag → %s", resp.get("halted"))
            self.state.set(railway_halted=bool(resp.get("halted")))
        if resp.get("ok"):
            self.state.set(plan=resp, plan_fetched_at=now.isoformat())
        else:
            log.info("plan not ready: %s", resp.get("why"))

    # 每日一轮
    def run_cycle(self, now: dt.datetime) -> dict[str, Any]:
        plan = self.state.get("plan") or {}
        halted, why_halt = self.halted()
        balances, quotes = self.venue.balances(), self.venue.quotes()
        self.state.set(pairs={s: {"pair": q["pair"], "sz_decimals": int(q["sz_decimals"])} for s, q in quotes.items()})
        # 停着也照样算出订单(halted=False),只是不提交 —— 停的时候也要知道「本来会做什么」
        res = core.plan_host_orders(plan, balances, quotes, now.timestamp(), self.cfg.nav_cap, halted=False)
        sleeve = plan["sleeves"][self.cfg.mode]
        staged = []
        for o in res["orders"]:
            q = quotes[o["symbol"]]
            lim = core.ioc_limit_px(q["mid"], o["side"], self.cfg.slip_bps, int(q["sz_decimals"]))
            staged.append((core.make_intent(o, sleeve, plan["signal_ref"], now, lim), o, q))
        mins = core.minutes_after_close(now)
        detail = {"phase": "intents", "minutes_after_close": round(mins, 1), "on_time": mins <= 60,
                  "targets": res["targets"], "holdings_usd": _r(res["holdings_usd"]), "dust_usd": _r(res["dust_usd"]),
                  "cash_usd": round(res["cash_usd"], 2), "nav_raw": round(res["nav_raw"], 2),
                  "nav_book": round(res["nav_book"], 2), "nav_cap": self.cfg.nav_cap,
                  "orders": [{k: o.get(k) for k in ("symbol", "side", "qty_base", "notional_rounded",
                                                    "est_slippage_bps", "truncated")} | {"limit_px": i.limit_price}
                             for i, o, _ in staged],
                  "refused": res["refused"], "halted": halted, "halt_why": why_halt}
        orders_txt = "; ".join(f"{i.symbol} {i.side} {o['qty_base']} (~${o['notional_rounded']}) 限价 {i.limit_price}"
                               for i, o, _ in staged)
        alert = None
        if staged:
            alert = (f"{plan['asof']} 收盘信号 · {self.cfg.mode}{' · 已停,不提交' if halted else ''}: {orders_txt}")
        # 意图先落盘,在任何订单存在之前(fill_log:决策时刻记录,没成交也要能对上)
        self._report("cycle", asof=plan["asof"], intents=[asdict(i) for i, _, _ in staged], detail=detail,
                     alert=alert if (self.cfg.mode == "dry_run" or halted) else None)
        outcomes = []
        if self.cfg.mode == "live" and staged and halted:
            outcomes = self._not_submitted(staged, f"一键停({why_halt}):未提交")
            self._report("cycle", asof=plan["asof"], outcomes=[asdict(x) for x in outcomes],
                         detail={"phase": "outcomes", "statuses": [x.status for x in outcomes]})
        elif self.cfg.mode == "live" and staged:
            outcomes = self._execute(staged, self.cfg.slip_bps)
            self._report("cycle", asof=plan["asof"], outcomes=[asdict(x) for x in outcomes],
                         detail={"phase": "outcomes", "statuses": [x.status for x in outcomes]},
                         alert=f"{plan['asof']} 真单: " + "; ".join(
                             f"{i.symbol} {i.side} → {x.status} {x.avg_fill_price or ''} ({x.note[:60]})"
                             for (i, _, _), x in zip(staged, outcomes)))
        self.state.set(done_asof=plan["asof"], last_cycle_at=now.isoformat())
        return {**detail, "intents": [asdict(i) for i, _, _ in staged], "outcomes": [asdict(x) for x in outcomes]}

    def _not_submitted(self, staged: list, why: str) -> list:
        """live 但停着:意图已记,结果 = cancelled(写明原因)—— 真跑 sleeve 里不留没有结果的意图。"""
        now = self.clock()
        return [core.Outcome(intent_id=i.intent_id, ts_resolved=now.isoformat(), status=core.CANCELLED, note=why)
                for i, _, _ in staged]

    def _execute(self, staged: list, slip_bps: float) -> list:
        """按序下 IOC(计划里卖单在前)。买单下单前重读 USDC,数量不超过可用余额。每个意图恰好一个结果。"""
        t0_ms = int(time.time() * 1000) - 2000
        sent = []
        for intent, o, q in staged:
            qty = o["qty_base"]
            if intent.side == BUY:
                qty = core.cap_buy_qty(qty, core.free(self.venue.balances(), "USDC"), intent.limit_price,
                                       int(q["sz_decimals"]))
            t_sent = time.time()
            if qty <= 0 or qty * intent.limit_price < 10.0:
                parsed = {"kind": "error", "error": f"按可用余额截断后 {qty} 低于最小名义额,未提交"}
            else:
                try:
                    parsed = core.parse_order_response(
                        self.venue.order(q["pair"], intent.side, qty, intent.limit_price, core.cloid_for(intent.intent_id)))
                except Exception as e:                                   # noqa: BLE001
                    parsed = {"kind": "error", "error": f"{type(e).__name__}: {str(e)[:200]}"}
            sent.append((intent, qty, parsed, t_sent, time.time()))
        time.sleep(self.settle_s)
        try:
            fills = self.venue.fills_since(t0_ms)
        except Exception as e:                                           # noqa: BLE001
            log.warning("fills fetch failed: %s", e)
            fills = []
        pairs = {s: p["pair"] for s, p in (self.state.get("pairs") or {}).items()}
        try:
            mids = self.venue.mids(pairs)
        except Exception:                                                # noqa: BLE001
            mids = {}
        now = self.clock()
        return [core.outcome_for(i, qty, parsed, fills, mids.get(i.symbol), ts, td, now)
                for i, qty, parsed, ts, td in sent]

    # 盘中灾难止损
    def check_stops(self, now: dt.datetime) -> list[str]:
        plan = self.state.get("plan") or {}
        pairs = self.state.get("pairs") or {}
        if not plan.get("stop_px") or not pairs:
            return []
        today = now.date().isoformat()
        stopped = (self.state.get("stopped") or {}).get(today, [])
        balances = self.venue.balances()
        mids = self.venue.mids({s: p["pair"] for s, p in pairs.items()})
        min_notional = float((plan.get("limits") or {}).get("min_notional_usd", 10.0))
        hits = core.stop_hits(plan["stop_px"], balances, mids, min_notional, stopped)
        if not hits:
            return []
        halted, why_halt = self.halted()
        sleeve = plan["sleeves"][self.cfg.mode]
        staged = []
        for sym in hits:
            p = pairs[sym]
            qty = core.round_size(core.free(balances, core.SPOT_TOKENS[sym]), p["sz_decimals"])
            lim = core.ioc_limit_px(mids[sym], SELL, self.cfg.stop_slip_bps, p["sz_decimals"])
            o = {"symbol": sym, "side": SELL, "qty_base": qty, "price": mids[sym], "bid": None, "ask": None}
            staged.append((core.make_intent(o, sleeve, plan["signal_ref"] + " · catastrophe", now, lim), o,
                           {"pair": p["pair"], "sz_decimals": p["sz_decimals"]}))
        lines = "; ".join(f"{s} 现价 {mids[s]} < 止损线 {plan['stop_px'][s]:.2f}" for s in hits)
        self._report("stop", asof=plan.get("asof"), intents=[asdict(i) for i, _, _ in staged],
                     detail={"hits": hits, "mids": {s: mids[s] for s in hits}, "halted": halted},
                     alert=f"灾难止损 · {self.cfg.mode}{' · 已停,不提交 (' + why_halt + ')' if halted else ''}: {lines}")
        if self.cfg.mode == "live":
            outs = (self._not_submitted(staged, f"一键停({why_halt}):未提交") if halted
                    else self._execute(staged, self.cfg.stop_slip_bps))
            self._report("stop", asof=plan.get("asof"), outcomes=[asdict(x) for x in outs],
                         detail={"phase": "outcomes", "statuses": [x.status for x in outs]},
                         alert="灾难止损结果: " + "; ".join(f"{i.symbol} → {x.status}" for (i, _, _), x in zip(staged, outs)))
        # 只留今天:每个币每天最多止一次(止完当天不再追;第二天收盘规则重新定目标)
        self.state.set(stopped={today: stopped + hits})
        return hits

    def heartbeat(self, now: dt.datetime) -> None:
        try:
            b = self.venue.balances()
            bal = {k: round(v["total"], 8) for k, v in b.items() if v.get("total")}
        except Exception as e:                                           # noqa: BLE001
            bal = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
        halted, why = self.halted()
        plan = self.state.get("plan") or {}
        self._report("heartbeat", asof=plan.get("asof"), detail={
            "balances": bal, "plan_asof": plan.get("asof"), "done_asof": self.state.get("done_asof"),
            "stop_px": plan.get("stop_px"), "halted": halted, "halt_why": why,
            "outbox_pending": len(self.outbox.pending()), "at": now.isoformat()})

    def tick(self) -> None:
        now = self.clock()
        for name, fn in (("flush", lambda: self.outbox.flush(self.railway)),
                         ("plan", lambda: self.refresh_plan(now)),
                         ("cycle", lambda: self._maybe_cycle(now)),
                         ("stop", lambda: self._every("stop", STOP_EVERY_S, lambda: self.check_stops(now))),
                         ("heartbeat", lambda: self._every("heartbeat", HEARTBEAT_EVERY_S, lambda: self.heartbeat(now)))):
            try:
                fn()
            except Exception as e:                                       # noqa: BLE001
                log.exception("step %s failed", name)
                self._every(f"err:{name}", 3600, lambda: self._report(
                    "error", detail={"step": name, "errors": [f"{type(e).__name__}: {str(e)[:300]}"]},
                    alert=f"执行器 {name} 出错: {type(e).__name__}: {str(e)[:200]}"))

    def _maybe_cycle(self, now: dt.datetime) -> None:
        plan = self.state.get("plan") or {}
        if plan.get("ok") and plan.get("asof") == asof_for(now) and self.state.get("done_asof") != plan["asof"]:
            r = self.run_cycle(now)
            log.info("cycle %s: %d orders, refused=%s", plan["asof"], len(r["orders"]), r["refused"])

    def _every(self, key: str, every_s: float, fn) -> None:
        if time.time() - self._last.get(key, 0) >= every_s:
            self._last[key] = time.time()
            fn()


def _r(d: dict) -> dict:
    return {k: round(v, 2) for k, v in d.items()}


def check(ex: Executor) -> dict[str, Any]:
    """部署后跑一次:配置、计划、余额、按真实余额算出的订单 —— 不下单。最后发一条心跳,验证回报这条路是通的。"""
    out: dict[str, Any] = {"mode": ex.cfg.mode, "account": ex.cfg.account, "api": ex.cfg.api,
                           "nav_cap": ex.cfg.nav_cap, "halted": ex.halted()}
    code, plan = ex.railway.plan()
    out["plan_http"] = code
    out["plan"] = {k: plan.get(k) for k in ("ok", "asof", "targets", "stop_px", "halted", "halt_status", "why")} \
        if isinstance(plan, dict) else str(plan)[:300]
    b = ex.venue.balances()
    out["balances"] = {k: v["total"] for k, v in b.items() if v.get("total")}
    if isinstance(plan, dict) and plan.get("ok"):
        q = ex.venue.quotes()
        r = core.plan_host_orders(plan, b, q, time.time(), ex.cfg.nav_cap, halted=False)
        out["would_trade"] = [{k: o.get(k) for k in ("symbol", "side", "qty_base", "notional_rounded")} for o in r["orders"]]
        out["refused"] = r["refused"]
        out["nav_book"] = round(r["nav_book"], 2)
    ex.heartbeat(utcnow())
    out["report"] = ex.outbox.flush(ex.railway)
    return out


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description="CometCloud 云主机执行器")
    ap.add_argument("--check", action="store_true", help="自检一次(不下单)并发一条心跳,然后退出")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config()
    ex = Executor(cfg, Venue(cfg), Railway(cfg.api, cfg.token))
    if args.check:
        print(json.dumps(check(ex), ensure_ascii=False, indent=2, default=str))
        return
    log.info("executor up · mode=%s · account=%s · api=%s · nav_cap=%s", cfg.mode, cfg.account, cfg.api, cfg.nav_cap)
    ex._report("heartbeat", detail={"event": "start", "mode": cfg.mode, "nav_cap": cfg.nav_cap},
               alert=f"执行器启动 · {cfg.mode} · {cfg.host}")
    while True:
        ex.tick()
        time.sleep(LOOP_S)


if __name__ == "__main__":
    main()
