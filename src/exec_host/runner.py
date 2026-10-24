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

本包对交易所只调用 `order`(IOC 限价;R-v2 单票还有减仓止损触发单)和 `cancel`(出场前撤掉那张触发单)。
不划转、不提币、不改杠杆 —— `tests/test_exec_host.py` 按 AST 守着这一条。

## R-v2 单票(`EXECUTOR_TICKETS_MODE` = off / dry_run / live,与 X1V 的 `EXECUTOR_MODE` 各管各的)

计划里的 `tickets` 段(Railway `ticket_plan`)→ `tickets.ticket_actions` → HL 永续:IOC 进场、按成交价挂减仓止损触发单、
不在持有单里的票减仓出场。净值 = 永续账户净值,封顶 `EXECUTOR_TICKETS_MAX_EQUITY_USD`。
**USDC 要在永续账户里**(现货 → 永续的划转是 Jazz 在 HL 上手动做的,本包不划转)。

## 子账户(`HL_SUBACCOUNT_ADDRESS`,可选)

不设:整个主账户都是执行器的 —— 它把账上全部 UBTC / UETH、全部永续净值与仓位当成自己的。Jazz 同时在主账户上手动交易,
两边会把对方的仓位算进来(同一个币上,执行器会把 Jazz 平掉的仓位记成「交易所上已平」)。
设了:余额、仓位、成交都读子账户,下单带 vaultAddress = 子账户(主账户批准的 API 钱包可以替子账户签名,私钥不变)。
钱进子账户是 Jazz 在 HL 网页上划的,本包不划转。启动时子账户不在主账户名下 ⇒ 不启动。
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
import uuid
import urllib.request
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Optional

from src.data.execution.fill_log import BUY, CANCELLED, FILLED, PARTIAL, SELL
from src.exec_host import core, tickets, verify

log = logging.getLogger("exec_host")
DEFAULT_API = "https://web-production-0cdf76.up.railway.app"
LOOP_S = 30
STOP_EVERY_S = 60
HEARTBEAT_EVERY_S = 3600
PLAN_WAIT_EVERY_S = 300
PLAN_REFRESH_EVERY_S = 900
PLAN_FROM_UTC = (0, 5)
TRIGGER_RETRY_S = 900          # 止损触发单没挂上:每 15 分钟重挂一次(后备 IOC 每分钟都在看)
TRUTH_GIVE_UP_S = 86400        # 交易所上已平、成交一直找不到:24 小时后按「找不到」结案(Book of Truth)


def _ms(iso: Any) -> int:
    """ISO 时间 → 毫秒;缺 ⇒ 0(从头查)。"""
    try:
        return int(dt.datetime.fromisoformat(str(iso)).timestamp() * 1000)
    except (TypeError, ValueError):
        return 0


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
        if not _is_addr(self.account):
            raise SystemExit("HL_ACCOUNT_ADDRESS 必须是主钱包地址(0x + 40 位)")
        # 子账户(可选):设了 ⇒ 读余额 / 仓位 / 成交、下单(vaultAddress)全部在子账户上,主账户留给 Jazz 手动交易。
        # 没设 ⇒ 照旧整个主账户都当成执行器的(两边同时用会互相把对方的仓位算进来)。
        sub = env.get("HL_SUBACCOUNT_ADDRESS", "").strip()
        if sub and not _is_addr(sub):
            raise SystemExit("HL_SUBACCOUNT_ADDRESS 必须是子账户地址(0x + 40 位),不用就留空")
        if sub and sub.lower() == self.account.lower():
            raise SystemExit("HL_SUBACCOUNT_ADDRESS 与主账户相同 —— 子账户是另一个地址(HL 网页「子账户」里看)")
        self.subaccount: Optional[str] = sub or None
        self.token = env.get("EXECUTOR_TOKEN", "").strip()
        if not self.token:
            raise SystemExit("EXECUTOR_TOKEN 未设置")
        self.api = env.get("EXECUTOR_API_BASE", DEFAULT_API).strip().rstrip("/")
        self.nav_cap = float(env.get("EXECUTOR_MAX_NAV_USD", "3000"))
        self.slip_bps = float(env.get("EXECUTOR_MAX_SLIP_BPS", "50"))
        self.stop_slip_bps = float(env.get("EXECUTOR_STOP_SLIP_BPS", "150"))
        self.state_dir = Path(env.get("EXECUTOR_STATE_DIR", "/var/lib/cometcloud"))
        self.host = env.get("EXECUTOR_HOST_NAME") or socket.gethostname()
        self.tickets_mode = env.get("EXECUTOR_TICKETS_MODE", "dry_run").strip()
        if self.tickets_mode not in ("off", "dry_run", "live"):
            raise SystemExit(f"EXECUTOR_TICKETS_MODE 必须是 off / dry_run / live,收到 {self.tickets_mode!r}")
        self.tickets_equity_cap = float(env.get("EXECUTOR_TICKETS_MAX_EQUITY_USD", "1000"))
        self.tickets_slip_bps = float(env.get("EXECUTOR_TICKETS_SLIP_BPS", "100"))
        # 主机复核(S-666 / S-667):规则 V′ 的开关;签名校验不受它管,始终强制
        self.verify_mode = env.get("EXECUTOR_VERIFY", verify.DEFAULT_MODE).strip()
        if self.verify_mode not in verify.MODES:
            raise SystemExit(f"EXECUTOR_VERIFY 必须是 {' / '.join(verify.MODES)},收到 {self.verify_mode!r}")
        # 私钥不进 Config:只在 live 模式建交易客户端的那一刻从环境变量里读一次(Venue.exchange)。
        # JAZZ_CALL_KEY(⓪ 签名密钥)同理,每轮复核时从环境变量读,不进 Config、不进日志(只记指纹)

    @property
    def halt_file(self) -> Path:
        return self.state_dir / "HALT"

    @property
    def trade_account(self) -> str:
        """执行器读写的那个账户:有子账户就是子账户,否则是主账户。"""
        return self.subaccount or self.account


