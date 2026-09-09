"""S-323 —— 「拿到了一页」和「拿到了全部」是两个状态,HTTP 200 对它们的回答一样。

2026-09-08 线上实测,同一个缺陷两个实例:

  `deep_panel_symbols()`     库里 262 个符号,函数回 **2**。
  `coverage_report()`        合格行 1759,统计量算在**任意 1000 行切片**上。

机制:PostgREST 有服务端 `db-max-rows` 上限(默认 1000)。请求 `limit=100000`
时它**不报错、不给 4xx、不加警告**,只是回 1000 行和一个 200。调用方拿到一个
形状完全正常的列表,没有任何一个字段说「这是一页,不是全部」。

后果不是「少了点数据」,是**换了一个对象**:
  - 深盘 universe 从 262 元集合变成 2 元集合,而下游照跑照报 ok ——
    一个覆盖 2 个资产的成功,和覆盖 262 个的成功,输出完全一样;
  - `coverage_pct` 的分子分母被**同一次截断**同时改写,所以比值永远看着合理,
    没有任何一个数会显得离谱。**一个被截断的样本不会说自己被截断了。**

而这条教训**早就写在这个仓库里** —— `beta_core_paper._regime_history` 的
docstring,S-130,原话:「不要搬运你即将聚合的行。让数据库算聚合,行数上限
就够不着了,而不只是变大了」,连 `db-max-rows` 默认 1000 都注明了。写在
docstring 里,然后两个新站点照犯,S-318 我还把 `_cg_panel_loop` 接到了其中
一个被截断的函数上。

**知道一件事和把它编码进去是两个动作,只有第二个能活下来。**
所以它从 docstring 搬到这里。

判据:`src/` 里任何 PostgREST URL 字面量,`limit=` 不得超过 `PGRST_MAX_ROWS`。
超过它就是在要一个服务器永远不会给的行数 —— 那个数字本身是假的,而它读起来
像一个上限承诺。要全量就调 RPC 让库里聚合,或者显式分页。
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: PostgREST 的服务端行数上限。Supabase 默认 1000,我们不控制这个配置。
#: **它是上限不是建议** —— 请求更大的数不会得到更多行,只会得到一个假的自信。
PGRST_MAX_ROWS = 1000

#: 尚未迁移到 RPC / 显式分页的站点数。**只减不增。**
#: 2026-09-08 基线 5:`src/api/store.py` ×1(limit=5000,当前窗口实测 215 行,
#: 还没撞上限但数字是假的)、`src/data/vector/vdb_health.py` ×4(limit=2000)。
#: 调高这个数等于把一次截断重新定义成正常 —— 那正是这条守卫要挡的事。
TRUNCATION_BUDGET = 5

_LIMIT = re.compile(r"limit=(\d+)")

_FAILS: list[str] = []


def _check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}")
        if detail:
            print(f"      {detail}")
        _FAILS.append(label)


def _code_strings(path: pathlib.Path) -> list[str]:
    """模块里**不是 docstring** 的字符串字面量。

    必须排除 docstring:S-130 的教训正文里就写着 `limit=20000`,那是**在讲这个
    错误**,不是在犯它。一条把讲解算成违规的守卫,会逼人把讲解删掉 ——
    **守卫不该让文档变得危险。**
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None) or []
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings):
            out.append(node.value)
    return out


def t_no_postgrest_read_asks_for_more_rows_than_the_server_will_give():
    offenders: list[str] = []
    for f in sorted((ROOT / "src").rglob("*.py")):
        try:
            txt = f.read_text(encoding="utf-8")
        except Exception:                                    # noqa: BLE001
            continue
        if "rest/v1" not in txt:
            continue
        for s in _code_strings(f):
            for m in _LIMIT.finditer(s):
                n = int(m.group(1))
                if n > PGRST_MAX_ROWS:
                    offenders.append(f"{f.relative_to(ROOT)} limit={n}")

    n = len(offenders)
    _check(
        f"要求超过服务端上限的读:{n} 处 ≤ 预算 {TRUNCATION_BUDGET}",
        n <= TRUNCATION_BUDGET,
        "新增了截断站点 —— " + "; ".join(sorted(offenders)),
    )
    _check(
        "预算只减不增(基线 5)",
        TRUNCATION_BUDGET <= 5,
        f"TRUNCATION_BUDGET={TRUNCATION_BUDGET} 被调高了 —— "
        "调高它等于把一次截断重新定义成正常",
    )
    if n < TRUNCATION_BUDGET:
        print(f"      ↓ 还剩 {n} 处,可把 TRUNCATION_BUDGET 收到 {n}")


def t_the_two_fixed_call_sites_aggregate_in_the_database():
    """两个已修站点必须**通过 RPC 聚合**,不能悄悄退回拉行。

    只盯 `limit=` 的守卫挡不住这个:退回去的写法可以完全不带 limit,
    然后拿默认的 1000 行 —— **默认值也是一个上限,而且它不写在代码里。**
    """
    pairs = [
        ("src/data/market/deep_panel_collector.py",
         "deep_panel_symbol_list", "deep_panel_symbols"),
        ("src/data/signals/forward_return_backfill.py",
         "forward_return_coverage", "coverage_report"),
    ]
    for rel, rpc, fn in pairs:
        txt = (ROOT / rel).read_text(encoding="utf-8")
        _check(f"{fn}() 走 RPC `{rpc}`", f'"{rpc}"' in txt,
               f"{rel} 里找不到 {rpc} —— 可能退回了拉行去重")


