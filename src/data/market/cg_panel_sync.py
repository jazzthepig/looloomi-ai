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

`/coins/list` 每周一次(listing 变化慢)。回填按天增量,约 262 次/天
⇒ 每月 ~8,000 次,占 Analyst 月额度 500,000 的 **1.6%**。
而当前用量是 0.4% —— 我们一直在为一个几乎全新的付费额度做取舍。
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

#: 注入式写入,显式声明 (S-304)。`ohlcv_daily` 由 cg_pro_backfill 写,
#: 它自己是字面调用,已在清单里。
WRITES_TABLES = ("cg_coin_map",)

LOOP_NAME = "_cg_panel_loop"


async def _known_map(supabase_query) -> tuple[dict[str, str], dict[str, str]]:
    """`cg_coin_map` 里已解析的 → `({symbol: coin_id}, {symbol: asset_class})`。

    **解析结果是缓存的,不是每天重算的。**

    ⚠️ `asset_class` 一起取 (S-313)。`to_rows` 只在拿到它时才写这一列,
    而首版没传 —— 实测 **3,520 行全部 `asset_class = NULL`**,
    于是任何按 `asset_class in (...)` 过滤的消费者(包括
    `refresh_depth_divergence`)**一行都看不见**。
    数据落进去了,而需要它的人看不到它:又一个「写了但没连线」。
    """
    try:
        rows = await supabase_query(
            "cg_coin_map",
            "symbol,coin_id,resolved_from,verified_at,asset_class") or []
        ids = {r["symbol"]: r["coin_id"] for r in rows
               if r.get("symbol") and r.get("coin_id")}
        cls = {r["symbol"]: (r.get("asset_class") or "Crypto") for r in rows
               if r.get("symbol")}
        return ids, cls
    except Exception:                                           # noqa: BLE001
        return {}, {}


async def run_once(*, client, supabase_query, supabase_upsert,
                   panel_symbols: list[str],
                   today: Optional[str] = None) -> dict[str, Any]:
    """跑一轮。**返回结构化结果,不打印** —— 调用方负责心跳与日志。

    注入是为了这层能离线测:「何时算成功、何时不该回填」这些判断
    必须能在没有网络的情况下被验证。
    """
    from src.data.market.cg_universe import (
        CG_PRO_BASE, index_listing, pairs_for_backfill, resolve)

    today = today or dt.date.today().isoformat()
    out: dict[str, Any] = {"today": today, "status": "ok", "errors": [],
                           "n_resolved_new": 0, "rows_written": 0}

    known, klass = await _known_map(supabase_query)
    missing = [s for s in panel_symbols if s.upper() not in known]
    out["n_known"] = len(known)
    out["n_missing"] = len(missing)

    # ── ① 解析 ──────────────────────────────────────────────────────────────
    idx: dict[str, list[str]] = {}
    mcap: dict[str, float] = {}
    if missing:
        try:
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

    new_rows = [{"symbol": m.symbol, "coin_id": m.coin_id,
                 "resolved_from": m.resolved_from,
                 "candidates": list(m.candidates) or None}
                for m in res["resolved"] if m.coin_id]
    if new_rows:
        if await supabase_upsert("cg_coin_map", new_rows, "symbol"):
            out["n_resolved_new"] = len(new_rows)

    # ── ② 回填 ──────────────────────────────────────────────────────────────
    # **默认排除市值裁决的** —— 未过收盘价校验的猜测不许写 ohlcv_daily。
    pairs = pairs_for_backfill(res)
    pairs += [(s, cid) for s, cid in known.items()]
    pairs = list(dict.fromkeys(pairs))
    out["n_pairs"] = len(pairs)

    if not pairs:
        out["status"] = "skipped"
        out["reason"] = ("一个可回填的 (symbol, coin_id) 对都没有 —— "
                         "**这不是「今天没行情」,是映射还没解析出来**")
        return out

    try:
        from src.data.market.cg_pro_backfill import backfill
        end = dt.date.fromisoformat(today)
        start = end - dt.timedelta(days=BACKFILL_LOOKBACK_DAYS)
        # 显式说明用途:窗口 60 天,地板按窗口比例算(S-306)。
        # `vendor_paired`:映射是 CoinGecko 自己成对给的(`/coins/list` 里唯一,
        # 或 trending 接口一并返回),**不是我们猜的**。对这些,当库里没有
        # 对照行时「不可校验」应当放行并记为未校验,而不是拒写 —— 否则面板
        # 结构上永远扩不出已有的 25 个标的 (S-307)。
        # 市值裁决出来的不在这个集合里,它们仍然必须先过校验。
        _vendor = {s_ for s_, _ in pairs}
        # **按 asset_class 分组** (S-313) —— `backfill` 一次只接受一个 class,
        # 而面板里有 6 个。传一个统一值会给 8 个非 Crypto 标的贴错标签,
        # 而错的标签比缺失的标签更难发现。
        _groups: dict[str, list] = {}
        for s_, cid in pairs:
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
    except Exception as e:                                      # noqa: BLE001
        out["status"] = "error"
        out["error"] = f"{type(e).__name__}: {str(e)[:140]}"
        return out

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
        f"回填 {len(pairs)} 对 · 写入 {out['rows_written']} 行"
        + (f" · **标的 {out.get('n_symbols_written')}/{len(pairs)}**"
           f"({out.get('shortfall') or ''})"
           if out.get("n_symbols_failed") else "")
        + (f";撞名未决 {len(res['ambiguous'])}、未解析 {len(res['unresolved'])}"
           f"(**显式列出,不静默丢弃**)" if res["ambiguous"] or res["unresolved"]
           else "")
        + (f";{len(out['errors'])} 个问题" if out["errors"] else ""))
    return out
