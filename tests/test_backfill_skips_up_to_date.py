"""S-895 阶段 3 —— 面板回填**按覆盖差驱动**:够新就不打外网。

## 这个测试在防什么

改之前的 `_cg_panel_loop` 是**轮询式**的:每 6 小时把同一批标的的同一个
60 天窗口重打一遍,**不问「库里已经有什么」**。一天 4 轮 × 59 对 ≈ 236 次
/ohlc/range;失败时 10 分钟一轮 ⇒ 144 轮 × 59 ≈ **8,500 次/天** ——
那正是「额度超支」的形状,而超支的部分**全花在重复的数据上**。

## 五条判据,各自独立

① **纯函数**:缺哪些日子(`missing_days`)—— 判据从 IO 里拿出来,单独能测。
   ⚠️ 判据是**逐日集合**,不是 `max(trade_date)`:一次失败留一个洞,
   而洞在前沿上完全不可见(S-190 那次的形状)。

② **集成**:库里已够新 ⇒ `run_once` **一次 /ohlc/range 都不打**。
   ⚠️ 断言的是**回填**这一段:解析阶段(/coins/list + /coins/markets)
   是**另一个职责** —— 面板里有 203 个标的解析不出来,所以每一轮都还要付那 5 次。
   本文件把这条边界也断言出来(哪些端点被打了),免得「省了额度」这句话
   有一天变成一句自我安慰。

③ **对拍**:判据给出的「缺的日子」必须**恰好等于**一次全量抓取会新增的日子。
   差一个,就是漏补或多补 —— 而少补的数据在 `max(trade_date)` 上完全不可见。

④ **退避阶梯**:失败一次就 10 分钟后重打 = 用 36 倍的额度问同一个
   不会变的问题。阶梯必须指数增长、必须封顶在成功间隔上。

⑤ **左端裁剪的依据**:窗口最左边那天算不算洞,取决于**它那时候存在吗**。
   依据是**并集的最早一天**(`deepest_start`),不是自己那个源 ——
   按自己那个源裁 ⇒ 老标的左端的洞**永远看不见**(少补);
   不裁 ⇒ 新上市的标的每轮都白打(多打)。**读不到这个答案 ⇒ 不裁剪**,
   宁可多打一次,不可少补一天(S-180)。
"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.data.market.cg_pro_backfill import (                    # noqa: E402
    BackfillResult, SymbolResult)
from src.data.market.cg_panel_sync import (                       # noqa: E402
    BACKFILL_LOOKBACK_DAYS, missing_days, run_once)
from src.data.market.cg_universe import FROM_DB                   # noqa: E402

_FAILURES: list[str] = []

#: 固定的「今天」—— 判据不该依赖跑测试的那一天。
TODAY = "2026-11-19"
START = (dt.date.fromisoformat(TODAY)
         - dt.timedelta(days=BACKFILL_LOOKBACK_DAYS)).isoformat()

#: 面板里的标的「早就存在」时,并集里最早的那一天(默认夹具)。
OLD = "2020-01-01"


def _check(label: str, ok: bool, detail: str = "") -> None:
    """**失败就抛** —— 软失败(只记不抛)会让 pytest 永远绿。

    上一版这个文件用「记进 list 就完事」的写法,pytest 报 `12 passed`,
    而独立 runner 报 2 个失败 —— **绿色的门挡不住任何东西**。
    """
    if ok:
        print(f"  ✓ {label}")
        return
    _FAILURES.append(label)
    print(f"  ✗ {label}\n      {detail}")
    raise AssertionError(f"{label} — {detail}")


def _window_days() -> list[str]:
    """这个循环要抓的那个窗口,逐日。"""
    _s = dt.date.fromisoformat(START)
    _e = dt.date.fromisoformat(TODAY)
    return [(_s + dt.timedelta(days=i)).isoformat()
            for i in range((_e - _s).days + 1)]


# ── 假件:不打网络、不写库 ──────────────────────────────────────────────────

class _FakeResp:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        # S-895 阶段 5:共享取数口(`get_cg_coin_list`)用的是 `raise_for_status()`。
        if self.status_code != 200:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    """只记录被打了哪些端点。**不打网络。**"""

    def __init__(self):
        self.urls: list[str] = []

    async def get(self, url, params=None, **kw):
        # `**kw`:S-895 阶段 5 起,`/coins/list` 走共享取数口
        # (`data_layer.get_cg_coin_list`),它会多传 `headers` / `timeout`。
        self.urls.append(url)
        return _FakeResp(200, [])


#: 本轮 `_run` 用的假 client(共享取数口也要用它 —— 见下面的 fixture)。
_CURRENT_FAKE: list[_FakeClient] = []


@pytest.fixture(autouse=True)
def _shared_path_never_touches_the_network(monkeypatch):
    """S-895 阶段 5:`/coins/list` 走**共享取数口**(`data_layer.get_cg_coin_list`)
    ⇒ 它用的是 `data_layer` 自己的 client,不再是被注入的那个。

    ⇒ 这条 fixture 把 data_layer 的 client 工厂换成本轮的假 client,并清掉
    那条路径的进程内缓存 —— 否则:①测试会**真的打 CoinGecko**;②第一个测试
    把结果缓存下来,后面的测试就看不到那次调用了(「5 次外呼」会变成「4 次」)。

    ⚠ 这个 fixture 是**阶段 5 的证据**:解析阶段那 5 次外呼一次都没少,只是
    其中 1 次换了个地方打。
    """
    import src.data.market.data_layer as dl
    for k in ("cg_coin_list_plat", "cg_coin_list_plat__neg"):
        dl._cache.pop(k, None)
    monkeypatch.setattr(dl, "_get_cg_client",
                        lambda: _CURRENT_FAKE[-1] if _CURRENT_FAKE else _FakeClient())
    yield
    for k in ("cg_coin_list_plat", "cg_coin_list_plat__neg"):
        dl._cache.pop(k, None)


def _mk_query(known_rows):
    async def _q(table, cols):
        return list(known_rows)
    return _q


async def _up(table, rows, on_conflict):
    return True


#: `cg_coin_map` 里已解析的映射。**默认只有 BTC** ——
#: 回填的候选集是**整张 `cg_coin_map`**(不只是面板),所以往这里加一个符号,
#: 它就会出现在每一轮的回填对里。
_KNOWN = [{"symbol": "BTC", "coin_id": "bitcoin", "resolved_from": FROM_DB,
           "verified_at": "2026-01-01T00:00:00Z", "asset_class": "Crypto"}]

_KNOWN_BTC_ETH = _KNOWN + [{"symbol": "ETH", "coin_id": "ethereum",
                             "resolved_from": FROM_DB,
                             "verified_at": "2026-01-01T00:00:00Z",
                             "asset_class": "Crypto"}]


async def _run(panel, coverage, *, coverage_reader=None, union_reader=None,
               known=None, inject_readers=True):
    """跑一轮 `run_once`。返回 (结果, 回填调用记录, 打过的端点)。

    `inject_readers=False` ⇒ **不传判据**,测 `run_once` 的默认形状。
    """
    from src.data.market import cg_pro_backfill

    calls: list[list[tuple[str, str]]] = []

    async def _fake_backfill(pairs, *, start, end, dest="local", asset_class=None,
                             min_candles=None, vendor_paired=None, dry_run=False):
        calls.append(list(pairs))
        _days = ((end - start).days + 1)
        _per = tuple(SymbolResult(s, c, True, _days) for s, c in pairs)
        return BackfillResult(True, _days * len(pairs), _per, "", dest)

    _orig = cg_pro_backfill.backfill
    cg_pro_backfill.backfill = _fake_backfill
    _client = _FakeClient()
    _CURRENT_FAKE.append(_client)
    try:
        if not inject_readers:
            res = await run_once(client=_client,
                                 supabase_query=_mk_query(
                                     known if known is not None else _KNOWN),
                                 supabase_upsert=_up,
                                 panel_symbols=list(panel),
                                 today=TODAY)
        else:
            if coverage_reader is None:
                async def coverage_reader(_syms, _s, _e):
                    return coverage
            if union_reader is None:
                async def union_reader(_syms):
                    # 默认:面板里的标的都「早就存在」⇒ 左端不裁剪。
                    return {str(s).upper(): OLD for s in _syms}
            res = await run_once(client=_client,
                                 supabase_query=_mk_query(
                                     known if known is not None else _KNOWN),
                                 supabase_upsert=_up,
                                 panel_symbols=list(panel),
                                 today=TODAY,
                                 coverage_reader=coverage_reader,
                                 union_reader=union_reader)
    finally:
        cg_pro_backfill.backfill = _orig
    return res, calls, _client.urls


# ── ① 纯函数:缺哪些日子 ────────────────────────────────────────────────────

def test_missing_days_is_a_per_day_set_not_a_frontier():
    """⚠️ **判据是逐日集合,不是 `max(trade_date)`。**

    一次失败留一个洞,而洞在前沿上完全不可见(S-190 那次的形状):
    「最新那根是今天」和「今天往前有一天空缺」在 max 上完全同形。
    """
    _s = dt.date(2026, 10, 1)
    _e = dt.date(2026, 10, 10)
    _full = {(_s + dt.timedelta(days=i)).isoformat() for i in range(10)}

    _check("全覆盖 ⇒ 没有缺的日子",
           missing_days(_full, _s, _e) == [], str(missing_days(_full, _s, _e)))

    _hole = _full - {"2026-10-05"}
    _check("中间一个洞 ⇒ 那个日子",
           missing_days(_hole, _s, _e) == ["2026-10-05"],
           str(missing_days(_hole, _s, _e)))

    _front = _full - {"2026-10-01"}
    _check("洞在窗口最前面 ⇒ 也要能看见(**不知道它那时候存不存在,就不裁**)",
           missing_days(_front, _s, _e) == ["2026-10-01"],
           str(missing_days(_front, _s, _e)))

    _tail = _full - {"2026-10-10"}
    _check("洞在最后一天 ⇒ 也要能看见",
           missing_days(_tail, _s, _e) == ["2026-10-10"],
           str(missing_days(_tail, _s, _e)))


def test_empty_coverage_means_the_whole_window_is_missing():
    _s = dt.date(2026, 10, 1)
    _e = dt.date(2026, 10, 3)
    _check("一条都没有 ⇒ 整个窗口都缺",
           missing_days(set(), _s, _e) == ["2026-10-01", "2026-10-02", "2026-10-03"],
           str(missing_days(set(), _s, _e)))


def test_young_symbol_is_not_permanently_in_gap():
    """**上市前的日子不是缺口** —— 但依据是「并集里最早的那一天」。

    `known_first` = 它在任何源里最早的那一天。它落在窗口之内 ⇒
    那时候它还没上市 ⇒ 上市前的日子**没有 bar**,不是洞。
    """
    _s = dt.date(2026, 10, 1)
    _e = dt.date(2026, 10, 10)
    _listing = "2026-10-06"
    _young = {"2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09", "2026-10-10"}
    _check("上市前的日子不算缺口",
           missing_days(_young, _s, _e, known_first=_listing) == [],
           str(missing_days(_young, _s, _e, known_first=_listing)))
    _check("上市**之后**的洞仍然是洞",
           missing_days(_young - {"2026-10-08"}, _s, _e,
                        known_first=_listing) == ["2026-10-08"],
           str(missing_days(_young - {"2026-10-08"}, _s, _e,
                            known_first=_listing)))


def test_unknown_listing_date_means_no_clipping():
    """**读不到「它那时候存在吗」⇒ 不裁剪。**

    宁可多打一次,不可少补一天(S-180)。少补的数据在 `max(trade_date)`
    上完全不可见 —— 那是最难被发现的一种少补。
    """
    _s = dt.date(2026, 10, 1)
    _e = dt.date(2026, 10, 10)
    _young = {"2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09", "2026-10-10"}
    _judged = missing_days(_young, _s, _e)
    _check("不知道 ⇒ 上市前的日子也当成缺(宁可多打)",
           _judged == ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04",
                       "2026-10-05"], str(_judged))


# ── ③ 对拍:判据 == 一次全量抓取会新增的日子 ────────────────────────────────

def test_judgement_equals_exactly_what_a_fetch_would_add():
    """**差一个就是漏补或多补** —— 而少补的数据在 `max(trade_date)` 上完全不可见。

    前提:标的存在的区间是 `[known_first, end]`(它上市那天起到今天),
    库里已有的日子是 `covered`。那么一次全量抓取会**新增**的日子 =
    存在区间里、库里没有的那些 —— 判据必须**恰好**等于它。
    """
    _w = _window_days()
    _s, _e = dt.date.fromisoformat(START), dt.date.fromisoformat(TODAY)
    _fixtures = {
        "库里空的": (set(), OLD),
        "全覆盖": (set(_w), OLD),
        "中间一个洞": (set(_w) - {_w[30]}, OLD),
        "只有前半段": (set(_w[:40]), OLD),
        "只有后半段(新上市)": (set(_w[20:]), _w[20]),
        "两端各缺一天": (set(_w) - {_w[0], _w[-1]}, OLD),
        "左端一个洞(老标的)": (set(_w) - {_w[0]}, OLD),
    }
    for _label, (_cov, _kf) in _fixtures.items():
        _lo = max(_s, dt.date.fromisoformat(_kf))
        _would_add = [d for d in _w if d >= _lo.isoformat() and d not in _cov]
        _judged = missing_days(_cov, _s, _e, known_first=_kf)
        _check(f"判据 == 全量会新增的日子({_label})",
               _judged == _would_add, f"判据 {_judged} vs 全量 {_would_add}")


# ── ② 集成:够新 ⇒ 一次 /ohlc/range 都不打 ─────────────────────────────────

def test_up_to_date_panel_makes_no_ohlc_range_call():
    """库里已够新 ⇒ **0 次回填调用**。"""
    _res, _calls, _urls = asyncio.run(_run(["BTC"], {"BTC": set(_window_days())}))
    _check("0 次 /ohlc/range 调用", len(_calls) == 0, str(_calls))
    _check("status=skipped(没有差可补,不是故障)", _res["status"] == "skipped",
           str(_res.get("status")))
    _check("n_pairs=1 / n_pairs_fetched=0 / n_pairs_skipped_up_to_date=1",
           _res["n_pairs"] == 1 and _res["n_pairs_fetched"] == 0
           and _res["n_pairs_skipped_up_to_date"] == 1,
           str({k: _res.get(k) for k in ("n_pairs", "n_pairs_fetched",
                                         "n_pairs_skipped_up_to_date")}))
    _check("reason 说清了「已是最新」",
           "已是最新" in str(_res.get("reason") or ""), str(_res.get("reason")))
    _check("覆盖读成功", _res.get("coverage_read_ok") is True)


def test_a_hole_in_one_symbol_fetches_only_that_symbol():
    """**洞在谁身上就只补谁** —— 不是「有洞就全部重打」。"""
    _w = _window_days()
    _cov = {"BTC": set(_w) - {_w[30]}, "ETH": set(_w)}
    _res, _calls, _urls = asyncio.run(
        _run(["BTC", "ETH"], _cov, known=_KNOWN_BTC_ETH))
    _check("只回填有洞的那一对", _calls == [[("BTC", "bitcoin")]], str(_calls))
    _check("n_pairs_fetched=1 / n_pairs_skipped_up_to_date=1",
           _res["n_pairs_fetched"] == 1 and _res["n_pairs_skipped_up_to_date"] == 1,
           str({k: _res.get(k) for k in ("n_pairs_fetched",
                                         "n_pairs_skipped_up_to_date")}))


def test_coverage_read_failure_falls_back_to_full_backfill():
    """⚠️ **读不到 ≠ 没有数据** (S-180)。

    覆盖读失败 ⇒ **照旧全量回填**。少补数据的失败模式是**静默**的 ——
    洞在前沿上完全不可见(S-190),而「少补了」不会报错,只会让曲线慢慢歪掉。
    """
    async def _failing(_syms, _s, _e):
        return None

    _res, _calls, _urls = asyncio.run(_run(["BTC"], None, coverage_reader=_failing))
    _check("覆盖读失败 ⇒ 仍然全量回填", len(_calls) == 1, str(_calls))
    _check("coverage_read_ok=False", _res.get("coverage_read_ok") is False)
    _check("reason 明说「覆盖读失败 ⇒ 本轮全量回填」",
           "覆盖读失败" in str(_res.get("reason") or ""), str(_res.get("reason")))


def test_coverage_reader_exception_also_falls_back():
    """读的那一层自己抛异常,同样不能变成「少补」。"""
    async def _boom(_syms, _s, _e):
        raise RuntimeError("supabase 读不到")

    _res, _calls, _urls = asyncio.run(_run(["BTC"], None, coverage_reader=_boom))
    _check("读异常 ⇒ 仍然全量回填", len(_calls) == 1, str(_calls))
    _check("coverage_read_ok=False", _res.get("coverage_read_ok") is False)


def test_union_read_failure_does_not_clip():
    """⚠️ **并集深度读不到 ⇒ 不裁剪** ⇒ 宁可多打一次,不可少补一天。

    裁剪的依据是「它那时候存在吗」。这个答案读不到时,
    唯一安全的默认是「不裁剪」(把上市前的日子也当成缺)——
    代价是多打一次,而不是永远补不上一个洞。
    """
    async def _no_union(_syms):
        return None

    _w = _window_days()
    _cov = {"BTC": set(_w[20:])}          # 只覆盖后 40 天(看着像新上市)
    _res, _calls, _urls = asyncio.run(
        _run(["BTC"], _cov, union_reader=_no_union))
    _check("并集读不到 ⇒ 不跳过,仍然回填", len(_calls) == 1, str(_calls))
    _check("union_read_ok=False", _res.get("union_read_ok") is False)
    _check("reason 明说「不裁剪」",
           "不裁剪" in str(_res.get("reason") or ""), str(_res.get("reason")))


def test_full_then_incremental_write_the_same_thing():
    """**对拍**:全量那一轮写的行,增量那一轮一行都不少写。

    第一轮:库里空的 ⇒ 全量回填(1 次调用)。
    第二轮:假装第一轮写进去了 ⇒ 0 次调用,0 行。
    两轮合起来的行集合 == 全量那一轮的行集合。
    """
    _res1, _calls1, _u1 = asyncio.run(_run(["BTC"], {}))
    _check("第一轮真的回填了", len(_calls1) == 1 and _res1["rows_written"] > 0,
           str(_calls1))
    _res2, _calls2, _u2 = asyncio.run(_run(["BTC"], {"BTC": set(_window_days())}))
    _check("第二轮 0 次调用", len(_calls2) == 0, str(_calls2))
    _check("第二轮 0 行写入", _res2["rows_written"] == 0, str(_res2["rows_written"]))
    _check("两轮合起来的行数 == 全量那一轮的行数",
           _res1["rows_written"] + _res2["rows_written"] == _res1["rows_written"],
           f"{_res1['rows_written']} + {_res2['rows_written']}")


def test_resolution_calls_are_a_separate_cost_and_are_still_visible():
    """⚠️ **边界要写清楚**:省下的是**回填**那几十次,不是这一轮的全部外呼。

    面板里有 203 个标的解析不出来,所以 `/coins/list` + 4 页 `/coins/markets`
    **每一轮都还要打**。S-895 阶段 5 把 `/coins/list` 挪到了共享取数口
    (`data_layer.get_cg_coin_list`,与持有人表共用)—— **次数没变**,只是换了
    地方打;所以「省了多少」这句话的分母还是 5,一条都没少。

    把这条钉住,是为了让「省了多少」这句话永远有个分母 —— 否则它会慢慢变成
    一句自我安慰。
    """
    _res, _calls, _urls = asyncio.run(
        _run(["BTC", "NEWCOIN"], {"BTC": set(_window_days())},
             known=_KNOWN[:1]))
    _check("回填 0 次", len(_calls) == 0, str(_calls))
    _check("解析阶段的 5 次外呼**仍然发生**(这是阶段 5 的活)",
           len(_urls) == 5, str(_urls))
    _check("而且它们全是解析端点",
           all(u.endswith("/coins/list") or u.endswith("/coins/markets")
               for u in _urls), str(_urls))
    _check("calls 字段把这一轮的外呼数说出来",
           _res.get("n_calls") == 5, str(_res.get("n_calls")))


# ── ④ 退避阶梯 ──────────────────────────────────────────────────────────────

def test_failure_backoff_is_exponential_and_capped_at_the_success_interval():
    """**退避不是惩罚,是别再问同一个问题。**

    一个 6 小时内不会自己好的故障,10 分钟后问一次和 6 小时后问一次
    拿到的是同一个答案 —— 代价差 36 倍。
    """
    from src.api.main import (_CG_PANEL_BACKOFF_RED_STEPS, _CG_PANEL_BACKOFF_S,
                              _CG_PANEL_INTERVAL_S, _cg_panel_backoff_s)

    _check("阶梯单调不减",
           all(_CG_PANEL_BACKOFF_S[i] < _CG_PANEL_BACKOFF_S[i + 1]
               for i in range(len(_CG_PANEL_BACKOFF_S) - 1)),
           str(_CG_PANEL_BACKOFF_S))
    _check("封顶 == 成功间隔(退到封顶就不再比正常轮更频繁)",
           _CG_PANEL_BACKOFF_S[-1] == _CG_PANEL_INTERVAL_S,
           f"{_CG_PANEL_BACKOFF_S[-1]} vs {_CG_PANEL_INTERVAL_S}")
    _check("第一级仍是 600 秒(S-323l:瞬时故障要快重试)",
           _cg_panel_backoff_s(1) == 600, str(_cg_panel_backoff_s(1)))
    _check("第 2/3/4 级是 1200/2400/4800",
           (_cg_panel_backoff_s(2), _cg_panel_backoff_s(3), _cg_panel_backoff_s(4))
           == (1200, 2400, 4800),
           str([_cg_panel_backoff_s(n) for n in (2, 3, 4)]))
    _check("再往后封顶,不越封顶",
           all(_cg_panel_backoff_s(n) == _CG_PANEL_INTERVAL_S
               for n in range(6, 40)),
           str([_cg_panel_backoff_s(n) for n in (6, 7, 20)]))
    _check("显式报红的门槛 ≤ 阶梯长度(报红一定进得了封顶那一档)",
           _CG_PANEL_BACKOFF_RED_STEPS <= len(_CG_PANEL_BACKOFF_S),
           f"{_CG_PANEL_BACKOFF_RED_STEPS} vs {len(_CG_PANEL_BACKOFF_S)}")
    _check("失败一天的轮数从 144 降到个位数~十几",
           sum(1 for _ in range(1, 40)
               if _cg_panel_backoff_s(_) <= 3600) <= 12,
           str([_cg_panel_backoff_s(n) for n in range(1, 10)]))


# ── ⑤ 左端的洞:老标的看得见,新标的不是洞 ──────────────────────────────────

def test_left_edge_hole_is_visible_for_an_asset_that_existed_before_the_window():
    """⚠️ **老标的左端的洞必须看得见** —— 它是洞,不是边界。

    改判据时最容易犯的错:按「自己那个源最早的一天」裁窗口 ——
    那样老标的左端的洞被裁掉,而**少补的数据在 `max(trade_date)` 上
    完全不可见**(S-190):曲线看起来完全正常,只是永远缺一天。
    """
    _w = _window_days()
    _cov = set(_w) - {_w[0]}
    _judged = missing_days(_cov, dt.date.fromisoformat(START),
                           dt.date.fromisoformat(TODAY), known_first=OLD)
    _check("它 2020 年就存在 ⇒ 左端少的那天是洞",
           _judged == [_w[0]], str(_judged))

    _res, _calls, _urls = asyncio.run(
        _run(["BTC"], {"BTC": _cov}))
    _check("⇒ 这一轮会回填它(洞被补上)", len(_calls) == 1, str(_calls))


# ── ⑥ 默认形状:没有判据 ⇒ 全量回填(不读库) ───────────────────────────────

def test_without_readers_it_does_not_read_the_database_and_falls_back():
    """⚠️ **默认不是「去读库」,是「没有判据」⇒ 照旧全量回填。**

    首版默认去读库,于是函数的结果开始依赖**线上库当时的内容**。
    实测(11-20):`tests/test_cg_coin_map_manual_is_sticky.py` 里一个既有测试
    **单独跑绿、批量跑红** —— 批量跑时线上库里 BTC 的窗口已经够新,
    于是被正确地跳过 ⇒ 「`seen["pairs"]` 这个键根本没出现」。

    那个断言**没有错**(它测的是 `vendor_paired` 的语义),
    错的是**它被一个它没声明的输入改变了含义**。
    ⇒ 读不读库必须是**调用方显式声明**的事。
    """
    _res, _calls, _urls = asyncio.run(
        _run(["BTC"], {"BTC": set(_window_days())}, inject_readers=False))
    _check("没给判据 ⇒ 照旧全量回填(不是跳过)", len(_calls) == 1, str(_calls))
    _check("coverage_read_ok=False(没有判据 ⇒ 没有读到)",
           _res.get("coverage_read_ok") is False)
    _check("**并且说得出「是没给」而不是「读失败」**",
           _res.get("coverage_reader_provided") is False
           and _res.get("union_reader_provided") is False,
           str({k: _res.get(k) for k in ("coverage_reader_provided",
                                         "union_reader_provided")}))
    _check("reason 里说的是「没有覆盖判据」",
           "没有覆盖判据" in str(_res.get("reason") or ""),
           str(_res.get("reason")))


def test_the_production_loop_must_pass_both_judgement_readers():
    """⚠️ **形状守卫:生产那条路必须显式传判据。**

    默认是「全量回填」(安全但费额度)。有人把生产那条路的传参删掉,
    省额度这件事会**静默消失** —— 循环照跑、心跳照绿,只是又开始
    每 6 小时重打一遍同一批标的。

    判据用 **AST**:匹配 `run_once(...)` 这个**调用**的关键字,
    不是匹配附近的字符串(`tests/_source.py`:a guard must match the
    CONSTRUCT, never a nearby string)。
    """
    import ast

    _main = _ROOT / "src/api/main.py"
    _tree = ast.parse(_main.read_text(encoding="utf-8"))
    _kw: set = set()
    _found = False
    for _fn in ast.walk(_tree):
        if isinstance(_fn, ast.AsyncFunctionDef) and _fn.name == "_cg_panel_loop":
            for _node in ast.walk(_fn):
                if (isinstance(_node, ast.Call)
                        and getattr(_node.func, "id", None) == "run_once"):
                    _found = True
                    _kw |= {k.arg for k in _node.keywords if k.arg}
    _check("找得到 `_cg_panel_loop` 里的 `run_once(...)` 调用", _found)
    _check("生产那条路传了 `coverage_reader`", "coverage_reader" in _kw, str(sorted(_kw)))
    _check("生产那条路传了 `union_reader`", "union_reader" in _kw, str(sorted(_kw)))


# ── ⑦ 右端是墙上时钟,不是库里的前沿 ────────────────────────────────────────

def test_the_window_right_edge_is_today_not_the_db_frontier():
    """⚠️ **右端取「今天」,不取「库里最新的那天」** —— 后者会让面板**冻结**。

    「库里最新的一天」不会自己往前走;而「没有洞 ⇒ 不打外网 ⇒ 库里不前进」
    是个闭环 ⇒ 面板永远停在那天,一天都不会再前进。

    ⇒ 判据的右端必须是**墙上时钟**:厂商哪天给到哪天,窗口就跟着走。
    代价是今天那根在当天第一轮还没写进去 ⇒ 它是洞 ⇒ 打一次(每天一次),
    而不是「库里全都有 ⇒ 0 次」。
    """
    _w = _window_days()
    _yesterday = _w[-2]
    _res, _calls, _urls = asyncio.run(
        _run(["BTC"], {"BTC": set(_w[:-1])}))          # 库里齐到昨天
    _check("库里齐到昨天 ⇒ 今天仍是洞 ⇒ 仍然回填(不是冻结)",
           len(_calls) == 1, str(_calls))
    _check("而窗口右端确实是今天",
           _res.get("window", "").endswith(TODAY), str(_res.get("window")))

    _res2, _calls2, _u2 = asyncio.run(
        _run(["BTC"], {"BTC": set(_w)}))                # 库里连今天都有
    _check("库里连今天都有 ⇒ 才跳过(0 次回填)",
           len(_calls2) == 0, str(_calls2))


if __name__ == "__main__":
    _ran = 0
    for _fn in list(globals().values()):
        if callable(_fn) and getattr(_fn, "__name__", "").startswith("test_"):
            print(f"\n▶ {_fn.__name__}")
            _ran += 1
            try:
                _fn()
            except AssertionError as _e:
                print(f"      ↳ {_e}")
            except Exception as _e:                                # noqa: BLE001
                _FAILURES.append(f"{_fn.__name__}: {type(_e).__name__}: {_e}")
                print(f"      ↳ {type(_e).__name__}: {_e}")
    print(f"\n{'❌ FAILED' if _FAILURES else '✅ ALL PASS'}"
          f" — {len(_FAILURES)} 个失败 / {_ran} 个测试")
    raise SystemExit(1 if _FAILURES else 0)
