"""决策流落库循环的守卫 (S-292)。

Jazz:「我们建了那么多东西,必须要连通呀,现在就像买了显卡、存储、网卡,
但是服务器不是连通的。」

所以本文件断言的不是「循环能跑」,而是**它插进了四个面**:

    loop_beat (S-282)           失败要落到可查询的地方
    producer_freshness (S-278)  表要被判活
    watch_census (S-279)        表要进覆盖清册
    Supabase                    数据要真的落地

`signal_outcomes` 死 123 天是「循环有了但心跳没接」;
`market_state_vectors` 停 27 天是「写了一次但从没上日程」。**两个前车都在隔壁。**

## 实跑发现的那条(2026-09-04)

    BTC   按家数 19.4%  ·  **按持仓 87.0%**
    ETH   按家数 61.8%  ·  **按持仓 22.9%**   ← 最大的 BitMine 解析不出来

**ETH 看家数还行、看持仓很糟。** 只报一个口径,这个洞看不见。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.entity.writer import (                            # noqa: E402
    COINS, LOOP_NAME, MAX_ENTITIES_PER_RUN, _cg_headers, run_once,
)

_FAIL: list = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}" + (f"\n      {detail}" if not ok else ""))
    if not ok:
        _FAIL.append(f"{label}{(' — ' + detail) if detail else ''}")


class _Resp:
    def __init__(self, code, body): self.status_code, self._b = code, body
    def json(self): return self._b


class _Client:
    """假 CG。**大持仓解析得出、小持仓解析不出** —— 实测的真实分布。"""
    def __init__(self):
        self.calls = []

    async def get(self, url, params=None):
        self.calls.append(url)
        if "companies/public_treasury" in url:
            return _Resp(200, {"companies": [
                {"name": "Strategy", "symbol": "MSTR", "total_holdings": 845050},
                {"name": "MARA Holdings", "symbol": "MARA", "total_holdings": 35303},
            ]})
        if url.endswith("/public_treasury/strategy"):
            return _Resp(200, {"id": "strategy"})
        if "transaction_history" in url:
            pg = (params or {}).get("page", 1)
            if pg > 1:
                return _Resp(200, {"transactions": []})
            return _Resp(200, {"transactions": [{
                "date": 1597104000000, "source_url": "https://x/8-k.pdf",
                "coin_id": "bitcoin", "type": "buy", "holding_net_change": 21454.0,
                "transaction_value_usd": 250000000.0, "holding_balance": 21454.0,
                "average_entry_value_usd": 11652.0}]})
        return _Resp(404, {})


def _run(**kw):
    written = []

    async def q(table, cols):
        return kw.get("known", [])

    async def up(table, rows, oc):
        written.append((table, len(rows)))
        return True

    res = asyncio.run(run_once(client=kw.get("client") or _Client(),
                               supabase_query=q, supabase_upsert=up,
                               today="2026-09-04"))
    return res, written


def t_the_loop_is_wired_into_all_four_surfaces():
    """**本文件的理由。** 一块没连线的卡和没买这块卡是一样的。"""
    main = (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    _check("① 循环存在", "async def _treasury_decisions_loop" in main)
    _check("① 且被 create_task 调度",
           "_asyncio.create_task(_treasury_decisions_loop())" in main)
    _check("② 心跳接了(成功与失败两条路都接)",
           main.count(f'_beat("{LOOP_NAME}"') >= 2,
           f"只找到 {main.count(chr(34) + LOOP_NAME + chr(34))} 处")

    from src.data.market.producer_freshness import EXPECTED
    _check("③ 表在判活清单里", "treasury_decisions" in EXPECTED)
    spec = EXPECTED.get("treasury_decisions")
    _check("③ 且两个时钟都声明了",
           spec and spec.write_col and spec.event_col,
           str(spec))
    _check("③ 死亡线放宽到 21 天(企业不是每天买)",
           spec and spec.dead_after_days >= 14, str(spec.dead_after_days if spec else None))

    from src.data.market.watch_census import COVERAGE
    _check("④ 表在覆盖清册里", "treasury_decisions" in COVERAGE)
    _check("④ 实体表也在", "treasury_entities" in COVERAGE)


def t_user_agent_is_not_optional():
    """裸客户端被 Cloudflare 1010 拦成 403,而 403 会被读成「没有这个能力」。"""
    import os
    os.environ["COINGECKO_API_KEY"] = "test-key"
    h = _cg_headers()
    _check("带 User-Agent", "User-Agent" in h, str(sorted(h)))
    _check("带 pro key 头", "x-cg-pro-api-key" in h)
    os.environ.pop("COINGECKO_API_KEY")
    _check("无 key 时返回空头(不伪造)", _cg_headers() == {})


def t_known_entities_are_not_reprobed():
    """解析结果几乎不变;每天重探 180 家是每月一万次额度。"""
    c = _Client()
    _run(client=c, known=[{"entity_id": "strategy", "name": "Strategy"}])
    probes = [u for u in c.calls
              if u.endswith("/public_treasury/strategy")]
    _check("已知实体不再被 probe", not probes,
           f"仍探了 {len(probes)} 次")

    c2 = _Client()
    _run(client=c2, known=[])
    _check("未知实体会被 probe",
           any(u.endswith("/public_treasury/strategy") for u in c2.calls))


def t_unresolved_entities_are_returned_not_dropped():
    res, _ = _run(known=[])
    btc = res["coins"].get("bitcoin") or {}
    names = {u["name"] for u in btc.get("unresolved", [])}
    _check("未解析的被带出来", "MARA Holdings" in names, str(names))
    _check("并带持仓(说明代价)",
           all(u["holdings"] > 0 for u in btc.get("unresolved", [])))
    _check("两个覆盖率口径都在",
           {"coverage_by_count", "coverage_by_holdings"} <= set(btc.get("resolution", {})),
           str(btc.get("resolution")))


def t_zero_written_is_legal_and_says_so():
    """企业不是每天买 —— 0 条不是故障。**陈旧由事件时钟判,不由这里判。**"""
    class _Empty(_Client):
        async def get(self, url, params=None):
            if "transaction_history" in url:
                return _Resp(200, {"transactions": []})
            return await super().get(url, params)

    res, written = _run(client=_Empty(), known=[])
    _check("0 条时不报错", res["n_written"] == 0, str(res["n_written"]))
    _check("reason 写明 0 条合法", "0 条是合法的" in res["reason"], res["reason"][:80])
    _check("并指向事件时钟才是陈旧判据", "事件时钟" in res["reason"])


def t_batch_cap_exists():
    _check(f"每轮上限 {MAX_ENTITIES_PER_RUN} 存在且合理",
           0 < MAX_ENTITIES_PER_RUN <= 200, str(MAX_ENTITIES_PER_RUN))
    _check("两个 coin 都跑", set(COINS) == {"bitcoin", "ethereum"}, str(COINS))


def main() -> int:
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("t_")]:
        print(f"\n▸ {fn.__name__}")
        fn()
    print("\n" + ("✓ 全部通过" if not _FAIL else f"✗ {len(_FAIL)} 条失败"))
    for f in _FAIL:
        print("   " + f)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