def t_deep_panel_symbols_is_three_valued():
    """`None`(没读到)不得和 `[]`(读通了是空的)折成一个值。

    第一轮修复正是在这里翻的车:日志里区分了两者,`return []` 又把区分丢掉,
    于是 `_deep_panel_loop` 报 `no deep-panel symbols resolved` ——
    一句话同时 covers「Supabase 没应答」(等下一轮)和「面板真空了」(改配置)。
    **在修「两个状态一个表示」的补丁里,又做了一次「两个状态一个表示」。**
    """
    import asyncio as _a
    import inspect

    from src.data.market import deep_panel_collector as dpc

    ann = str(inspect.signature(dpc.deep_panel_symbols).return_annotation)
    _check("deep_panel_symbols 声明可能返回 None", "None" in ann,
           f"返回标注是 {ann} —— 三值必须写进签名,否则调用方不会去分")

    # ⚠️ S-323q:这个 mock 原来打在 `store.supabase_rpc` 上。S-323m 把读取的
    # 接缝换成了 `rpc_with_detail`(为了让错误信息带上真实状态码与 body),
    # 于是 mock 打空了 —— 测试跑的是**没有凭据的真实路径**,
    # 两条断言都不再测它们声称要测的东西,而其中一条**因为巧合仍然是绿的**
    # (`not_configured` 也返回 None)。
    #
    # **一个打在旧接缝上的 mock,不会报错,只会安静地测别的东西。**
    # 换接缝时必须同时换 mock —— 这和「豁免不会自己过期」是同一类。
    import src.api.rpc_diagnostics as _rd

    async def _unreachable(fn_name, payload=None):
        return None, {"fn": fn_name, "outcome": "no_response",
                      "status": None, "body": None}

    async def _empty(fn_name, payload=None):
        return [], {"fn": fn_name, "outcome": "ok", "status": 200, "n_rows": 0}

    orig = _rd.rpc_with_detail
    try:
        _rd.rpc_with_detail = _unreachable
        _check("RPC 不通 → None(不是 [])",
               _a.run(dpc.deep_panel_symbols()) is None,
               "读不到被当成了「面板是空的」")
        _rd.rpc_with_detail = _empty
        _check("RPC 通但零行 → [](不是 None)",
               _a.run(dpc.deep_panel_symbols()) == [],
               "真的空被当成了「读不到」")
    finally:
        _rd.rpc_with_detail = orig

    # 两个状态在**报错文本**里也必须分开 —— 一个 None 传到下游若仍渲染成
    # 「面板空了」,三值就白分了。
    src = (ROOT / "src/data/market/deep_panel_collector.py").read_text(encoding="utf-8")
    _check("collect_deep_panel 对 None 与 [] 分别措辞",
           "没读到" in src and "读通了,但是空的" in src,
           "两个分支的文案没有分开 —— 读的人两边都不能动")


def t_the_overlap_window_can_reach_the_hole_it_has_to_repair():
    """固定 14 天的重叠窗**同时是一个上限**:循环永远修不了 14 天以外的洞。

    实测 2026-09-08:洞 21 天(08-18 起每天只进 1–4 个标的),固定窗口够不着,
    只能人手跑一次。**一个需要人手补的自动循环,下次出事还是要人手。**

    窗口改为从 `latest` 的**中位数**推。用 min 会被一个 2017 年就下架的符号
    绑架,把窗口永久钉在上限 —— 那是「一个离群点决定全局策略」,和覆盖率
    被 2 个标的的分母绑架是同一个形状。
    """
    import asyncio as _a
    import datetime as _dt

    import src.api.store as _store
    from src.data.market import deep_panel_collector as dpc

    today = _dt.date.today()

    def _state(days_ago: int, n: int = 262, fresh: int = 2) -> list[dict]:
        return [{"symbol": f"S{i}", "n_rows": 100,
                 "latest": (today if i < fresh
                            else today - _dt.timedelta(days=days_ago)).isoformat()}
                for i in range(n)]

    seen: dict = {}
    orig_fetch, orig_rpc = dpc._fetch_one, _store.supabase_rpc

    async def _stub(sym, days):
        seen["days"] = days
        return sym, [], "stub"

    def _window(rows: list[dict]) -> int:
        async def _rpc(name, payload=None):
            return rows
        _store.supabase_rpc = _rpc
        _a.run(dpc.collect_deep_panel())
        return seen["days"]

    try:
        dpc._fetch_one = _stub
        _check("洞 21 天 → 窗口伸到 23 天", _window(_state(21)) == 23,
               f"窗口 {seen.get('days')} —— 够不到的窗口等于没有自愈")
        _check("没有洞 → 窗口留在 14 天", _window(_state(0)) == 14,
               f"窗口 {seen.get('days')} —— 无事也全量拉是浪费")
        _outlier = _state(0)
        _outlier[5]["latest"] = "2017-01-01"
        _check("一个 2017 的离群点不绑架窗口", _window(_outlier) == 14,
               f"窗口 {seen.get('days')} —— 用了 min 而不是中位数?")
    finally:
        dpc._fetch_one, _store.supabase_rpc = orig_fetch, orig_rpc


def main() -> int:
    for fn in (t_no_postgrest_read_asks_for_more_rows_than_the_server_will_give,
               t_the_two_fixed_call_sites_aggregate_in_the_database,
               t_deep_panel_symbols_is_three_valued,
               t_the_overlap_window_can_reach_the_hole_it_has_to_repair):
        print(f"\n▸ {fn.__name__}")
        fn()
    print()
    if _FAILS:
        print(f"✗ {len(_FAILS)} 条失败")
        return 1
    print("✓ 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
