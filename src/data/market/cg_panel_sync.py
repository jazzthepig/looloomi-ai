"""面板日线的常驻同步 —— **把那个从没被调度的回填接上电** (S-304).

## 这个模块存在的唯一理由

S-303 顺着链条查到底,Sense 段 24 条私有取数路径的根是一个单点:

    cg_pro_backfill 只有一个手动 API 路由，没有循环
      → coingecko_pro_ohlc 表里 0 行
        → 账本从库里读不到可信价格
          → 24 个模块各自打外网

**它不是没建好,是没人在的时候它不跑,而没人在的时候比有人在的时候多得多。**

Jazz 2026-09-05 问「Railway 还是 sandbox」时,答案就是这条推出来的:

> **一件事如果只在某个操作者在线时才发生,它最终就不会发生。**

所以这里是一个 Railway 循环 —— 不是脚本、不是手动路由、不在沙箱。
沙箱随会话消失,手动路由需要有人记得,而这两件事我们都已经付过学费。

## 两段,顺序不可换

    ① 解析   symbol → coin_id。库里已有的先用（trending_log 副产品 56 个），
             不够的才打 /coins/list（一次调用给全部 ~17,000 条）
    ② 回填   只对**已解析且允许回填**的对做 —— 市值裁决出来的默认不进，
             它们要先过 S-258 的收盘价校验

顺序不能换,因为回填要 `(symbol, coin_id)` 对,而**猜一个 coin_id 的代价是
把另一个币的整段历史写进这个标的,曲线看起来完全正常**。

## 额度

`/coins/list` 每周一次(listing 变化慢)。回填按天增量 —— **S-895 阶段 3 之后**,
只有「窗口里有洞」的标的重打,其余跳过(判据见下面的「覆盖差驱动」)。

⚠️ 改之前是**轮询式**的:每 6 小时把同一批标的的同一个 60 天窗口重打一遍,
**不问「库里已经有什么」** ⇒ 4 轮 × ~59 ≈ 236 次/天,
**失败时 10 分钟一轮 ⇒ 144 轮 × 59 ≈ 8,500 次/天**。
那正是「额度超支」的形状 —— 而超支的部分**全花在重复的数据上**。

改之后的量级 ≈ **每个标的每天一次**(窗口右端是「今天」,今天那根还没写进去
⇒ 有洞 ⇒ 打一次;写进去之后,当天剩下的几轮全跳过)⇒ **~230–290 次/天**,
省 ~780 次/天。⚠️ 这个数**不是**「库里全都有 ⇒ 0 次」——
见下面「窗口右端」那段:右端永远差着「今天」那根,除非厂商那根一直不给。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

#: `/coins/list` 多久重取一次。listing 变化以周计,不是以天计。
LISTING_REFRESH_DAYS = 7

#: 一轮最多解析多少个新 symbol。护栏,不是目标。
MAX_RESOLVE_PER_RUN = 300

#: 增量回填往回看多少天。**不是「今天一天」** —— 一次失败会留一个洞,
#: 而一个洞在 `max(trade_date)` 上完全不可见(S-190 那次的形状)。
#:
#: ⚠️ 首版取 7 天,结果 **57 个标的全部被拒、写入 0 行** (S-306):
#: `cg_pro_backfill` 的地板是绝对值 30 根 bar,而 7 天窗口正常就只有 ~7 根。
#: **地板没错,是我把一个为长窗口回填写的函数用在增量刷新上** ——
#: 同一个数字在两种用途下含义相反:回填时 7 根 = 出错了,刷新时 7 根 = 正常。
#:
#: 现在 60 天:既让地板自然满足,也真的实现上面那句「补洞」——
#: 7 天窗口补不了一个 10 天前的洞,而我当时就是这么写的。
BACKFILL_LOOKBACK_DAYS = 60

# ── S-895 阶段 3:覆盖差驱动(够新就不打外网)────────────────────────────────
#
# 原来这个循环是**轮询式**的:每 6 小时把同一批标的的同一个 60 天窗口重打一遍,
# **不问「库里已经有什么」**。一天 4 轮 ≈ 236 次 /ohlc/range;
# 失败时 10 分钟一轮 ⇒ 144 轮 × 59 ≈ **8,500 次/天** —— 那正是「额度超支」的形状,
# 而超支的部分**全花在重复的数据上**。
#
# 仓库里已经有正确形状的范本:`perp_mcap_backfill.stale_coins()`
# (读库 → 算差 → 没有差就不打外网)。这一步不是发明新机制,
# 是**把一个循环改写成仓库里已经有的那种形状**。
#
# ⚠️ **判据是逐日集合,不是 `max(trade_date)`。**
# 一次失败留一个洞,而洞在前沿上完全不可见(S-190 那次的形状):
# 「最新那根是今天」和「今天往前有一天空缺」在 max 上完全同形。
#
# ⚠️ **窗口左端按「并集里最早的那一天」裁,不是按自己那个源裁。**
# 问的是「它那时候存在吗」:存在 ⇒ 少的那天是洞(要补);
# 还不存在 ⇒ 上市前的日子不是洞(不必补)。
# 读不到这个答案 ⇒ **不裁剪**(宁可多打一次,不可少补一天,S-180)。
#
# ⚠️ **窗口右端是「今天」,不是「库里最新的一天」—— 这个选择是有代价的。**
#
# 「右端取库里最新的一天」听起来更省(库里全都有 ⇒ 全跳过),但那样**面板会冻结**:
# 库里最新的一天不会自己往前走,而「没有洞 ⇒ 不打外网 ⇒ 库里不会前进」是闭环。
# ⇒ 右端必须是**墙上时钟**(今天),厂商哪天给到哪天,窗口就跟着走。
#
# 代价:今天那根 bar 在**这一天的第一轮**还没写进库里 ⇒ 它是一个洞 ⇒ 打一次;
# 写进去之后,当天剩下的几轮全跳过。⇒ **每个标的每天一次**,不是 0 次。
# (实测 2026-11-20:库里 `coingecko_pro_ohlc` 最新到 11-18,而 `binance_hist`
#  到 11-19 —— 面板那两天没写进去,所以那两天它一直在被重打。这是**现象**,
#  不是判据的错;另外「右端取库里最新那天」的写法会让这个现象永久化。)


def missing_days(covered: set[str], start: dt.date, end: dt.date, *,
                 known_first: Optional[str] = None) -> list[str]:
    """窗口 `[start, end]` 里,`covered` 之外还缺哪些日子(ISO 字符串,升序)。

    **纯函数** —— 判据从 IO 里拿出来,单独能测。
    范本:`perp_mcap_backfill.stale_coins()`:判据不碰 IO 才能离线验证。

    ⚠️ **判据是逐日集合,不是 `max(trade_date)`。**
    一次失败留一个洞,而洞在前沿上完全不可见(S-190 那次的形状)。

    ## `known_first` —— 「它那时候存在吗」

    窗口左端的那一天算不算洞,取决于**这个标的那时是不是已经存在**。
    `known_first` = 它**在任何源里**最早的那一天(并集 `deepest_start`):

    - `known_first` **早于**窗口 ⇒ 它在窗口之前就存在 ⇒ 左端少的那天**是洞**;
    - `known_first` **在窗口之内** ⇒ 它那时还没上市 ⇒ 上市前的日子**不是洞**;
    - `known_first` **未知**(None)⇒ **不裁剪**,整个窗口都算缺。

    ⚠️ **未知 ⇒ 不裁剪**,不是「按自己那个源的最早一天裁」。
    裁错了两个方向都出事:按自己那个源裁 ⇒ 老标的左端的洞**永远看不见**
    (少补,而且少补在 `max(trade_date)` 上完全不可见);不裁 ⇒ 新上市的标的
    每轮都白打一次(多打,不是少补 —— 宁可多打一次,不可少补一天,S-180)。

    ⚠️ `covered` 必须是**这个循环自己写的那个源**(`coingecko_pro_ohlc`)的日子。
    跨源并集回答的是另一个问题 ——「这段历史我们有没有」(S-276 的 `deepest_start`),
    而这里要回答的是「**我要写的这个序列**有没有洞」。
    拿并集当跳过依据,会把 `coingecko_pro_ohlc` 的行**少写**,
    而它在 `TRUSTED_RETURN_SOURCES` 里 —— 少写它就是少一份可信价源。
    ⇒ 并集只用来回答「那时它存在吗」,**不用来当跳过依据**。
    """
    if end < start:
        return []
    lo = start
    if known_first:
        try:
            _kf = dt.date.fromisoformat(str(known_first)[:10])
        except ValueError:
            _kf = start
        lo = max(start, _kf)
    if lo > end:
        return []
    out: list[str] = []
    _d = lo
    while _d <= end:
        _s = _d.isoformat()
        if _s not in covered:
            out.append(_s)
        _d += dt.timedelta(days=1)
    return out


#: 一次 `in.(...)` 里放多少个符号。
#: 260 个符号拼进 URL 约 1.4 KB —— PostgREST 收得下,但**分块更稳**
#: (代理/nginx 的 URI 上限各处不同)。分块还有一个好处:
#: 单块返回 ≤ 100×61 = 6,100 行 < PAGE_ASK ⇒ 一块一次请求,不分页。
_SYMBOL_CHUNK = 100


async def _covered_days(symbols: list[str], start: str, end: str, *,
                        source: Optional[str] = None) -> Optional[dict[str, set[str]]]:
    """一次批量读,不逐标的读。**读不到 ⇒ None**(S-180:读不到 ≠ 没有数据)。

    只读**这个循环自己写的那个源**。跨源并集是「历史深度」的问题
    (S-276 的 `deepest_start`),与「我要写的序列有没有洞」不是同一个问题。

    `end` 不参与过滤:库里没有未来日期的行,`gte.start` 已经是窗口。
    **下界不能省** —— 省了它就拿不到这个标的自己最早的那一天,
    新上市标的的裁剪就没有依据。

    ⚠️ **这是生产用的读法,不是 `run_once` 的默认行为** ——
    默认行为是「没有判据 ⇒ 照旧全量回填」。理由见 `run_once` 的 docstring。
    """
    if not symbols:
        return {}
    if source is None:
        from src.data.market.cg_pro_backfill import SOURCE_TAG
        source = SOURCE_TAG
    _syms = sorted({str(s).upper() for s in symbols if s})
    if not _syms:
        return {}
    out: dict[str, set[str]] = {}
    try:
        from src.data.style.header import _read_all
        for _i in range(0, len(_syms), _SYMBOL_CHUNK):
            _chunk = _syms[_i:_i + _SYMBOL_CHUNK]
            _rows = await _read_all("ohlcv_daily", {
                "select": "symbol,trade_date",
                "source": f"eq.{source}",
                "symbol": "in.(" + ",".join(_chunk) + ")",
                "trade_date": f"gte.{start}",
            })
            for _r in _rows or []:
                _sym = str(_r.get("symbol") or "").upper()
                _day = str(_r.get("trade_date") or "")[:10]
                if _sym and _day:
                    out.setdefault(_sym, set()).add(_day)
    except Exception:                                            # noqa: BLE001
        return None
    return out


async def _union_first_days(symbols: list[str]) -> Optional[dict[str, str]]:
    """每个标的**在任何源里**最早的那一天(并集 `deepest_start`)。

    为什么需要它:窗口左端的日子算不算「洞」,取决于**这个标的那时存在吗**。
    只看自己那个源 ⇒ 新上市的标的永远「有洞」(上市前没 bar),
    老标的左端的洞反而被裁掉 —— 两个方向都错。

    ⚠️ **这不是用并集当跳过依据**(见 `missing_days` 的说明)。
    并集在这里只回答一个问题:「它那时候存在吗」。

    **一次 RPC 拿全部标的** —— 不是逐标的读(`deepest_start` 已经是聚合过的,
    `ohlcv_symbol_coverage()` 一次算完)。读不到 ⇒ `None`
    (S-180:读不到 ≠ 没有数据)⇒ 调用方**不裁剪**,宁可多打一次。

    ⚠️ **生产用的读法,不是 `run_once` 的默认行为** —— 见 `run_once` 的 docstring。
    """
    if not symbols:
        return {}
    _want = {str(s).upper() for s in symbols if s}
    if not _want:
        return {}
    try:
        from src.api.store import supabase_rpc
        raw = await supabase_rpc("ohlcv_symbol_coverage", {})
    except Exception:                                            # noqa: BLE001
        return None
    if not isinstance(raw, list):
        return None
    out: dict[str, str] = {}
    for r in raw:
        if not isinstance(r, dict):
            continue
        _sym = str(r.get("symbol") or "").upper()
        _first = str(r.get("first_date") or "")[:10]
        if not _sym or not _first or _sym not in _want:
            continue
        if _sym not in out or _first < out[_sym]:
            out[_sym] = _first
    return out


#: 注入式写入,显式声明 (S-304)。`ohlcv_daily` 由 cg_pro_backfill 写,
#: 它自己是字面调用,已在清单里。
WRITES_TABLES = ("cg_coin_map",)

LOOP_NAME = "_cg_panel_loop"


async def _known_map(supabase_query) -> Optional[tuple[dict[str, str], dict[str, str],
                                                        dict[str, str]]]:
    """`cg_coin_map` 里已解析的 → (ids, klass, resolved_from)。

    **解析结果是缓存的,不是每天重算的。**

    ⚠️ `asset_class` 一起取 (S-313)。`to_rows` 只在拿到它时才写这一列,
    而首版没传 —— 实测 **3,520 行全部 `asset_class = NULL`**,
    于是任何按 `asset_class in (...)` 过滤的消费者(包括
    `refresh_depth_divergence`)**一行都看不见**。
    数据落进去了,而需要它的人看不到它:又一个「写了但没连线」。

    第三项 `resolved_from` 是**审计 `vendor_paired` 语义的真源**:
    - `FROM_DB` = trending_log 已存映射,vendor 出的
    - `FROM_UNIQUE` = `/coins/list` 里唯一匹配,vendor 出的
    - `FROM_MCAP` = 我们按市值撞名裁决,**不是 vendor 出的**,必须过校验

    把这三项区分清楚之前,daily loop 把 `cg_coin_map` 里所有行当 vendor_paired
    处理,语义范围比 docstring 承诺的宽 ——
    `FROM_MCAP` 写过的行再被读出来,`_verify_mapping` 又会被它挡住,
    反复。
    """
    # S-469:**读不到 ≠ 一个映射都没有。** 这里原来把读失败(RPC ~20s,共享 client 10s 超时)
    # 折成 `{}`,于是整张表在这一轮「全部缺失」,解析器按市值重猜一遍并 upsert ——
    # 2026-10-03 05:49 把刚人工改正的 ONE / AI 覆盖回了错的 coin_id。读不到就返回 None,
    # 调用方本轮不解析、不覆盖。
    try:
        rows = await supabase_query(
            "cg_coin_map",
            "symbol,coin_id,resolved_from,verified_at,asset_class")
    except Exception:                                           # noqa: BLE001
        return None
    if not isinstance(rows, list) or not rows:
        return None
    ids = {r["symbol"]: r["coin_id"] for r in rows
           if r.get("symbol") and r.get("coin_id")}
    cls = {r["symbol"]: (r.get("asset_class") or "Crypto") for r in rows
           if r.get("symbol")}
    rf = {r["symbol"]: (r.get("resolved_from") or "") for r in rows
          if r.get("symbol")}
    return ids, cls, rf


#: 11-02(T-220 补交「SKY 撞名」的根因):面板日线只覆盖 Binance 永续宇宙,**CIS 自己的 25 个加密名字不一定在里面** ——
#: SKY 在 `ohlcv_daily` 只有 15 行 HL 永续(2026-08),研究一按 symbol 读就以为「没数据 / 错源」。价格其实一直在
#: `asset_mcap_daily`(coin_id sky,2024-09 起),只是没进 `coingecko_pro_ohlc`。这里把 CIS 的加密名字并进面板,
#: 映射直接取 `cis_provider.CRYPTO_ASSETS` 的 coingecko id(人工核过的,写成 manual_verified,S-469 的粘性规则保护它)。
async def ensure_cis_names(supabase_query, supabase_upsert, panel: list[str]) -> tuple[list[str], list[str]]:
    """→ (面板 ∪ CIS 加密名字, 本轮新写进 cg_coin_map 的符号)。cg_coin_map 读不到 ⇒ 不写、只并面板。"""
    from src.data.cis.cis_provider import CRYPTO_ASSETS
    cis = {s.upper(): (c.get("coingecko") or "") for s, c in CRYPTO_ASSETS.items() if c.get("coingecko")}
    merged = sorted(set(x.upper() for x in panel) | set(cis))
    km = await _known_map(supabase_query)
    if km is None:
        return merged, []
    known = km[0]
    rows = [{"symbol": s, "coin_id": cid, "resolved_from": "manual_verified", "candidates": [cid],
             "resolved_at": dt.datetime.now(dt.timezone.utc).isoformat()} for s, cid in cis.items() if s not in known]
    if rows:
        try:
            await supabase_upsert("cg_coin_map", rows, "symbol")
        except Exception:                                           # noqa: BLE001 —— 写不进就让 run_once 自己去解析
            return merged, []
    return merged, [r["symbol"] for r in rows]


async def run_once(*, client, supabase_query, supabase_upsert,
                   panel_symbols: list[str],
                   today: Optional[str] = None,
                   coverage_reader=None,
                   union_reader=None) -> dict[str, Any]:
    """跑一轮。**返回结构化结果,不打印** —— 调用方负责心跳与日志。

    注入是为了这层能离线测:「何时算成功、何时不该回填」这些判断
    必须能在没有网络的情况下被验证。

    `coverage_reader(symbols, start, end) -> Optional[dict[str, set[str]]]`
    是 S-895 阶段 3 加的第三个注入点:「库里已经有哪些日子」的读法。
    **默认 None ⇒ 没有判据 ⇒ 照旧全量回填**(今天的形状,不多花也不少补)。

    `union_reader(symbols) -> Optional[dict[str, str]]` 是第四个注入点:
    「每个标的在任何源里最早的那一天」。它只用来回答「它那时候存在吗」
    (窗口左端的日子算不算洞),**不用来当跳过依据**。读不到 ⇒ 不裁剪。

    ## ⚠️ 为什么默认**不是**真读库(`_covered_days` / `_union_first_days`)

    首版默认去读库,于是**函数的结果开始依赖线上库当时的内容**。
    实测(2026-11-20):`tests/test_cg_coin_map_manual_is_sticky.py` 里一个
    既有测试**单独跑绿、批量跑红** —— 它断言「mcap 裁决出来的 BTC 要进回填」,
    而批量跑时线上库里 BTC 的 60 天窗口已经够新 ⇒ 被正确地跳过了 ⇒
    「`seen["pairs"]` 这个键根本没出现」。

    那个测试的断言**没有错**,错的是**它被一个它不知道的判据改变了含义**:
    它测的是 `vendor_paired` 的语义(市值裁决的不享受放行),
    不是「BTC 必须被回填」。**一个测试的结论依赖它没声明的输入,
    就不是一个测试。**

    ⇒ **读不读库是调用方的决定,不是函数的默认行为。**
    生产(`main.py::_cg_panel_loop`)显式传 `_covered_days` / `_union_first_days`;
    测试显式传假件;谁都不传 ⇒ 全量回填(旧形状,安全方向:宁可多打一次)。
    `tests/test_backfill_skips_up_to_date.py` 里有一条形状守卫钉住
    「生产那条路**必须**传」—— 免得这个默认值将来被人当成「忘了传也没事」。
    """
    from src.data.market.cg_universe import (
        CG_PRO_BASE, FROM_DB, FROM_MANUAL, FROM_MCAP, FROM_UNIQUE,
        index_listing, pairs_for_backfill, resolve)

    # ⚠️ **UTC**。Mac 在 JST,`date.today()` 是本地的 —— 15:00 UTC 之后
    # 算出来的就是明天,而窗口两端都跟着错一天(规则 5c / S-195 / S-368)。
    today = today or dt.datetime.now(dt.timezone.utc).date().isoformat()
    out: dict[str, Any] = {"today": today, "status": "ok", "errors": [],
                           "n_resolved_new": 0, "rows_written": 0}

    km = await _known_map(supabase_query)
    if km is None:
        out["status"] = "error"
        out["error"] = ("cg_coin_map 读不到 —— 读不到 ≠ 没有映射;本轮不解析、不覆盖、不回填"
                        "(S-469:曾因此把人工改正的映射按市值重猜覆盖)")
        out["reason"] = out["error"]
        return out
    known, klass, resolved_from = km
    missing = [s for s in panel_symbols if s.upper() not in known]
    out["n_known"] = len(known)
    out["n_missing"] = len(missing)

    # ── ① 解析 ──────────────────────────────────────────────────────────────
    idx: dict[str, list[str]] = {}
    mcap: dict[str, float] = {}
    # **本轮我们自己发起的外部请求数** —— 规则 5b 的判活判据要看得见
    # 「省了多少」,不然「省了额度」和「什么都没干」在面板上同形。
    _n_calls_resolution = 0
    if missing:
        try:
            _n_calls_resolution += 1
            r = await client.get(f"{CG_PRO_BASE}/coins/list")
            if r.status_code != 200:
                out["errors"].append(f"/coins/list HTTP {r.status_code}")
            else:
                idx = index_listing(r.json() or [])
        except Exception as e:                                  # noqa: BLE001
            out["errors"].append(f"/coins/list {type(e).__name__}: {str(e)[:70]}")

        # ── 市值:撞名裁决的唯一依据 (S-320) ──────────────────────────────
        #
        # ⚠️ 我在 S-304 把这个标成「已知缺口,下一步」,而它成了**绑定约束**:
        # 面板从 24 扩到 262 之后,映射只从 57 涨到 **59** ——
        # **203 个标的解析不出来,因为撞名在 262 的规模上是常态不是例外**,
        # 而没有市值就永远判 ambiguous。
        #
        # 「已知缺口」和「不重要」是两个状态,而我把前者写成了后者的语气。
        #
        # `/coins/markets` 是 CG Pro 的**批量**端点(250/次,付费源,合规):
        # 取市值前 1000 名 = 4 次调用,覆盖任何我们会交易的标的。
        # 这不是扇出 —— 是 4 次批量读。
        for _page in range(1, 5):
            try:
                _n_calls_resolution += 1
                mr = await client.get(
                    f"{CG_PRO_BASE}/coins/markets",
                    params={"vs_currency": "usd", "order": "market_cap_desc",
                            "per_page": 250, "page": _page})
                if mr.status_code != 200:
                    out["errors"].append(f"/coins/markets p{_page} HTTP {mr.status_code}")
                    break
                for c in (mr.json() or []):
                    cid, mc = c.get("id"), c.get("market_cap")
                    if cid and mc:
                        mcap[str(cid)] = float(mc)
            except Exception as e:                              # noqa: BLE001
                out["errors"].append(
                    f"/coins/markets p{_page} {type(e).__name__}: {str(e)[:60]}")
                break
        out["n_mcap"] = len(mcap)

    res = resolve(missing[:MAX_RESOLVE_PER_RUN], known=known,
                  listing_index=idx, mcap=mcap)
    out["resolution"] = {k: res[k] for k in
                         ("n_total", "n_resolved", "n_from_db", "n_unique",
                          "n_mcap_tiebreak_unverified")}
    # **显式带出来** —— 未解析与撞名未决不是「没有数据」,是我们没找到 id。
    out["ambiguous"] = res["ambiguous"][:20]
    out["unresolved"] = res["unresolved"][:20]

    # 人工确认过的映射(FROM_MANUAL)永不被自动解析覆盖;库里另有触发器兜底(S-469)。
    new_rows = [{"symbol": m.symbol, "coin_id": m.coin_id,
                 "resolved_from": m.resolved_from,
                 "candidates": list(m.candidates) or None}
                for m in res["resolved"]
                if m.coin_id and resolved_from.get(m.symbol) != FROM_MANUAL]
    if new_rows:
        if await supabase_upsert("cg_coin_map", new_rows, "symbol"):
            out["n_resolved_new"] = len(new_rows)

    # ── ② 回填 ──────────────────────────────────────────────────────────────
    # **本轮外呼数先落一个底** —— 解析阶段打的那些(≤5 次)也是外呼,
    # 「这一轮花了多少」必须包括它们,否则分母是假的。
    out["n_calls_resolution"] = _n_calls_resolution
    out["n_calls_backfill"] = 0
    out["n_calls"] = _n_calls_resolution
    # **默认排除市值裁决的** —— 未过收盘价校验的猜测不许写 ohlcv_daily。
    # 把 `cg_coin_map` 里已知映射带回来时,**只带 vendor 出的(FROM_DB/FROM_UNIQUE)**;
    # FROM_MCAP 是我们自己按市值猜的撞名裁决,**必须先过 paid-first 校验**(S-307
    # 之后又一轮收紧,2026-09-17 audit),不能享受 `vendor_paired` 的 not-checkable
    # 放行权 —— 否则 endpoint 写错一处就把「我们猜的币」永久当成「vendor 出的币」,
    # `_verify_mapping` 形同虚设。
    pairs = pairs_for_backfill(res)
    _vendor_known = [(s, cid) for s, cid in known.items()
                     if resolved_from.get(s) in (FROM_DB, FROM_UNIQUE, FROM_MANUAL)]
    # S-471:市值裁决的已知映射**也要每天写** —— 只是不享受 vendor_paired 放行,必须先过
    # `_verify_mapping` 对 binance_hist 的同日收盘校验。原来这里整批丢掉它们,于是 BTC / ETH / SOL
    # 在内的 18 个核心名(① 面板 24 个里的 18 个)从来没有日更写入端;S-459 关掉 collect_ohlcv
    # 的加密写入后,它们只剩手动回填 —— 10-02 起 HL 账本与代币化倾斜因缺收盘而拒绝记账。
    _mcap_known = [(s, cid) for s, cid in known.items() if resolved_from.get(s) == FROM_MCAP]
    _vendor_syms = {s for s, _ in pairs} | {s for s, _ in _vendor_known}
    pairs += _vendor_known + _mcap_known
    pairs = list(dict.fromkeys(pairs))
    out["n_pairs"] = len(pairs)
    out["n_vendor_paired"] = len(_vendor_known)
    out["n_mcap_required_check"] = len(_mcap_known)

    if not pairs:
        out["status"] = "skipped"
        out["reason"] = ("一个可回填的 (symbol, coin_id) 对都没有 —— "
                         "**这不是「今天没行情」,是映射还没解析出来**")
        return out

    # ── ③ 覆盖差驱动:够新就不打外网 (S-895 阶段 3) ─────────────────────
    #
    # 判据 = 这个循环**自己写的那个源**(`coingecko_pro_ohlc`)逐日覆盖,
    # 不是跨源并集 —— 并集回答的是「这段历史我们有没有」(S-276 的 `deepest_start`),
    # 这里要回答的是「**我要写的这个序列**有没有洞」。拿并集当跳过依据,
    # 会把 `coingecko_pro_ohlc` 的行**少写**,而它在 `TRUSTED_RETURN_SOURCES` 里。
    _end_d = dt.date.fromisoformat(today)
    _start_d = _end_d - dt.timedelta(days=BACKFILL_LOOKBACK_DAYS)
    out["window"] = f"{_start_d.isoformat()}..{_end_d.isoformat()}"

    # ⚠️ **没有判据 ⇒ 全量回填**(旧形状)。见 `run_once` 的 docstring:
    # 默认去读库 ⇒ 函数的结果依赖线上库当时的内容,而既有测试因此变成
    # 「线上库说什么就什么」(单独绿 / 批量红)。**读不读库是调用方的决定。**
    _reader = coverage_reader
    _ureader = union_reader
    _cov_provided = _reader is not None
    _union_provided = _ureader is not None
    _cov: Optional[dict[str, set[str]]] = None
    if _cov_provided:
        try:
            _cov = await _reader([s for s, _ in pairs],
                                 _start_d.isoformat(), _end_d.isoformat())
        except Exception:                                        # noqa: BLE001
            _cov = None
    _cov_ok = _cov is not None
    # 「它那时候存在吗」—— 并集的最早一天。读不到 ⇒ None ⇒ **不裁剪**。
    _union: Optional[dict[str, str]] = None
    if _union_provided:
        try:
            _union = await _ureader([s for s, _ in pairs])
        except Exception:                                        # noqa: BLE001
            _union = None
    _union_ok = _union is not None
    _fetch_pairs: list[tuple[str, str]] = list(pairs)
    _skipped: list[str] = []
    if _cov_ok:
        _fetch_pairs = []
        for _s, _cid in pairs:
            _have = set((_cov or {}).get(_s.upper()) or ())
            _known_first = (_union or {}).get(_s.upper())
            if _have and not missing_days(_have, _start_d, _end_d,
                                          known_first=_known_first):
                _skipped.append(_s)
            else:
                _fetch_pairs.append((_s, _cid))
    # **读不到 ≠ 没有数据** (S-180):读不到就照旧全量回填。
    # 少补数据的失败模式是**静默**的 —— 洞在前沿上完全不可见(S-190)。
    out["n_pairs"] = len(pairs)
    out["n_pairs_fetched"] = len(_fetch_pairs)
    out["n_pairs_skipped_up_to_date"] = len(_skipped)
    out["coverage_read_ok"] = _cov_ok
    out["union_read_ok"] = _union_ok
    # 「有没有判据」和「判据读到了没有」是**两个问题** ——
    # 前者是调用方的选择,后者是 IO 的结果。合成一个数,
    # 「没传判据」就会被读成「判据读失败」(两者的修法完全不同)。
    out["coverage_reader_provided"] = _cov_provided
    out["union_reader_provided"] = _union_provided
    # 回填每个标的 1 次 /ohlc/range(窗口 60 天 < CHUNK_DAYS=175 ⇒ 不会分块)。
    out["n_calls"] = _n_calls_resolution + len(_fetch_pairs)
    out["n_calls_resolution"] = _n_calls_resolution
    out["n_calls_backfill"] = len(_fetch_pairs)

    if not _fetch_pairs:
        # 全部已是最新 —— 本轮 **0 次 /ohlc/range 调用**。
        # **不是故障,也不是「今天没行情」**:是「没有差可补」。
        out["n_classes"] = 0
        out["rows_written"] = 0
        out["backfill_ok"] = True
        out["n_symbols_written"] = 0
        out["n_symbols_failed"] = 0
    else:
        try:
            from src.data.market.cg_pro_backfill import backfill
            end, start = _end_d, _start_d
            # 显式说明用途:窗口 60 天,地板按窗口比例算(S-306)。
            # `vendor_paired`:映射是 CoinGecko 自己成对给的(`/coins/list` 里唯一,
            # 或 trending 接口一并返回),**不是我们猜的**。对这些,当库里没有
            # 对照行时「不可校验」应当放行并记为未校验,而不是拒写 —— 否则面板
            # 结构上永远扩不出已有的 25 个标的 (S-307)。
            # 市值裁决出来的不在这个集合里,它们仍然必须先过校验。
            _vendor = _vendor_syms          # 市值裁决的不在里面:查不到对照 ⇒ 拒写,不放行
            # **按 asset_class 分组** (S-313) —— `backfill` 一次只接受一个 class,
            # 而面板里有 6 个。传一个统一值会给 8 个非 Crypto 标的贴错标签,
            # 而错的标签比缺失的标签更难发现。
            _groups: dict[str, list] = {}
            for s_, cid in _fetch_pairs:
                _groups.setdefault(klass.get(s_, "Crypto"), []).append((s_, cid))
            _rows, _ok_all, _per_all = 0, True, []
            for _cls, _grp in _groups.items():
                _r = await backfill(_grp, start=start, end=end, dest="supabase",
                                    asset_class=_cls,
                                    min_candles=max(5, int(BACKFILL_LOOKBACK_DAYS * 0.5)),
                                    vendor_paired=_vendor)
                _rows += int(getattr(_r, "rows_written", 0) or 0)
                _ok_all = _ok_all and bool(getattr(_r, "ok", False))
                _per_all.extend(getattr(_r, "per_symbol", ()) or ())
            r = type("_Agg", (), {"rows_written": _rows, "ok": _ok_all,
                                  "per_symbol": tuple(_per_all),
                                  "reason": "" if _ok_all else "见 per_symbol"})()
            out["n_classes"] = len(_groups)
            out["rows_written"] = int(getattr(r, "rows_written", 0) or 0)
            out["backfill_ok"] = bool(getattr(r, "ok", False))
            # ⚠️ **写了几行 ≠ 写全了** (S-310)。首轮实测写入 12/57 个标的,
            # 而心跳报 `ok` —— 因为 `rows_written > 0` 就算进展。进展是真的,
            # 但**「写了 12 个」和「写了 57 个」在 ok 上完全同形**,
            # 而 45 个没成功这件事不该只存在于 detail 里。
            _per = getattr(r, "per_symbol", ()) or ()
            out["n_symbols_written"] = sum(1 for x in _per if getattr(x, "ok", False))
            out["n_symbols_failed"] = len(_per) - out["n_symbols_written"]
            if out["n_symbols_failed"]:
                from src.data.market.cg_pro_backfill import _why_all_failed
                out["shortfall"] = _why_all_failed(
                    [x for x in _per if not getattr(x, "ok", False)])[:220]
            if not out["backfill_ok"]:
                out["errors"].append(str(getattr(r, "reason", ""))[:150])
        except Exception as e:                                  # noqa: BLE001
            out["status"] = "error"
            out["error"] = f"{type(e).__name__}: {str(e)[:140]}"
            return out

    # ⚠️ **「没给判据」和「判据读失败」是两件事,理由里也要分开说。**
    # 前者是调用方的选择(测试里就是故意不给),后者是 IO 的结果(要查)。
    # 合成一句话 ⇒ 「没传判据」会被读成「读失败」,而两者的修法完全不同。
    if not _cov_provided:
        _cov_note = ";**没有覆盖判据 ⇒ 本轮全量回填**"
    elif not _cov_ok:
        _cov_note = ";**覆盖读失败 ⇒ 本轮全量回填**"
    else:
        _cov_note = ""
    if not _union_provided:
        _union_note = ";**没有并集判据 ⇒ 不裁剪(宁可多打一次)**"
    elif not _union_ok:
        _union_note = ";**并集深度读失败 ⇒ 不裁剪(宁可多打一次)**"
    else:
        _union_note = ""

    # `status` 供 `loop_beat.classify()` 用 —— **ok 从产出量推导,不写死**(S-299)。
    if out["rows_written"] > 0:
        out["status"] = "ok"
    elif out["errors"]:
        out["status"] = "error"
        # ⚠️ 首版只报「1 个问题」**不说是哪个问题** —— `classify()` 读的是
        # `error`(单数),而这里只填了 `errors`(复数),于是心跳上是一句
        # 没有原因的失败。一个不带原因的失败,排查成本等于从零开始 (S-306)。
        out["error"] = str(out["errors"][0])[:200]
    else:
        # 0 行且无错:面板已经是最新的。**合法,但不是进展** —— 记为 refused,
        # 连续多轮 0 行由 producer_freshness 的事件时钟去判。
        out["status"] = "skipped"

    out["reason"] = (
        f"映射 {len(known)} 已知 + {out['n_resolved_new']} 新解析"
        + (f"(市值表 {out.get('n_mcap')} 条)" if out.get("n_mcap") else "")
        + ";"
        + f"回填 {len(_fetch_pairs)}/{len(pairs)} 对"
        + (f"(**{len(_skipped)} 对已是最新,跳过**)" if _skipped else "")
        + f" · 写入 {out['rows_written']} 行"
        + f" · 外呼 {out['n_calls']} 次"
        + (f" · **标的 {out.get('n_symbols_written')}/{len(_fetch_pairs)}**"
           f"({out.get('shortfall') or ''})"
           if out.get("n_symbols_failed") else "")
        + (f";撞名未决 {len(res['ambiguous'])}、未解析 {len(res['unresolved'])}"
           f"(**显式列出,不静默丢弃**)" if res["ambiguous"] or res["unresolved"]
           else "")
        + (f";{len(out['errors'])} 个问题" if out["errors"] else "")
        + _cov_note + _union_note)
    return out