def _is_addr(a: str) -> bool:
    return a.startswith("0x") and len(a) == 42


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
        return core.parse_balances(self.info.spot_user_state(self.cfg.trade_account))

    def subaccount_check(self) -> dict[str, Any]:
        """设了子账户时:它是不是主账户名下的。ok = True / False(HL 答了),None(读不到 —— 不等于不是)。"""
        sub = self.cfg.subaccount
        if not sub:
            return {"ok": None, "why": "没设子账户(整个主账户归执行器)"}
        try:
            rows = self.info.query_sub_accounts(self.cfg.account) or []
        except Exception as e:                                           # noqa: BLE001
            return {"ok": None, "address": sub, "why": f"读不到子账户列表:{type(e).__name__}: {str(e)[:120]}"}
        for r in rows if isinstance(rows, list) else []:
            if str((r or {}).get("subAccountUser", "")).lower() == sub.lower():
                return {"ok": True, "address": sub, "name": r.get("name")}
        return {"ok": False, "address": sub, "n_subaccounts": len(rows) if isinstance(rows, list) else 0,
                "why": "主账户名下没有这个子账户 —— 地址抄错了,或者子账户不是这个主账户开的"}

    def quotes(self) -> dict:
        from src.data.execution.dry_run import _spot_quotes_sync
        from src.data.venues.hl_spot import HlSpotClient
        return _spot_quotes_sync(HlSpotClient(poster=self._poster))

    def mids(self, pairs: dict[str, str]) -> dict[str, float]:
        allm = self.info.all_mids() or {}
        return {s: float(allm[p]) for s, p in pairs.items() if p in allm}

    def agent_check(self) -> dict[str, Any]:
        """切 live 前:主机上这把 API 钱包是不是主账户批准的 agent(HL `userRole`;`extraAgents` 给到期时间)。不下单。
        ok = True / False(HL 答了),None(读不到 —— 不等于不是)。只在 live 模式调用(要建交易客户端、读私钥)。"""
        try:
            agent = str(self.exchange().wallet.address)
        except Exception as e:                                           # noqa: BLE001
            return {"ok": False, "why": f"建不了交易客户端(私钥没配或不对):{type(e).__name__}: {str(e)[:120]}"}
        try:
            role = self.info.user_role(agent) or {}
        except Exception as e:                                           # noqa: BLE001
            return {"ok": None, "agent": agent, "why": f"读不到 userRole:{type(e).__name__}: {str(e)[:120]}"}
        master = str((role.get("data") or {}).get("user") or "")
        ok = role.get("role") == "agent" and master.lower() == self.cfg.account.lower()
        valid_until = None
        try:
            for a in self.info.extra_agents(self.cfg.account) or []:
                if str((a or {}).get("address", "")).lower() == agent.lower() and a.get("validUntil"):
                    valid_until = dt.datetime.fromtimestamp(int(a["validUntil"]) / 1000, dt.timezone.utc).isoformat()
        except Exception:                                                # noqa: BLE001 —— 到期时间只是附带信息
            pass
        return {"ok": ok, "agent": agent, "role": role.get("role"), "agent_of": master or None, "valid_until": valid_until,
                "why": None if ok else "这把 API 钱包不是 HL_ACCOUNT_ADDRESS 批准的 agent(没批准、已过期,或被新的替换了)"}

    def fills_since(self, t_ms: int) -> list[dict]:
        return self.info.user_fills_by_time(self.cfg.trade_account, t_ms) or []

    def exchange(self) -> Any:
        if self.cfg.mode != "live" and self.cfg.tickets_mode != "live":
            raise RuntimeError("dry_run 不建交易客户端,也不读私钥")
        if self._exchange is None:
            from eth_account import Account
            from hyperliquid.exchange import Exchange
            from hyperliquid.utils import constants
            wallet = Account.from_key(os.environ["HL_API_WALLET_PRIVATE_KEY"])
            # 子账户:主账户批准的 API 钱包可以替子账户签名,动作里带 vaultAddress = 子账户(HL 文档「Nonces and API wallets」)
            self._exchange = Exchange(wallet, constants.MAINNET_API_URL, account_address=self.cfg.account,
                                      vault_address=self.cfg.subaccount)
        return self._exchange

    def order(self, pair: str, side: str, qty: float, limit_px: float, cloid: str) -> Any:
        from hyperliquid.utils.types import Cloid
        return self.exchange().order(pair, side == BUY, qty, limit_px, {"limit": {"tif": "Ioc"}}, cloid=Cloid(cloid))

    # 永续(R-v2 单票)
    def perp_meta(self) -> dict[str, int]:
        return tickets.perp_meta(self.info.meta())

    def perp_mids(self) -> dict[str, float]:
        return {k: float(v) for k, v in (self.info.all_mids() or {}).items() if not str(k).startswith("@")}

    def perp_state(self) -> dict[str, Any]:
        return tickets.parse_perp_state(self.info.user_state(self.cfg.trade_account))

    def order_perp(self, coin: str, side: str, qty: float, limit_px: float, cloid: str, reduce_only: bool) -> Any:
        from hyperliquid.utils.types import Cloid
        return self.exchange().order(coin, side == BUY, qty, limit_px, {"limit": {"tif": "Ioc"}},
                                     reduce_only=reduce_only, cloid=Cloid(cloid))

    def stop_trigger(self, coin: str, qty: float, limit_px: float, order_type: dict, cloid: str) -> Any:
        from hyperliquid.utils.types import Cloid
        return self.exchange().order(coin, False, qty, limit_px, order_type, reduce_only=True, cloid=Cloid(cloid))

    def cancel(self, coin: str, oid: int) -> Any:
        return self.exchange().cancel(coin, oid)

    def daily_bars(self, coin: str, through: dt.date) -> list[dict]:
        """HL 公开日线(到 through 为止,含),给主机复核用 —— 不经过 Railway、不经过我们的库。"""
        end = dt.datetime.combine(through + dt.timedelta(days=1), dt.time(0), tzinfo=dt.timezone.utc)
        start = end - dt.timedelta(days=verify.BARS_NEEDED + 5)
        return verify.hl_bars(self.info.candles_snapshot(coin, "1d", int(start.timestamp() * 1000),
                                                         int(end.timestamp() * 1000) - 1))


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
        tp = self.state.get("ticket_plan") or {}
        tickets_waiting = self.cfg.tickets_mode != "off" and not (tp.get("asof") == want and tp.get("ready"))
        have_today = plan.get("asof") == want and not tickets_waiting
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
        if isinstance(resp.get("tickets"), dict):
            self.state.set(ticket_plan=resp["tickets"], ticket_plan_fetched_at=now.isoformat())
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

    # ── R-v2 单票(HL 永续)────────────────────────────────────────────────
    def _report_t(self, kind: str, **kw: Any) -> None:
        self.outbox.put({"mode": self.cfg.tickets_mode, "book": "r_v2", "kind": kind, "host": self.cfg.host, **kw})

    def _ticket_equity(self) -> tuple[float, dict, str]:
        """(记账净值, 交易所仓位, 净值来源)。live:永续账户净值封顶;空跑:账上虚拟仓位,净值同样读真实账户,
        账户为空时拿上限当净值(写明来源,不假装)。"""
        live = self.cfg.tickets_mode == "live"
        try:
            st = self.venue.perp_state()
        except Exception as e:                                           # noqa: BLE001
            if live:
                raise
            st = {"ok": False, "equity": 0.0, "positions": {}, "error": f"{type(e).__name__}: {str(e)[:120]}"}
        raw = float(st.get("equity") or 0.0)
        cap = self.cfg.tickets_equity_cap
        if live:
            # 读不到账户 ≠ 账户里没有仓位:当成「全平了」会把账上的票全部记成已平,真仓位就没人管了
            if not st.get("ok"):
                raise RuntimeError("永续账户状态读不到(没有 marginSummary)—— 这一轮不动")
            return min(raw, cap), st.get("positions") or {}, f"永续账户 {raw:.2f}(上限 {cap:.0f})"
        book = self.state.get("ticket_book") or {}
        virt = {b["coin"]: b["qty"] for b in book.values()}
        if raw >= tickets.MIN_NOTIONAL_USD:
            return min(raw, cap), virt, f"空跑 · 永续账户 {raw:.2f}(上限 {cap:.0f})"
        return cap, virt, f"空跑 · 永续账户为空({raw:.2f}),按上限 {cap:.0f} 记账"

    def _ticket_intent(self, coin: str, side: str, qty: float, mid: float, sleeve: str, ref: str, now: dt.datetime,
                       limit_px: float):
        return core.make_intent({"symbol": coin, "side": side, "qty_base": qty, "price": mid}, sleeve, ref, now, limit_px)

    def _send_ticket_orders(self, staged: list) -> list:
        """live:逐个下减仓 / 开仓 IOC;每个意图恰好一个结果。staged = [(intent, coin, qty, reduce_only, sz_decimals)]。"""
        t0_ms = int(time.time() * 1000) - 2000
        sent = []
        for intent, coin, qty, reduce_only, _szd in staged:
            t_sent = time.time()
            try:
                parsed = core.parse_order_response(self.venue.order_perp(
                    coin, intent.side, qty, intent.limit_price, core.cloid_for(intent.intent_id), reduce_only))
            except Exception as e:                                       # noqa: BLE001
                parsed = {"kind": "error", "error": f"{type(e).__name__}: {str(e)[:200]}"}
            sent.append((intent, qty, parsed, t_sent, time.time()))
        time.sleep(self.settle_s)
        try:
            fills = self.venue.fills_since(t0_ms)
        except Exception:                                                # noqa: BLE001
            fills = []
        try:
            mids = self.venue.perp_mids()
        except Exception:                                                # noqa: BLE001
            mids = {}
        now = self.clock()
        return [core.outcome_for(i, qty, parsed, fills, mids.get(i.symbol), ts, td, now) for i, qty, parsed, ts, td in sent]

    def _place_trigger(self, b: dict, now: dt.datetime) -> dict:
        """按账上的止损线挂减仓止损触发单;返回更新后的账行(trigger_oid / trigger_error)。只在 live。"""
        lim, otype = tickets.trigger_order(b["stop_px"], b["sz_decimals"])
        try:
            parsed = core.parse_order_response(self.venue.stop_trigger(b["coin"], b["qty"], lim, otype,
                                                                       core.cloid_for(str(uuid.uuid4()))))
        except Exception as e:                                           # noqa: BLE001
            parsed = {"kind": "error", "error": f"{type(e).__name__}: {str(e)[:200]}"}
        if parsed["kind"] == "resting" and parsed.get("oid") is not None:
            # Book of Truth:交易所上的每一张单子都有意图 —— 止损触发单也是;成交 / 撤销时补结果
            intent = replace(self._ticket_intent(b["coin"], SELL, b["qty"], b["stop_px"], self._t_sleeve(),
                                                 f"r_v2:{b['ticket_id']}:stop_trigger", now, lim), order_type="trigger")
            self._report_t("stop", asof=(self.state.get("ticket_plan") or {}).get("asof"), intents=[asdict(intent)],
                           detail={"phase": "trigger", "ticket_id": b["ticket_id"], "oid": parsed["oid"]})
            return {**b, "trigger_oid": parsed["oid"], "trigger_error": None, "trigger_at": now.isoformat(),
                    "trigger_intent_id": intent.intent_id}
        return {**b, "trigger_oid": None, "trigger_error": str(parsed.get("error") or parsed)[:200]}

    def _t_sleeve(self) -> str:
        tp = self.state.get("ticket_plan") or {}
        return (tp.get("sleeves") or {}).get(self.cfg.tickets_mode) or f"r_v2_{self.cfg.tickets_mode}"

    def _resolve_trigger(self, b: dict, now: dt.datetime, fill: Optional[dict], note: str) -> None:
        """止损触发单的意图补一个结果:成交(按交易所的真实成交)或撤销。没有触发单意图的票不动。"""
        iid = b.get("trigger_intent_id")
        if not iid:
            return
        if fill:
            o = core.Outcome(intent_id=iid, ts_resolved=now.isoformat(),
                             status=FILLED if fill["sz"] >= b["qty"] * (1 - 1e-9) else PARTIAL,
                             filled_notional_usd=round(fill["sz"] * fill["px"], 6), avg_fill_price=fill["px"],
                             fee_usd=round(fill["fee"], 6), liquidity="taker", note=note)
        else:
            o = core.Outcome(intent_id=iid, ts_resolved=now.isoformat(), status=CANCELLED, note=note)
        self._report_t("stop", asof=(self.state.get("ticket_plan") or {}).get("asof"), outcomes=[asdict(o)],
                       detail={"phase": "trigger_outcome", "ticket_id": b["ticket_id"], "status": o.status})

    def _venue_closed(self, tids: list[str], now: dt.datetime) -> None:
        """交易所上已平(触发单成交 / 手动平 / 强平):先按止损线临时记平仓,真实成交进待查,马上查一次。"""
        book = self.state.get("ticket_book") or {}
        pend = dict(self.state.get("truth_pending") or {})
        for t in tids:
            if t in book:
                pend[t] = {**book[t], "closed_seen_at": now.isoformat()}
        self._close_book(tids, "交易所上已平(止损触发单成交或手动平仓)", {t: book[t].get("stop_px") for t in tids
                                                                    if t in book}, now)
        self.state.set(truth_pending=pend)
        self.settle_truth(now)

    def settle_truth(self, now: dt.datetime) -> list[str]:
        """待查的平仓去交易所找真实成交:找到 ⇒ 改平仓价、给触发单意图补结果(没有触发单意图的补记一条 venue_close);
        24 小时还找不到 ⇒ 按找不到结案。成交读不到 = 下一分钟再查,不当「没成交」。"""
        pend = dict(self.state.get("truth_pending") or {})
        if not pend:
            return []
        since = min(_ms(b.get("entered_at")) for b in pend.values())
        try:
            fills = self.venue.fills_since(max(0, since - 1000))
        except Exception as e:                                           # noqa: BLE001
            log.warning("fills unreadable, truth stays pending: %s", e)
            return []
        done_ids = []
        for t, b in list(pend.items()):
            f = tickets.close_fills(fills, b["coin"], _ms(b.get("entered_at")), b.get("trigger_oid"))
            age = (now - dt.datetime.fromisoformat(b["closed_seen_at"])).total_seconds()
            if not f and age < TRUTH_GIVE_UP_S:
                continue
            note = (f"交易所成交 {int(f['n'])} 笔,均价 {f['px']:.6g}(止损线 {b.get('stop_px')})" if f
                    else "仓位没了,24 小时内找不到平仓成交")
            if b.get("trigger_intent_id"):
                self._resolve_trigger(b, now, f, note)
            else:
                # 没挂过(或旧版本挂的)触发单:是手动平仓或强平 —— 也要进真相之书
                ref = b.get("stop_px") or b.get("entry_px") or 0.0
                i = replace(self._ticket_intent(b["coin"], SELL, b["qty"], ref, self._t_sleeve(),
                                                f"r_v2:{t}:venue_close", now, ref), order_type="unknown")
                o = (core.Outcome(intent_id=i.intent_id, ts_resolved=now.isoformat(),
                                  status=FILLED if f["sz"] >= b["qty"] * (1 - 1e-9) else PARTIAL,
                                  filled_notional_usd=round(f["sz"] * f["px"], 6), avg_fill_price=f["px"],
                                  fee_usd=round(f["fee"], 6), liquidity="taker", note=note) if f else
                     core.Outcome(intent_id=i.intent_id, ts_resolved=now.isoformat(), status=CANCELLED, note=note))
                self._report_t("stop", asof=(self.state.get("ticket_plan") or {}).get("asof"), intents=[asdict(i)],
                               outcomes=[asdict(o)], detail={"phase": "venue_close", "ticket_id": t},
                               alert=f"R-v2 {b['coin']} 交易所上被平,但不是我们的止损触发单(手动 / 强平?):{note}")
            if f:
                done = dict(self.state.get("ticket_done") or {})
                if t in done:
                    done[t] = {**done[t], "close_px": f["px"], "close_px_source": "venue_fills"}
                    self.state.set(ticket_done=done)
            del pend[t]
            done_ids.append(t)
        self.state.set(truth_pending=pend)
        return done_ids

    def _close_book(self, tids: list[str], why: str, px: dict[str, Optional[float]], now: dt.datetime) -> None:
        book = dict(self.state.get("ticket_book") or {})
        done = dict(self.state.get("ticket_done") or {})
        for tid in tids:
            b = book.pop(tid, None)
            if b:
                done[tid] = {**b, "closed_at": now.isoformat(), "close_why": why, "close_px": px.get(tid)}
        done = dict(sorted(done.items(), key=lambda kv: kv[1].get("closed_at", ""))[-300:])
        self.state.set(ticket_book=book, ticket_done=done)

    def _verify_plan(self, tp: dict, szd: dict, book: dict, done: set) -> tuple[dict, dict]:
        """主机复核(verify.py):今天要进场的票 → HL 公开日线 / Jazz 签名 → 主机真正执行的计划 + 判定。
        日线读不到 ⇒ 当成没有那根(V1 不过):report 下只记,enforce 下不进 —— 读不到不等于没问题。"""
        enter = [e for e in tp.get("enter") or [] if e.get("ticket_id") not in book and e.get("ticket_id") not in done]
        coin_of = {e["ticket_id"]: tickets.resolve_coin(e.get("symbol") or "", szd) for e in enter}
        bars: dict[str, list[dict]] = {}
        if self.cfg.verify_mode != "off":
            for e in enter:
                c = coin_of.get(e["ticket_id"])
                sd = verify._d(e.get("signal_d"))
                if c and sd and c not in bars and not verify.is_j(e):
                    try:
                        bars[c] = self.venue.daily_bars(c, sd)
                    except Exception as ex:                              # noqa: BLE001
                        log.warning("HL daily bars for %s unreadable: %s", c, ex)
                        bars[c] = []
        key = os.environ.get("JAZZ_CALL_KEY", "").strip() or None
        tp_v, vsum = verify.review({**tp, "enter": enter}, bars, coin_of, key, self.cfg.verify_mode)
        vsum["key_fingerprint"] = verify.key_fingerprint(key) if key else None
        # 每票风险占比:计划是上游给的,主机再守一次 2% 的硬上限
        try:
            rf = float(tp_v.get("risk_frac") or 0.0)
        except (TypeError, ValueError):
            rf = 0.0
        if not (0.0 <= rf <= tickets.MAX_RISK_FRAC):
            vsum["risk_frac_capped"] = {"plan": tp_v.get("risk_frac"), "host": tickets.MAX_RISK_FRAC}
            tp_v["risk_frac"] = min(max(rf, 0.0), tickets.MAX_RISK_FRAC)
        return tp_v, vsum

    def run_ticket_cycle(self, now: dt.datetime) -> dict[str, Any]:
        tp = self.state.get("ticket_plan") or {}
        live = self.cfg.tickets_mode == "live"
        sleeve = (tp.get("sleeves") or {}).get(self.cfg.tickets_mode) or f"r_v2_{self.cfg.tickets_mode}"
        halted, why_halt = self.halted()
        szd, mids = self.venue.perp_meta(), self.venue.perp_mids()
        equity, positions, eq_src = self._ticket_equity()
        book = dict(self.state.get("ticket_book") or {})
        done = set((self.state.get("ticket_done") or {}).keys())
        tp_v, vsum = self._verify_plan(tp, szd, book, done)
        act = tickets.ticket_actions(tp_v, book, positions, mids, szd, equity, done)
        act["not_executable"] = list(act["not_executable"]) + list(tp_v.get("host_rejected") or [])
        if act["closed_on_venue"]:
            self._venue_closed([c["ticket_id"] for c in act["closed_on_venue"]], now)
            book = dict(self.state.get("ticket_book") or {})
        staged = []
        for x in act["exits"]:
            b = book[x["ticket_id"]]
            mid = mids.get(x["coin"]) or b["entry_px"]
            lim = tickets.ioc_px_perp(mid, False, self.cfg.tickets_slip_bps, b["sz_decimals"])
            staged.append((self._ticket_intent(x["coin"], SELL, x["qty"], mid, sleeve,
                                               f"r_v2:{x['ticket_id']}:exit:{x['why']}", now, lim),
                           x["coin"], x["qty"], True, b["sz_decimals"]))
        for e in act["entries"]:
            lim = tickets.ioc_px_perp(e["mid"], True, self.cfg.tickets_slip_bps, e["sz_decimals"])
            staged.append((self._ticket_intent(e["coin"], BUY, e["qty"], e["mid"], sleeve,
                                               f"r_v2:{e['ticket_id']}:enter", now, lim),
                           e["coin"], e["qty"], False, e["sz_decimals"]))
        mins = core.minutes_after_close(now)
        detail = {"phase": "intents", "book_name": "r_v2", "asof": tp.get("asof"), "minutes_after_close": round(mins, 1),
                  "equity": round(equity, 2), "equity_source": eq_src, "risk_frac": tp.get("risk_frac"),
                  "portfolio_leverage": act.get("portfolio_leverage"), "alloc": round(act.get("alloc") or 0.0, 2),
                  "closed_on_venue": act["closed_on_venue"],
                  "exits": [{k: x[k] for k in ("ticket_id", "coin", "qty", "why")} for x in act["exits"]],
                  "entries": [{k: e.get(k) for k in ("ticket_id", "symbol", "coin", "qty", "notional", "risk_usd",
                                                     "stop_frac", "mid", "capped", "risk_mult", "book")}
                              for e in act["entries"]],
                  "regime_call": {k: (tp.get("regime_call") or {}).get(k) for k in ("id", "state", "conviction", "source")},
                  "blocked_by_call": [b.get("ticket_id") for b in tp.get("blocked_by_call") or []],
                  "not_executable": [{k: n.get(k) for k in ("ticket_id", "symbol", "coin", "why")}
                                     for n in act["not_executable"]],
                  "skipped_cap_paper": [s["ticket_id"] for s in tp.get("skipped_cap") or []],
                  "verify": vsum,
                  "open_before": len(book), "halted": halted, "halt_why": why_halt}
        lines = [f"出 {x['coin']} {x['qty']}({x['why']})" for x in act["exits"]] + \
                [f"进 {e['coin']} {e['qty']}(~${e['notional']},止损 −{e['stop_frac']:.1%})" for e in act["entries"]] + \
                [f"不可执行 {n['symbol']}:{n['why']}" for n in act["not_executable"]]
        alert = (f"R-v2 {tp.get('asof')} · {self.cfg.tickets_mode}{' · 已停,不提交' if halted else ''}: " + "; ".join(lines)
                 ) if lines else None
        self._report_t("cycle", asof=tp.get("asof"), intents=[asdict(i) for i, *_ in staged], detail=detail,
                       alert=alert if (not live or halted) else None)
        outcomes: list = []
        if live and staged and halted:
            outcomes = self._not_submitted([(i, None, None) for i, *_ in staged], f"一键停({why_halt}):未提交")
        elif live and staged:
            for x in act["exits"]:
                oid = book[x["ticket_id"]].get("trigger_oid")
                if oid is not None:
                    try:
                        self.venue.cancel(x["coin"], oid)
                    except Exception as e:                               # noqa: BLE001
                        log.warning("cancel trigger %s failed: %s", oid, e)
                    self._resolve_trigger(book[x["ticket_id"]], now, None, f"出场({x['why']})前撤掉")
                    book[x["ticket_id"]] = {**book[x["ticket_id"]], "trigger_oid": None, "trigger_intent_id": None}
            self.state.set(ticket_book=book)
            outcomes = self._send_ticket_orders(staged)
        # 账本:live 按成交结果,空跑按中间价虚拟成交
        by_ref = {i.signal_ref: (i, o) for (i, *_), o in zip(staged, outcomes or [None] * len(staged))}
        exit_px: dict[str, Optional[float]] = {}
        for x in act["exits"]:
            i, o = by_ref[next(r for r in by_ref if r.startswith(f"r_v2:{x['ticket_id']}:exit"))]
            if not live:
                exit_px[x["ticket_id"]] = i.decision_mid
            elif o is not None and o.status in ("filled", "partial") and o.avg_fill_price:
                exit_px[x["ticket_id"]] = o.avg_fill_price
        closed = list(exit_px)
        if closed:
            self._close_book(closed, "出场", exit_px, now)
        book = dict(self.state.get("ticket_book") or {})
        if live and not halted:
            # 出场单没成交:触发单已经撤了 ⇒ 记下来,止损循环 15 分钟内重挂;明天的 cycle 再出
            for x in act["exits"]:
                if x["ticket_id"] in book and x["ticket_id"] not in exit_px:
                    book[x["ticket_id"]] = {**book[x["ticket_id"]], "trigger_oid": None,
                                            "trigger_error": "出场单没成交,止损触发单已撤 —— 待重挂"}
        for e in act["entries"]:
            i, o = by_ref[f"r_v2:{e['ticket_id']}:enter"]
            if live and halted:
                continue
            if live:
                if o is None or o.status not in ("filled", "partial") or not o.avg_fill_price:
                    continue
                fill_px, qty = o.avg_fill_price, round(o.filled_notional_usd / o.avg_fill_price, e["sz_decimals"])
            else:
                fill_px, qty = e["mid"], e["qty"]
            b = {"ticket_id": e["ticket_id"], "symbol": e["symbol"], "coin": e["coin"], "qty": qty,
                 "entry_px": fill_px, "stop_frac": e["stop_frac"], "sz_decimals": e["sz_decimals"],
                 "stop_px": tickets.stop_px_for(fill_px, e["stop_frac"], e["sz_decimals"]),
                 "signal_d": e.get("signal_d"), "entered_at": now.isoformat(), "trigger_oid": None}
            if live and qty > 0:
                b = self._place_trigger(b, now)
            if qty > 0:
                book[e["ticket_id"]] = b
        self.state.set(ticket_book=book, ticket_done_asof=tp.get("asof"), ticket_cycle_at=now.isoformat())
        if live and staged:
            bad = [b for b in book.values() if b.get("trigger_error")]
            self._report_t("cycle", asof=tp.get("asof"), outcomes=[asdict(x) for x in outcomes],
                           detail={"phase": "outcomes", "statuses": [x.status for x in outcomes],
                                   "book": self._book_brief(book)},
                           alert=f"R-v2 {tp.get('asof')} 真单: " + "; ".join(
                               f"{i.symbol} {i.side} → {x.status} {x.avg_fill_price or ''}"
                               for (i, *_), x in zip(staged, outcomes))
                           + ("" if not bad else " · ⚠️ 止损触发单没挂上:" + ", ".join(b["coin"] for b in bad)))
        return {**detail, "intents": [asdict(i) for i, *_ in staged], "outcomes": [asdict(x) for x in outcomes]}

    @staticmethod
    def _book_brief(book: dict) -> list[dict]:
        return [{k: b.get(k) for k in ("ticket_id", "coin", "qty", "entry_px", "stop_px", "trigger_oid")}
                for b in book.values()]

    def check_ticket_stops(self, now: dt.datetime) -> list[str]:
        """每分钟:空跑 = 现价 ≤ 止损线就按止损线虚拟平仓;live = 交易所上仓位没了就记平仓,
        仓位还在但现价已破止损线 ⇒ 补一张减仓 IOC(触发单的后备),触发单没挂上的再挂一次。"""
        book = dict(self.state.get("ticket_book") or {})
        if not book or self.cfg.tickets_mode == "off":
            return []
        mids = self.venue.perp_mids()
        hits = tickets.stop_breaches(book, mids)
        tp = self.state.get("ticket_plan") or {}
        sleeve = (tp.get("sleeves") or {}).get(self.cfg.tickets_mode) or f"r_v2_{self.cfg.tickets_mode}"
        if self.cfg.tickets_mode != "live":
            if hits:
                virt = [replace(self._ticket_intent(book[t]["coin"], SELL, book[t]["qty"], book[t]["stop_px"], sleeve,
                                                    f"r_v2:{t}:stop_virtual", now, book[t]["stop_px"]),
                                order_type="trigger") for t in hits]
                self._close_book(hits, "止损(空跑:现价 ≤ 止损线)", {t: book[t]["stop_px"] for t in hits}, now)
                self._report_t("stop", asof=tp.get("asof"), intents=[asdict(i) for i in virt],
                               detail={"hits": hits, "mids": {t: mids.get(book[t]["coin"]) for t in hits}},
                               alert="R-v2 空跑止损: " + "; ".join(f"{book[t]['coin']} {mids.get(book[t]['coin'])} ≤ {book[t]['stop_px']}" for t in hits))
            return hits
        st = self.venue.perp_state()
        if not st.get("ok"):
            raise RuntimeError("永续账户状态读不到 —— 不据此记平仓")
        positions = st.get("positions") or {}
        gone = [t for t, b in book.items() if positions.get(b["coin"], 0.0) <= 0]
        if gone:
            self._venue_closed(gone, now)
            self._report_t("stop", asof=tp.get("asof"), detail={"closed_on_venue": gone},
                           alert="R-v2 止损(交易所触发单): " + ", ".join(book[t]["coin"] for t in gone))
        book = dict(self.state.get("ticket_book") or {})
        halted, why_halt = self.halted()
        backup = [t for t in hits if t in book]
        if backup and not halted:
            staged = []
            for t in backup:
                b = book[t]
                qty = min(b["qty"], positions.get(b["coin"], 0.0))
                lim = tickets.ioc_px_perp(mids[b["coin"]], False, self.cfg.stop_slip_bps, b["sz_decimals"])
                staged.append((self._ticket_intent(b["coin"], SELL, qty, mids[b["coin"]], sleeve,
                                                   f"r_v2:{t}:stop_backup", now, lim), b["coin"], qty, True, b["sz_decimals"]))
            self._report_t("stop", asof=tp.get("asof"), intents=[asdict(i) for i, *_ in staged],
                           detail={"backup_stop": backup})
            outs = self._send_ticket_orders(staged)
            filled = [t for t, o in zip(backup, outs) if o.status in ("filled", "partial")]
            for t in filled:
                if book[t].get("trigger_oid") is not None:
                    try:
                        self.venue.cancel(book[t]["coin"], book[t]["trigger_oid"])
                    except Exception as e:                               # noqa: BLE001
                        log.warning("cancel trigger %s failed: %s", book[t]["trigger_oid"], e)
                self._resolve_trigger(book[t], now, None, "后备 IOC 先平了,触发单撤掉")
            self._close_book(filled, "止损(主机后备 IOC)", {t: o.avg_fill_price for t, o in zip(backup, outs)}, now)
            self._report_t("stop", asof=tp.get("asof"), outcomes=[asdict(o) for o in outs],
                           detail={"phase": "outcomes", "statuses": [o.status for o in outs]},
                           alert="R-v2 后备止损: " + "; ".join(f"{i.symbol} → {o.status}" for (i, *_), o in zip(staged, outs)))
        for t, b in (self.state.get("ticket_book") or {}).items():
            last = b.get("trigger_retry_at")
            if b.get("trigger_oid") is None and not halted and (
                    not last or (now - dt.datetime.fromisoformat(last)).total_seconds() >= TRIGGER_RETRY_S):
                nb = {**self._place_trigger(b, now), "trigger_retry_at": now.isoformat()}
                book2 = dict(self.state.get("ticket_book") or {})
                book2[t] = nb
                self.state.set(ticket_book=book2)
        return hits

    def _maybe_ticket_cycle(self, now: dt.datetime) -> None:
        tp = self.state.get("ticket_plan") or {}
        if (self.cfg.tickets_mode != "off" and tp.get("ready") and tp.get("asof") == asof_for(now)
                and self.state.get("ticket_done_asof") != tp["asof"]):
            r = self.run_ticket_cycle(now)
            log.info("ticket cycle %s: %d entries, %d exits, %d not executable", tp["asof"], len(r["entries"]),
                     len(r["exits"]), len(r["not_executable"]))

    def heartbeat(self, now: dt.datetime) -> None:
        try:
            b = self.venue.balances()
            bal = {k: round(v["total"], 8) for k, v in b.items() if v.get("total")}
        except Exception as e:                                           # noqa: BLE001
            bal = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
        halted, why = self.halted()
        plan = self.state.get("plan") or {}
        self._report("heartbeat", asof=plan.get("asof"), detail={
            "balances": bal, "trade_account": self.cfg.trade_account, "subaccount": bool(self.cfg.subaccount),
            "plan_asof": plan.get("asof"), "done_asof": self.state.get("done_asof"),
            "stop_px": plan.get("stop_px"), "halted": halted, "halt_why": why,
            "tickets_mode": self.cfg.tickets_mode, "ticket_book": self._book_brief(self.state.get("ticket_book") or {}),
            "ticket_plan_asof": (self.state.get("ticket_plan") or {}).get("asof"),
            "ticket_done_asof": self.state.get("ticket_done_asof"),
            "truth_pending": sorted((self.state.get("truth_pending") or {}).keys()),
            "outbox_pending": len(self.outbox.pending()), "at": now.isoformat()})

    def tick(self) -> None:
        now = self.clock()
        for name, fn in (("flush", lambda: self.outbox.flush(self.railway)),
                         ("plan", lambda: self.refresh_plan(now)),
                         ("cycle", lambda: self._maybe_cycle(now)),
                         ("tickets", lambda: self._maybe_ticket_cycle(now)),
                         ("stop", lambda: self._every("stop", STOP_EVERY_S, lambda: self.check_stops(now))),
                         ("ticket_stop", lambda: self._every("ticket_stop", STOP_EVERY_S,
                                                             lambda: self.check_ticket_stops(now))),
                         ("ticket_truth", lambda: self._every("ticket_truth", STOP_EVERY_S,
                                                              lambda: self.settle_truth(now))),
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
    out: dict[str, Any] = {"mode": ex.cfg.mode, "account": ex.cfg.account, "trade_account": ex.cfg.trade_account,
                           "api": ex.cfg.api, "nav_cap": ex.cfg.nav_cap, "halted": ex.halted()}
    if ex.cfg.subaccount:
        out["subaccount"] = ex.venue.subaccount_check()
    if ex.cfg.mode == "live" or ex.cfg.tickets_mode == "live":
        out["agent"] = ex.venue.agent_check()
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
    if ex.cfg.tickets_mode != "off":
        tp = plan.get("tickets") if isinstance(plan, dict) else None
        key = os.environ.get("JAZZ_CALL_KEY", "").strip()
        t: dict[str, Any] = {"mode": ex.cfg.tickets_mode, "equity_cap": ex.cfg.tickets_equity_cap,
                             "verify": {"mode": ex.cfg.verify_mode,
                                        "jazz_call_key": verify.key_fingerprint(key) if key else
                                        "没有 —— J 票一律不开、风险倍数按 1(Mac 上 regime_call.py keygen --show 抄过来)"},
                             "plan": {k: (tp or {}).get(k) for k in ("asof", "ready", "why", "last_d", "risk_frac", "cap",
                                                                      "portfolio_leverage")}}
        try:
            st = ex.venue.perp_state()
            szd, mids = ex.venue.perp_meta(), ex.venue.perp_mids()
            t["perp_account"] = {"ok": st.get("ok"), "equity": st.get("equity"), "positions": st.get("positions")}
            t["hl_perps_listed"] = len(szd)
            if not st.get("ok") or (st.get("equity") or 0) < tickets.MIN_NOTIONAL_USD:
                t["warning"] = (("子账户" if ex.cfg.subaccount else "") + "永续账户里没有可用的 USDC —— 真跑前要在 HL 上把 USDC "
                                + ("划进子账户的永续" if ex.cfg.subaccount else "从现货划到永续") + "(Jazz 手动)")
            if tp and tp.get("ready"):
                eq = min(st.get("equity") or 0.0, ex.cfg.tickets_equity_cap) or ex.cfg.tickets_equity_cap
                book, done = ex.state.get("ticket_book") or {}, set((ex.state.get("ticket_done") or {}).keys())
                tp_v, vsum = ex._verify_plan(tp, szd, book, done)
                t["verify"]["today"] = {k: vsum.get(k) for k in ("call_signed", "call_why", "call_mult", "n", "passed",
                                                                 "blocked")}
                act = tickets.ticket_actions(tp_v, book, st.get("positions") or {}, mids, szd, eq, done)
                act["not_executable"] = list(act["not_executable"]) + list(tp_v.get("host_rejected") or [])
                t["would"] = {"enter": [{k: e.get(k) for k in ("symbol", "coin", "qty", "notional", "stop_frac")}
                                        for e in act["entries"]],
                              "exit": act["exits"], "not_executable": [{k: n.get(k) for k in ("symbol", "why")}
                                                                       for n in act["not_executable"]]}
        except Exception as e:                                           # noqa: BLE001
            t["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        out["tickets"] = t
    ex.heartbeat(utcnow())
    out["report"] = ex.outbox.flush(ex.railway)
    return out


def refuse_foreign_subaccount(venue: Venue) -> None:
    """子账户地址 HL 明确说不在主账户名下 ⇒ 不启动(读余额会读到别人的账户、按别人的净值定尺寸)。
    读不到列表(网络)⇒ 照常启动:下单时 HL 自己会拒绝没被授权的 vaultAddress。"""
    c = venue.subaccount_check()
    if c.get("ok") is False:
        raise SystemExit(f"HL_SUBACCOUNT_ADDRESS {c.get('address')}:{c.get('why')} —— 不启动")
    if c.get("ok") is None and venue.cfg.subaccount:
        log.warning("subaccount not verified at start: %s", c.get("why"))


def refuse_unapproved_agent(venue: Venue) -> None:
    """live 模式:HL 明确说这把 API 钱包不是主账户的 agent ⇒ 不启动(第一张真单才发现「签名被拒」太晚)。
    dry_run 不读私钥,不查。读不到 userRole ⇒ 照常启动、记警告(HL 自己会拒没授权的签名)。"""
    if venue.cfg.mode != "live" and venue.cfg.tickets_mode != "live":
        return
    c = venue.agent_check()
    if c.get("ok") is False:
        raise SystemExit(f"API 钱包没被主账户批准:{c.get('why')} —— 不启动")
    if c.get("ok") is None:
        log.warning("agent not verified at start: %s", c.get("why"))
    else:
        log.info("agent %s approved by %s, valid until %s", c.get("agent"), c.get("agent_of"), c.get("valid_until"))


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description="CometCloud 云主机执行器")
    ap.add_argument("--check", action="store_true", help="自检一次(不下单)并发一条心跳,然后退出")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config()
    ex = Executor(cfg, Venue(cfg), Railway(cfg.api, cfg.token))
    if args.check:
        out = check(ex)
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        if (out.get("subaccount") or {}).get("ok") is False:
            raise SystemExit("HL_SUBACCOUNT_ADDRESS 不是这个主账户的子账户 —— 不启动")
        if (out.get("agent") or {}).get("ok") is False:
            raise SystemExit(f"live 模式但 API 钱包没被主账户批准:{out['agent'].get('why')} —— 不启动")
        return
    refuse_foreign_subaccount(ex.venue)
    refuse_unapproved_agent(ex.venue)
    log.info("executor up · mode=%s · account=%s · trade_account=%s · api=%s · nav_cap=%s",
             cfg.mode, cfg.account, cfg.trade_account, cfg.api, cfg.nav_cap)
    ex._report("heartbeat", detail={"event": "start", "mode": cfg.mode, "nav_cap": cfg.nav_cap,
                                    "trade_account": cfg.trade_account, "subaccount": bool(cfg.subaccount)},
               alert=f"执行器启动 · {cfg.mode} · {cfg.host}" + (" · 子账户" if cfg.subaccount else ""))
    while True:
        ex.tick()
        time.sleep(LOOP_S)


if __name__ == "__main__":
    main()
