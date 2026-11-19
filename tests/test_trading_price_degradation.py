"""S-895 阶段 1 —— 交易路由的降级语义:**拿不到价就是拿不到价**。

**为什么有这个测试。** 2026-11-17 起 CoinGecko 超额调用要钱 ⇒ 闸门
(`src/data/market/cg_guard.py`)开始真的会拒绝 ⇒ 拒绝时返回**合成 503**。
交易路由(`src/api/routers/trading.py`)原来在这件事上的写法是:

```python
price = prices.get(sym, pos["entry_price"])   # 拿不到价 → 用开仓价
```

拿不到标记价 ⇒ 用开仓价 ⇒ **PnL 精确等于 0** ⇒ 与「仓位真的平了」同形。
一份「今天没有价格」的报告,和一份「今天全部平了」的报告,**长得一模一样**。
更糟的是 SL/TP:开仓价常常就落在止损位之内 ⇒ 一个「价格取不到」的仓位会被
**假止损**平掉 ⇒ 写进 `trade_results` 的已实现盈亏是**编出来的** ⇒ 喂给
Learn 循环的是一个假样本。

`docs/DATA_ARCHITECTURE.md:109`:未测量 = NaN 且必须传播(I1)。
所以这一阶段的验收是**语义**的,不是「别崩」的:

① 合成 503(闸门拒了)与真 503(上游挂了)⇒ `current_price is None`
   (**不是** `entry_price`)、`unrealized_pnl is None`、`price_source == "unavailable"`;
② **SL/TP 不触发** —— 既不置 flag,也不平仓;
③ 同 symbol 集合连打两次 ⇒ 只发 **1** 次外部请求(函数层缓存);
④ 前端 `null` ⇒ 渲染「—」,而**真的 0 仍然渲染「+0.00」**(0 是数据,不是缺失)。

④ 的后半句最重要:修「null 塌成 0」最常见的翻车是把 **0 也当成缺失**,
于是「盈亏正好为零」显示成「没测量」。`isMissing(0) === false` 是这条边界。
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.api.routers import trading                              # noqa: E402
from src.data.market import cg_guard                             # noqa: E402
from src.data.market.cg_guard import GuardedCGClient             # noqa: E402


# ── 脚手架 ────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """每个用例都从零状态开始:价缓存空、闸门关着、不碰真 Redis。

    ⚠️ `CG_DAILY_BUDGET` **不能**设成 0 来逼闸门拒绝 ——
    `cg_guard.effective_budget()` 读它时要求 `n > 0`,0 会静默回落成 16,000。
    想让闸门拒绝,正确姿势是**把熔断打开**(下一段 `_breaker_open`)。
    """
    trading._price_cache.clear()
    monkeypatch.setattr(cg_guard, "_UPSTASH_URL", "")
    monkeypatch.setattr(cg_guard, "_local_used", {})
    monkeypatch.setattr(cg_guard, "_local_breaker_until", 0.0)
    monkeypatch.setattr(cg_guard, "_local_tripped", 0)
    monkeypatch.setattr(cg_guard, "_local_unbudgeted", {})
    monkeypatch.setattr(cg_guard, "_local_unbudgeted_ep", {})
    monkeypatch.setenv("CG_DAILY_BUDGET", "16000")
    monkeypatch.setenv("CG_BREAKER_COOLDOWN_S", "300")
    # 交易所兜底不在本文件的作用域里 —— 钉死成「没有 key」,免得测试机上有。
    monkeypatch.setattr(trading, "_EODHD_KEY", "")
    monkeypatch.setattr(trading, "_COINGECKO_KEY", "test-key")
    yield
    trading._price_cache.clear()


def _breaker_open(monkeypatch) -> None:
    """把闸门的熔断打开 —— 之后每一条 CoinGecko 请求都拿到**合成 503**。

    这是闸门最诚实的拒绝方式:`admit()` 先看熔断再��预算
    (`cg_guard.py:382`),熔断开着时 `request()` 直接返回 `denied_response(...)`
    —— 一个带 `request=` 的 503,正文是
    `{"error": "coingecko_guard", "reason": "breaker_open:cooldown"}`。
    """
    monkeypatch.setattr(cg_guard, "_local_breaker_until", time.time() + 300)


def _mock_cg(monkeypatch, handler) -> list:
    """让 trading 里的 `GuardedCGClient` 用 MockTransport —— 不打真网络,并记录请求。"""
    seen: list = []

    def _wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return handler(request)

    def factory(**kwargs):
        kwargs.pop("transport", None)
        return GuardedCGClient(transport=httpx.MockTransport(_wrapped), **kwargs)

    monkeypatch.setattr(trading, "GuardedCGClient", factory)
    return seen


def _position(**over) -> dict:
    """一个 LONG 仓位,止损/止盈**故意**落在开仓价两侧。

    `entry=100, sl=105, tp=95` ⇒ 旧的「回落开仓价」写法会同时触发 SL 和 TP。
    这不是随意的数字:它是「假止损真的会发生」的最小复现。
    """
    pos = {
        "order_id": "o1",
        "symbol": "BTC",
        "side": "LONG",
        "qty": 1.0,
        "entry_price": 100.0,
        "size_usd": 100.0,
        "status": "open",
        "opened_at": "2026-11-01T00:00:00+00:00",
        "stop_loss": 105.0,
        "take_profit": 95.0,
        "cis_score": 80,
        "cis_grade": "A",
    }
    pos.update(over)
    return pos


def _stub_store(monkeypatch, positions: dict) -> dict:
    """把 Redis 换成内存字典。返回的 dict 用来断言「有没有被写回去」。"""
    saved: dict = {}

    async def _get_positions():
        return {k: dict(v) for k, v in positions.items()}

    async def _save_positions(pos):
        saved.clear()
        saved.update({k: dict(v) for k, v in pos.items()})

    async def _get_balance():
        return 10_000.0

    monkeypatch.setattr(trading, "_get_positions", _get_positions)
    monkeypatch.setattr(trading, "_save_positions", _save_positions)
    monkeypatch.setattr(trading, "_get_balance", _get_balance)
    return saved


# ── ① 拿不到价 ⇒ 三个字段是 None,不是 0 ──────────────────────────────────────

def test_闸门拒了_当前价是None_不是开仓价(monkeypatch):
    """合成 503(闸门拒了)⇒ `current_price is None`,**不是** `entry_price`。

    这条是整个阶段的锚:回落开仓价 = PnL 恒等于 0 = 与「仓位真的平了」同形。
    """
    _breaker_open(monkeypatch)
    _stub_store(monkeypatch, {"o1": _position()})
    seen = _mock_cg(monkeypatch, lambda req: httpx.Response(200, json={}))

    resp = asyncio.run(trading.get_positions())

    assert not seen, "闸门拒了之后**不该**有任何外部请求发出去"
    pos = resp["positions"][0]
    assert pos["current_price"] is None, "拿不到价却报了一个价 —— 那是编的"
    assert pos["unrealized_pnl"] is None, "没有价格 ⇒ P&L 未测量 ⇒ 必须是 None"
    assert pos["unrealized_pct"] is None
    assert pos["price_source"] == "unavailable"
    # NAV 仍按开仓价计入(保守估值,账面不因一次取价失败而缩水)——
    # 但**账面口径必须写明**,否则下一位读数的人以为那是标记价。
    assert pos["current_value_basis"] == "entry_price"
    assert pos["current_value_usd"] == 100.0
    assert resp["price_coverage"]["priced_positions"] == 0
    assert resp["price_coverage"]["unpriced_positions"] == 1
    assert resp["price_coverage"]["unpriced_symbols"] == ["BTC"]


def test_上游真503_跟闸门拒绝一样处理(monkeypatch):
    """真 503(上游挂了)⇒ 跟合成 503 **同一种**降级:没有价,不是假价。

    两种 503 走的是同一条分支 —— 这正是「合成 503 带 `request=`」这个设计的
    意义:既有 `except` 分支一个字都不用改,降级语义也不会分叉。
    """
    _stub_store(monkeypatch, {"o1": _position()})
    _mock_cg(monkeypatch, lambda req: httpx.Response(503, json={"error": "upstream down"}))

    resp = asyncio.run(trading.get_positions())

    pos = resp["positions"][0]
    assert pos["current_price"] is None
    assert pos["unrealized_pnl"] is None
    assert pos["price_source"] == "unavailable"
    assert resp["price_coverage"]["unpriced_positions"] == 1


def test_拿得到价的时候_照常报数(monkeypatch):
    """**反向验收**:闸门开着的时候一切照旧 —— 否则这条测试只是在测「都返回 None」。

    闸门开着 + 上游 200 + 真实价 ⇒ P&L 有值、来源标注合法。
    """
    _breaker_open(monkeypatch)
    _stub_store(monkeypatch, {"o1": _position()})
    _mock_cg(monkeypatch, lambda req: httpx.Response(
        200, json={"bitcoin": {"usd": 110.0}}))

    # 熔断开着 ⇒ 请求拿不到价。把熔断关掉,让上游真的答。
    monkeypatch.setattr(cg_guard, "_local_breaker_until", 0.0)

    resp = asyncio.run(trading.get_positions())

    pos = resp["positions"][0]
    assert pos["current_price"] == 110.0
    assert pos["unrealized_pnl"] == 10.0
    assert pos["unrealized_pct"] == pytest.approx(10.0)
    assert pos["price_source"] in ("coingecko_pro", "coingecko_public")
    assert pos["current_value_basis"] == "mark_price"
    assert resp["price_coverage"]["priced_positions"] == 1
    assert resp["price_coverage"]["unpriced_positions"] == 0


# ── ② SL/TP 不触发 ────────────────────────────────────────────────────────────

def test_没有标记价_SL_TP不置flag(monkeypatch):
    """开仓价落在止损位之内 ⇒ 旧的回落写法会置 `sl_triggered`。

    置 flag 本身就会让前端把这一行染成红色并打上「SL hit」——
    **一个从来没发生过的事件**,被渲染成发生了。
    """
    _breaker_open(monkeypatch)
    _stub_store(monkeypatch, {"o1": _position()})
    _mock_cg(monkeypatch, lambda req: httpx.Response(200, json={}))

    resp = asyncio.run(trading.get_positions())

    pos = resp["positions"][0]
    assert not pos.get("sl_triggered"), "没有价格却报了止损 —— 那是用开仓价编的"
    assert not pos.get("tp_triggered"), "没有价格却报了止盈 —— 那是用开仓价编的"


def test_没有标记价_SLTP循环不平仓(monkeypatch):
    """**平仓比 flag 更贵**:平仓会写 `trade_results` ⇒ 一个假样本进 Learn 循环。

    `_sl_tp_exit` 必须:这一轮**不评估**这个仓位,并如实报出
    「有几个没评估」(`unpriced`)—— 不评估和「评估了但没触发」是两件事。
    """
    _breaker_open(monkeypatch)
    saved = _stub_store(monkeypatch, {"o1": _position()})
    _mock_cg(monkeypatch, lambda req: httpx.Response(200, json={}))

    out = asyncio.run(trading._sl_tp_exit())

    assert out["closed"] == 0, "没有标记价却平了仓"
    assert out["sl"] == 0 and out["tp"] == 0
    assert out["unpriced"] == 1, "没评估的仓位必须**报出来**,不能静默"
    assert "o1" not in saved or saved["o1"]["status"] == "open", "仓位被平了"
    assert "o1" not in saved or "exit_price" not in saved["o1"], "写了一个没成交过的出场价"


def test_手动平仓_拿不到价就拒绝(monkeypatch):
    """手动平仓没有标记价 ⇒ **拒绝**(503),不拿开仓价成交。

    拿开仓价成交 ⇒ 写进 `trade_results` 的已实现盈亏是**编出来的**。
    """
    _breaker_open(monkeypatch)
    _stub_store(monkeypatch, {"o1": _position()})
    _mock_cg(monkeypatch, lambda req: httpx.Response(200, json={}))

    with pytest.raises(Exception) as exc:
        asyncio.run(trading.close_position("o1"))

    status = getattr(exc.value, "status_code", None)
    assert status == 503, f"拿不到标记价却平了仓(status={status})"


# ── ③ 函数层缓存:同一批 symbol 只打一次 ──────────────────────────────────────

def test_同一symbol集合连打两次_只发一次外部请求(monkeypatch):
    """两条后台循环(`_sl_tp_loop` / `_cis_flip_loop`)故意错开 60 秒,问的是同一个问题。

    90 秒 TTL 让后一条命中前一条的缓存 ⇒ 每 5 分钟只打一次。
    缓存键是 **symbol**,不是「请求批次」—— 因为问价有两种形状
    (批量 / 单个),按批缓存的话这两种问法互相看不见,去重就是空话。
    """
    seen = _mock_cg(monkeypatch, lambda req: httpx.Response(
        200, json={"bitcoin": {"usd": 60000.0}, "ethereum": {"usd": 3000.0}}))

    first = asyncio.run(trading._fetch_prices_batch(["BTC", "ETH"]))
    second = asyncio.run(trading._fetch_prices_batch(["BTC", "ETH"]))

    assert first["BTC"] == 60000.0 and second["BTC"] == 60000.0
    assert first["ETH"] == 3000.0 and second["ETH"] == 3000.0
    assert len(seen) == 1, "第二遍应该命中缓存,不该再发请求"


def test_缓存只存成功的价_失败不缓存(monkeypatch):
    """闸门关掉之后**不能**连续 90 秒吐一个不存在的价。

    失败不缓存 ⇒ 闸门一恢复就能立刻拿到真价。
    """
    seen = _mock_cg(monkeypatch, lambda req: httpx.Response(503, json={"error": "x"}))
    first = asyncio.run(trading._fetch_prices_batch(["BTC"]))
    assert first == {}, "503 不该返回任何价"

    # 缓存里不能有 BTC —— 否则闸门恢复后 90 秒内还是「没有价」。
    assert trading._price_cache_get("BTC") is None


def test_单问与批问看得见彼此的缓存(monkeypatch):
    """`_fetch_price`(单个)与 `_fetch_prices_cg_batch`(一批)共用同一份缓存。

    这是「键 = symbol」的直接后果,也是它值得单独测的理由:
    两种问法如果各存各的,去重就只做了一半。
    """
    seen = _mock_cg(monkeypatch, lambda req: httpx.Response(
        200, json={"bitcoin": {"usd": 60000.0}}))

    asyncio.run(trading._fetch_price("BTC"))
    asyncio.run(trading._fetch_prices_cg_batch(["BTC"]))

    assert len(seen) == 1, "单问打了一次,批问又打了一次 —— 缓存没跨形状生效"


# ── ④ 前端:null ⇒「—」,而 0 仍然是「+0.00」 ─────────────────────────────────

_SAFEFORMAT_URL = (ROOT / "dashboard" / "src" / "lib" / "safeFormat.js").as_uri()

_JS = r"""
import('__SAFEFORMAT_URL__')
  .then(async (m) => {
    const { fmtSignedPnl } = m;
    const fails = [];

    // 未测量 ⇒ 「—」。不是 "+0.00"、不是 "0.00"。
    const mustBeDash = [
      ["null",         fmtSignedPnl(null, null),       "—"],
      ["undefined",    fmtSignedPnl(undefined, undefined), "—"],
      ["NaN",          fmtSignedPnl(NaN, NaN),         "—"],
      ["null pnl + pct", fmtSignedPnl(null, 3.2),      "—"],
      ["string pnl",   fmtSignedPnl("1.0", 1.0),        "—"],
    ];
    for (const [label, got, want] of mustBeDash) {
      if (got !== want) fails.push(`fmtSignedPnl(${label}) = ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
    }

    // **真的 0 仍然是 0** —— 这是最容易翻车的一条:
    // 修「null 塌成 0」时把 0 也当成缺失 ⇒ 「盈亏正好为零」显示成「没测量」。
    const mustBeNumber = [
      ["zero pnl + zero pct", fmtSignedPnl(0, 0),        "+0.00 (+0.00%)"],
      ["zero pnl",            fmtSignedPnl(0, null),     "+0.00"],
      ["positive",            fmtSignedPnl(12.345, 1.234), "+12.35 (+1.23%)"],
      ["negative",            fmtSignedPnl(-3.2, -0.5),  "-3.20 (-0.50%)"],
      ["no pct",              fmtSignedPnl(5, undefined), "+5.00"],
    ];
    for (const [label, got, want] of mustBeNumber) {
      if (got !== want) fails.push(`fmtSignedPnl(${label}) = ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
    }

    if (fails.length) {
      for (const f of fails) console.error("  ✗ " + f);
      process.exit(1);
    }
    console.log("  ✓ 未测量的 P&L 渲染「—」(不是 +0.00)");
    console.log("  ✓ 真的 0 仍然渲染「+0.00」(0 是数据,不是缺失)");
  })
  .catch((e) => { console.error("load failed:", e); process.exit(2); });
"""


def test_前端_null渲染成破折号_而0仍然是0():
    """前端运行时验收(照 `tests/test_safe_format_score.py` 的形状跑 node)。"""
    proc = subprocess.run(
        ["node", "--input-type=module", "-e",
         _JS.replace("__SAFEFORMAT_URL__", _SAFEFORMAT_URL)],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        print(proc.stdout, end="")
        print(proc.stderr, file=sys.stderr, end="")
        raise AssertionError(
            "fmtSignedPnl() 违反了 null-safe 契约 —— 见上。"
            "前端把「没测量」渲染成「+0.00」= 一份「没有价格」的报告"
            "跟一份「仓位真的平了」的报告长得一样(S-262 家族)。"
        )
    print(proc.stdout, end="")


def test_QuantMonitor不再把null塌成0():
    """静态守卫:组件里不许再出现 `(pos.unrealized_pnl || 0)` 这种塌缩。

    回归测试必须抓住**当初造成 bug 的那个字面量** —— 抓不到就等于没测。
    """
    src = (ROOT / "dashboard" / "src" / "components" / "QuantMonitor.jsx").read_text(encoding="utf-8")
    bad = []
    for i, line in enumerate(src.splitlines(), 1):
        stripped = line.split("//", 1)[0]
        for pat in ("(pos.unrealized_pnl || 0)", "(pos.unrealized_pct || 0)",
                    "pos.unrealized_pnl ?? 0", "pos.unrealized_pct ?? 0"):
            if pat in stripped:
                bad.append(f"line {i}: {line.strip()!r}")
    assert not bad, (
        "QuantMonitor.jsx 又把未测量的 P&L 塌成了 0 —— S-895 阶段 1 回归了:\n  "
        + "\n  ".join(bad)
    )


if __name__ == "__main__":
    fails = 0
    for fn in (test_闸门拒了_当前价是None_不是开仓价,
               test_上游真503_跟闸门拒绝一样处理,
               test_拿得到价的时候_照常报数,
               test_没有标记价_SL_TP不置flag,
               test_没有标记价_SLTP循环不平仓,
               test_手动平仓_拿不到价就拒绝,
               test_同一symbol集合连打两次_只发一次外部请求,
               test_缓存只存成功的价_失败不缓存,
               test_单问与批问看得见彼此的缓存,
               test_前端_null渲染成破折号_而0仍然是0,
               test_QuantMonitor不再把null塌成0):
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"  ✗ {fn.__name__}\n    {e}")
    print(f"\n{'✅' if not fails else '🔴'} 交易降级语义 — {fails} failing")
    sys.exit(1 if fails else 0)
