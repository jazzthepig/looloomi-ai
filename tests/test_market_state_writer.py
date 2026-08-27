"""几何基底的写者:单源、定盘、写前设地板 (S-245).

这些断言各自钉住一个**已经实测发生过**的缺陷,不是假想的:

    97.6% 的天数混了价源              → 单源过滤 + 客户端断言
    17,876 个 symbol-day 有 ≥2 个源     → 平均差 190.6bps,最大 5,506bps
    n_symbols 在 25↔75 之间摆动        → 定盘,并记下剔除原因
    vec_full 曾要被写成 dict           → 位置数组回归 (S-233)
    fng/oi/stable 拉低完整度上限        → 从分母摘出 (S-231)
    地板在写之后 = 写了才发现不该写      → 地板在写之前 (S-220)
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.vector import market_state_writer as W
from src.data.vector.market_state import (
    DIMS, UNWIRED_DIMS, StateVector, build_rows_for_upsert)

_FAILURES: list[str] = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ✓ {label}")
    else:
        _FAILURES.append(f"{label}{(' — ' + detail) if detail else ''}")
        print(f"  ✗ {label}\n      {detail}")


# ── 单源 ──────────────────────────────────────────────────────────────────────

def test_panel_query_filters_by_source():
    """取数必须带 `source=eq.…`。

    **按构造查,不按字符串查。** 一句解释"必须过滤 source"的注释里也含有
    `source`,而一个只 grep 文本的守卫会被自己的文档满足 —— `tests/_source.py`
    记的就是这个失败,今天已经踩到第八次。所以解析 AST,找那个 dict 字面量里
    真的有一个键叫 "source" 且值以 "eq." 开头。
    """
    tree = ast.parse(inspect.getsource(W.fetch_panel))
    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if not (isinstance(k, ast.Constant) and k.value == "source"):
                continue
            # 值是 f-string `f"eq.{source}"` → JoinedStr,首段常量应为 "eq."
            if isinstance(v, ast.JoinedStr) and v.values:
                head = v.values[0]
                if isinstance(head, ast.Constant) and str(head.value).startswith("eq."):
                    found = True
            elif isinstance(v, ast.Constant) and str(v.value).startswith("eq."):
                found = True
    _check("面板查询在服务端按 source 过滤(AST 构造,非字符串)", found,
           "fetch_panel 的查询字典里没有 source: eq.* —— 没有它,同一天同一标的的"
           "多个源会按分页顺序静默互相覆盖,平均差 190.6bps")


def test_no_multi_source_fallback():
    """模块里不能有「这个源没有就用下一个」的回退。

    那正是造出 582 行拼接表的逻辑:它必然在窗口中间跨源,而三个源对同一个
    BTC 同一个窗口给 +1.6% / +21.3% / +19.1%。宁可少几天,不可跨源。
    """
    src = inspect.getsource(W)
    banned = [s for s in ("yfinance", "coingecko", "eodhd")
              if f'"{s}"' in src or f"'{s}'" in src]
    _check("模块里没有第二个价源的字面量", not banned, f"出现了 {banned}")
    _check("PANEL_SOURCE 是 binance_hist", W.PANEL_SOURCE == "binance_hist",
           W.PANEL_SOURCE)


# ── 定盘 ──────────────────────────────────────────────────────────────────────

def _panel(spec: dict[str, int], days: list[str]):
    """构造 {symbol: {day: (close, volume)}},spec 给每个标的覆盖前 n 天。"""
    return {s: {d: (100.0 + i, 1000.0) for i, d in enumerate(days[:n])}
            for s, n in spec.items()}


def test_pin_panel_excludes_low_coverage_with_a_reason():
    days = [f"2025-01-{i:02d}" for i in range(1, 21)]          # 20 天
    panel = _panel({"FULL": 20, "MOSTLY": 19, "HALF": 10, "THIN": 2}, days)
    spec = W.pin_panel(panel, days[0], source="binance_hist", min_coverage=0.90)

    _check("覆盖率达标的入选", set(spec.symbols) == {"FULL", "MOSTLY"},
           str(spec.symbols))
    _check("不达标的被剔除", set(spec.excluded) == {"HALF", "THIN"},
           str(sorted(spec.excluded)))
    _check("每个剔除都带原因,且原因里有数字",
           all(("/" in r and "coverage" in r) for r in spec.excluded.values()),
           str(spec.excluded))
    # 拒绝的信息量必须大于一个布尔值 —— 聚合后的 payload 也要说得出剔了几个。
    _check("payload 报出剔除计数", spec.as_payload()["excluded"].get("coverage") == 2,
           str(spec.as_payload()))


def test_pinned_panel_makes_n_symbols_constant():
    """定盘之后成员是常数 —— 这正是横截面维可跨日比较的前提。

    负控制:同一份面板不定盘时,逐日"谁有价"会给出变化的成员数。
    实测旧表 n_symbols 在 25↔75 之间摆动,而 breadth/corr/dispersion 是在
    那些不同成员集上算的 —— 「广度下降」和「面板少了 30 个标的」同一个数。
    """
    days = [f"2025-01-{i:02d}" for i in range(1, 21)]
    panel = _panel({f"S{i}": (20 if i < 25 else 5) for i in range(40)}, days)
    spec = W.pin_panel(panel, days[0], source="binance_hist", min_coverage=0.90)

    pinned = {len([s for s in spec.symbols if d in panel[s]]) for d in days}
    naive = {len([s for s in panel if d in panel[s]]) for d in days}
    _check(f"定盘后每日成员数恒定({pinned})", len(pinned) == 1, str(sorted(pinned)))
    _check(f"负控制:不定盘时成员数会变({len(naive)} 种取值)", len(naive) > 1,
           "负控制没有复现出摆动 —— 这个测试没有在测它以为在测的东西")


# ── 地板在写之前 ──────────────────────────────────────────────────────────────

def test_floor_refuses_without_ever_calling_upsert():
    """地板必须在 upsert **之前**返回 —— 用行为验,不用源码验。

    ⚠️ 第一版是 AST 版:比较 `refused=True` 的 return 与 `supabase_upsert_table`
    调用的行号。**变异测试当场打穿。** 把 `if spec.n_symbols < MIN_SYMBOLS:`
    改成 `if False:`,那个 return 语句**仍然在 AST 里**,行号也仍然更早,
    守卫照样全绿 —— 而地板已经没了。

    我验的是「那行代码在不在」,要验的是「那条路走不走得到」。
    这是今天第九次同一个错法(`tests/_source.py`):**语法树能告诉你结构,
    告诉不了你可达性。** 静态守卫只能钉住"写法",钉不住"行为"。

    所以改成行为验:喂一个过不了地板的面板,给 upsert 装探针,断言**探针一次
    也没被碰过**。它不关心代码长什么样,只关心写没写 —— 在 `if False:` 下必红。
    """
    # ⚠️ 第二版仍然被变异 2 打穿,原因值得记:我的夹具是「5 标的 × 20 天」,
    # 两条地板都不满足 —— 但即使把两条都改成 `if False:`,`compute_vectors`
    # 内部还有第三道 `len(live) < MIN_SYMBOLS: continue`,于是 0 个向量,
    # 由 `if not vectors` 兜住,照样 refused、照样没写。**测试通过了,
    # 但通过的原因不是我以为的那条。** 一个夹具同时触发三条地板,
    # 就分不出是哪条在起作用 —— 又一次「两个状态压成一个」。
    #
    # 所以每条地板配一个**只触发它自己**的夹具,并断言拒绝原因指名了是哪条。
    # 拒绝原因是契约的一部分:一个说不出"我为什么算不了"的拒绝,和一次静默
    # 失败在下游长得一样。
    cases = [
        # (标的数, 天数, 期望的原因前缀, 说明)
        (5, 500, "定盘后只剩", "标的地板:天数充足,只有标的不够"),
        (25, 20, "窗口只有", "天数地板:标的充足,只有天数不够"),
    ]
    for n_syms, n_days, want_prefix, label in cases:
        ok, calls = _run_recompute(n_syms, n_days)
        _check(f"{label} → 拒绝", ok.refused is True and ok.ok is False,
               f"ok={ok.ok} refused={ok.refused} reason={ok.reason}")
        _check(f"{label} → upsert 一次也没被调用", not calls,
               f"写了 {calls} —— 地板在写之后等于没有地板 (S-220)")
        _check(f"{label} → 原因指名了这一条地板",
               ok.reason.startswith(want_prefix),
               f"期望以「{want_prefix}」开头,实际:{ok.reason[:60]}")
        _check(f"{label} → rows_written = 0", ok.rows == 0, str(ok.rows))


def test_read_failure_says_which_kind_of_failure():
    """读不到的四个原因必须给出四句不同的话 (S-245 第二轮)。

    实测 2026-08-27:Jazz 在 Mac 上跑 dry-run 拿到
    「Supabase 读不到 —— offset=0,已取 0 行」。这句话对排查毫无帮助 ——
    **凭证没设 / 断路器打开 / HTTP 4xx / 传输失败**,四个原因长得一模一样,
    而最可能的那个(裸 `python3 -c` 没导出 .env)本来一句话就能说清。

    第十次「两个状态压进一个表示」,而且是我一小时前刚写的 `Optional[list]`。
    """
    import asyncio
    import os

    import src.api.store as store

    def read(**patch):
        """在给定环境下跑一次 _sb_get,返回 (ok, reason)。"""
        saved = {k: os.environ.pop(k, None)
                 for k in ("SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_SERVICE_KEY")}
        orig_brk, orig_req = store.supabase_breaker_state, store._supabase_request_with_retry
        os.environ.update({k: v for k, v in patch.get("env", {}).items()})
        if "breaker" in patch:
            store.supabase_breaker_state = lambda: patch["breaker"]
        if "resp" in patch:
            async def fake(*a, **k):                       # noqa: ANN001
                return patch["resp"]
            store._supabase_request_with_retry = fake
        try:
            r = asyncio.new_event_loop().run_until_complete(W._sb_get("t", {}))
        finally:
            store.supabase_breaker_state, store._supabase_request_with_retry = orig_brk, orig_req
            for k in ("SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_SERVICE_KEY"):
                os.environ.pop(k, None)
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v
        return r.ok, r.reason

    class _Resp:
        def __init__(self, code, text="denied by RLS"):
            self.status_code, self.text = code, text

        def json(self):
            return [{"x": 1}]

    live = {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_KEY": "k"}
    cases = {
        "no_creds":  read(env={}),
        "breaker":   read(env=live, breaker={"open": True, "cooldown_remaining_s": 12.0}),
        "http_4xx":  read(env=live, breaker={"open": False}, resp=_Resp(403)),
        "transport": read(env=live, breaker={"open": False}, resp=None),
        "ok":        read(env=live, breaker={"open": False}, resp=_Resp(200)),
    }

    _check("凭证缺失被单独识别",
           not cases["no_creds"][0] and ".env" in cases["no_creds"][1],
           cases["no_creds"][1][:90])
    _check("断路器打开被单独识别",
           not cases["breaker"][0] and "断路器" in cases["breaker"][1],
           cases["breaker"][1][:90])
    _check("HTTP 4xx 带上后端原话",
           not cases["http_4xx"][0] and "403" in cases["http_4xx"][1]
           and "RLS" in cases["http_4xx"][1],
           cases["http_4xx"][1][:90])
    _check("传输失败被单独识别",
           not cases["transport"][0] and "传输" in cases["transport"][1],
           cases["transport"][1][:90])
    _check("成功路径 ok=True", cases["ok"][0], cases["ok"][1][:90])

    reasons = [v[1] for k, v in cases.items() if k != "ok"]
    _check(f"四种失败给出四句【互不相同】的话({len(set(reasons))}/4)",
           len(set(reasons)) == 4,
           "有两种失败说了同一句 —— 那就等于没有分开")


def test_env_presence_never_leaks_a_value():
    """凭证只报存在性。这是硬约束,不是风格。"""
    import os
    saved = os.environ.get("SUPABASE_KEY")
    os.environ["SUPABASE_KEY"] = "sb-secret-do-not-leak-0123456789"
    try:
        p = W.env_presence()
        _check("env_presence 只返回布尔",
               all(isinstance(v, bool) for v in p.values()), str(p))
        _check("值不出现在任何字段里",
               "sb-secret-do-not-leak-0123456789" not in repr(p), repr(p)[:80])
    finally:
        os.environ.pop("SUPABASE_KEY", None)
        if saved is not None:
            os.environ["SUPABASE_KEY"] = saved


def _run_recompute(n_symbols: int, n_days: int):
    """跑一次 `recompute_all`,给 upsert 装探针。返回 (结果, 探针记录)。"""
    import asyncio

    import src.api.store as store
    from src.data.market.single_source import SeriesSource

    calls: list[tuple] = []

    async def spy(table, rows, on_conflict=None):             # noqa: ANN001
        calls.append((table, len(rows)))
        return True

    from datetime import date, timedelta
    d0 = date(2024, 1, 1)
    days = [(d0 + timedelta(days=i)).isoformat() for i in range(n_days)]
    panel = _panel({f"S{i}": n_days for i in range(n_symbols)}, days)

    async def fake_fetch(start, *, source=W.PANEL_SOURCE):    # noqa: ANN001
        return panel, SeriesSource("binance_hist", n_symbols * n_days,
                                   days[0], days[-1], n_symbols)

    orig_fetch, orig_upsert = W.fetch_panel, store.supabase_upsert_table
    W.fetch_panel, store.supabase_upsert_table = fake_fetch, spy
    try:
        res = asyncio.new_event_loop().run_until_complete(W.recompute_all(days[0]))
    finally:
        W.fetch_panel, store.supabase_upsert_table = orig_fetch, orig_upsert
    return res, calls


def test_refusal_is_degraded_not_ok_and_not_error():
    """拒绝 ≠ 失败 ≠ 成功 —— 三个状态,三个字。"""
    refused = W.RecomputeResult(False, True, 0, None, None, "标的不足")
    errored = W.RecomputeResult(False, False, 0, None, None, "upsert 返回 False")
    good = W.RecomputeResult(True, False, 1693, "p", None)
    _check("拒绝 → degraded", refused.as_payload()["status"] == "degraded",
           str(refused.as_payload()))
    _check("失败 → error", errored.as_payload()["status"] == "error",
           str(errored.as_payload()))
    _check("成功 → ok", good.as_payload()["status"] == "ok", str(good.as_payload()))
    _check("拒绝带着原因走", refused.as_payload().get("reason") == "标的不足")
    _check("成功不带 reason 字段", "reason" not in good.as_payload())


# ── 契约回归 ──────────────────────────────────────────────────────────────────

def test_vec_full_is_a_positional_array_not_a_dict():
    """S-233 回归。RPC 用 `jsonb_array_elements_text(vec_full) with ordinality`
    按下标 join,所以这一列是**有序数组**;`to_vec_full()` 返回的是 dict。
    写者若把 dict 塞进去,邻居查询会静默降级而不报错。"""
    sv = StateVector(d="2025-01-01", values={"cis_mean": 1.0, "vol_mkt": -0.5})
    row = build_rows_for_upsert([sv], zscore_pass="t")[0]
    _check("vec_full 是 list", isinstance(row["vec_full"], list), type(row["vec_full"]).__name__)
    _check("vec_full 长度 = 24", len(row["vec_full"]) == 24, str(len(row["vec_full"])))
    _check("vec_full 按 DIMS 顺序定位",
           row["vec_full"][DIMS.index("cis_mean")] == 1.0
           and row["vec_full"][DIMS.index("vol_mkt")] == -0.5)
    _check("未测量位是 None 而不是 0.0",
           row["vec_full"][DIMS.index("corr_mean")] is None,
           str(row["vec_full"][DIMS.index("corr_mean")]))
    _check("zscore_pass 被戳上 (S-232)", row["zscore_pass"] == "t")


def test_unwired_dims_are_out_of_the_denominator():
    """S-231:完整度必须在【可达到】的总体上测。

    ⚠️ 这条守卫**测不到**"这三维真的没有表" —— 那要连 Supabase,而一个
    需要凭证才能跑的关卡在没有凭证的机器上会常红。它能测的是:名单是合法的
    维名、确实被排除出分母、而且分母本身可以被读出来。
    「没有源」这个事实由 S-245 的台账条目和 docstring 承载,不由这条测试承载。
    """
    _check("UNWIRED_DIMS ⊆ DIMS", UNWIRED_DIMS <= set(DIMS), str(UNWIRED_DIMS - set(DIMS)))
    live = [k for k in DIMS if not k.startswith("_reserved") and k not in UNWIRED_DIMS]
    full = StateVector(d="x", values={k: 0.0 for k in live})
    _check(f"填满可达的 {len(live)} 维 → completeness = 1.0",
           full.source_completeness == 1.0, str(full.source_completeness))
    _check("分母可被单独读出", full.attainable_dims == len(live),
           f"{full.attainable_dims} vs {len(live)}")
    # 负控制:若某个未接线维被误算进分母,上面那条就会 <1.0。
    with_unwired = [k for k in DIMS if not k.startswith("_reserved")]
    _check("负控制:把未接线维算进分母会掉到 1.0 以下",
           len(with_unwired) > len(live)
           and round(len(live) / len(with_unwired), 4) < 1.0,
           "负控制没成立 —— UNWIRED_DIMS 可能是空集")


if __name__ == "__main__":
    print("── market_state_vectors 写者:单源 · 定盘 · 写前地板 (S-245) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED:")
        for f in _FAILURES:
            print(f"   - {f}")
        sys.exit(1)
    print("\n✓ 几何基底写者守卫全绿")
