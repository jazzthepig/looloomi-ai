"""S-895 阶段 4 —— 预热循环**只热本地缓存**,不打外网。

**这一份守的是什么(一句话):** 预热循环曾经每 4 分钟把 25 条面板路径各请求一遍,
其中 13 条会**穿透外网**(CoinGecko / DeFiLlama / EODHD / 场所 API / RSS)。
预热是**缓存维护职责,不是采集职责**(SPINE.md:184-213)—— 预热顺手把采集做了 =
有了第二条活路,而那条活路不在任何 `loop_attempt` 的记账里 ⇒「今天打了多少」
永远少一块(SPINE.md:170-174:「一个因错误理由变绿的检查,比红的更坏」)。

**为什么必须是「构造」而不是「附近的字符串」:** 本文件里所有匹配都走 AST
(`tests/_source.py::code_only` 那条规矩的同一族):匹配源码里的一个词,注释和
docstring 就能满足它,而解释 bug 的那段注释永远紧挨着修 bug 的那段代码 ⇒ 守���会
跟它要守的东西**反相关**。

**四条判据:**
1. **构造**:预热循环遍历的那个名字必须��� `_WARM_PATHS_LOCAL`,而且循环体里
   不得再出现旧的全集名字 `_WARM_PATHS`(那个名字本身就是「把它合回去」的邀请)。
2. **集合纪律**:两张表互不相交,并集 = 冻结的那 25 条(不多不少)⇒ 没有人能悄悄
   少登记一条;每条 EXTERNAL 都必须写清楚它会打到哪一家、代码在哪一行。
3. **登记必须跟代码对得上**:每条路径的第一跳必须是**路由装饰器下面那个函数**
   (从 AST 里读,不是从 app 对象里读 —— 那是另一种真相来源)。
4. **分类必须是真的**:EXTERNAL 的调用链里必须真的有一跳引用了网络入口
   (HTTP 客户端 / 取数函数);LOCAL 的调用链里**一跳都不许有**。

**诚实说明:** 第 4 条的调用链是**手工登记**的(表在下面)。它不是自动推导的 ——
自动推导需要全仓库调用图,而同名函数跨模块解析会炸(实测:`get`/`report`/`main`
这类名字在仓库里有几百个同名候选)。所以这一条的性质是「登记 + 校验」:
登记写错了(函数改名、链路改了、分类反了)测试会红;但它守不住「有人把链路
藏起来了」。第 1–3 条才是硬的。
"""
from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MAIN_PY = ROOT / "src/api/main.py"

# ── 冻结的清单(S-895 阶段 4 改之前的全部 25 条)──────────────────────────────
# 改之前是一个 `_WARM_PATHS` 元组;改成两张表之后,**并集必须还是这 25 条** ——
# 少一条就是有人把一条路径从登记里拿掉了(「拿掉」= 不再被预热,也不再被看见)。
FROZEN_WARM_PATHS = (
    "/api/v1/protocols/universe",
    "/api/v1/portfolio/books?mode=forward",
    "/api/v1/portfolio/books?mode=replay",
    "/api/v1/proof/books",
    "/api/v1/cis/attribution?symbol=BTC&limit=8",
    "/api/v1/market/economic-indicators",
    "/api/v1/vc/portfolios",
    "/api/v1/signals/dingge-board",
    "/api/v1/trading/metrics",
    "/api/v1/cis/universe",
    "/api/v1/cis/v2",
    "/api/v1/market/crowd-clock",
    "/api/v1/market/macro-pulse",
    "/api/v1/macro/brief",
    "/api/v1/defi/overview",
    "/api/v1/intelligence/macro-events",
    "/api/v1/vc/funding-rounds?limit=400&days=180",
    "/api/v1/strategies",
    "/api/v1/strategies/open-source",
    "/api/v1/signals/feed",
    "/api/v1/signals/performance?method=official",
    "/api/v1/signals/journal?limit=30&offset=0&status=all&method=official",
    "/api/v1/proof/anchors",
    "/api/v1/portfolio/risk-meter",
    "/api/v1/market/earnings-calendar?symbols=AAPL,NVDA,MSFT,AMZN,GOOGL&days_ahead=30",
)

# ── 网络入口:「这一跳会打外网」的判据 ───────────────────────────────────────
# 一个函数只要引用了下面任何一个名字,它就会(直接或间接)发 HTTP。
_NETWORK_MARKERS = frozenset({
    # HTTP 客户端本身
    "httpx", "requests", "aiohttp", "urlopen", "urllib", "AsyncClient",
    # 本仓库自己的 client 取法
    "_get_cg_client", "_get_misc_client", "_get_llama_client", "_client",
    # 取数函数(它们内部就是上面那几个 client)
    "get_macro_pulse", "get_defi_overview", "get_eodhd_macro_indicators",
    "get_eodhd_earnings_calendar", "get_cg_vc_portfolios", "get_vc_raises",
    "fetch_all_macro_events", "fetch_all_protocol_tvls", "fetch_cg_markets",
    "calculate_cis_universe",
})


# ── 调用链登记 ───────────────────────────────────────────────────────────────
# (相对路径, 函数名) —— 每一跳都必须真的存在于代码里。
_EXTERNAL_CHAINS = {
    "/api/v1/protocols/universe": [
        ("src/api/routers/intelligence.py", "get_protocols"),
        ("src/data/market/protocol_engine.py", "get_protocol_universe"),
        ("src/data/market/protocol_engine.py", "fetch_all_protocol_tvls"),
    ],
    "/api/v1/market/economic-indicators": [
        ("src/api/routers/market.py", "economic_indicators"),
        ("src/data/market/data_layer.py", "get_economic_dashboard"),
        ("src/data/market/data_layer.py", "get_eodhd_macro_indicators"),
    ],
    "/api/v1/vc/portfolios": [
        ("src/api/routers/intelligence.py", "get_vc_portfolios"),
        ("src/data/market/data_layer.py", "get_cg_vc_portfolios"),
    ],
    "/api/v1/signals/dingge-board": [
        ("src/api/main.py", "dingge_board"),
        ("src/data/signals/dingge_rwa.py", "scan_live"),
        ("src/data/signals/dingge_rwa.py", "_client"),
    ],
    "/api/v1/cis/universe": [
        ("src/api/routers/cis.py", "get_cis_universe"),
        ("src/api/routers/cis.py", "_build_cis_universe"),
        ("src/data/cis/cis_provider.py", "fetch_cg_markets"),
    ],
    "/api/v1/market/crowd-clock": [
        ("src/api/routers/market.py", "crowd_clock"),
        ("src/data/market/crowd_clock.py", "get_crowd_clock"),
    ],
    "/api/v1/market/macro-pulse": [
        ("src/api/routers/market.py", "macro_pulse"),
        ("src/data/market/data_layer.py", "get_macro_pulse"),
    ],
    "/api/v1/macro/brief": [
        ("src/api/routers/macro.py", "get_macro_brief"),
    ],
    "/api/v1/defi/overview": [
        ("src/api/routers/market.py", "defi_overview"),
        ("src/data/market/data_layer.py", "get_defi_overview"),
    ],
    "/api/v1/intelligence/macro-events": [
        ("src/api/routers/intelligence.py", "get_macro_events"),
    ],
    "/api/v1/vc/funding-rounds?limit=400&days=180": [
        ("src/api/routers/intelligence.py", "get_funding_rounds"),
    ],
    "/api/v1/portfolio/risk-meter": [
        ("src/api/routers/cis.py", "get_risk_meter"),
        ("src/api/routers/cis.py", "get_cis_universe"),
        ("src/api/routers/cis.py", "_build_cis_universe"),
    ],
    "/api/v1/market/earnings-calendar?symbols=AAPL,NVDA,MSFT,AMZN,GOOGL&days_ahead=30": [
        ("src/api/routers/market.py", "earnings_calendar"),
        ("src/data/market/data_layer.py", "get_eodhd_earnings_calendar"),
    ],
}

_LOCAL_CHAINS = {
    "/api/v1/portfolio/books?mode=forward": [
        ("src/api/routers/portfolio_builder.py", "portfolio_books"),
        ("src/api/routers/portfolio_builder.py", "_basis"),
        ("src/data/accounting/combine.py", "load_basis"),
    ],
    "/api/v1/portfolio/books?mode=replay": [
        ("src/api/routers/portfolio_builder.py", "portfolio_books"),
        ("src/api/routers/portfolio_builder.py", "_basis"),
        ("src/data/accounting/combine.py", "load_basis"),
    ],
    "/api/v1/proof/books": [
        ("src/api/routers/ohlcv.py", "proof_books"),
        ("src/data/accounting/proof.py", "proof_rows"),
    ],
    "/api/v1/cis/attribution?symbol=BTC&limit=8": [
        ("src/api/routers/cis.py", "cis_signal_attribution"),
        ("src/data/cis/signal_attribution.py", "track_record"),
    ],
    "/api/v1/trading/metrics": [
        ("src/api/routers/trading.py", "get_metrics"),
        ("src/api/routers/trading.py", "_compute_metrics"),
    ],
    "/api/v1/cis/v2": [
        ("src/api/routers/cis.py", "cis_v2_shadow"),
        ("src/data/cis/v2_view.py", "latest_view"),
    ],
    "/api/v1/strategies": [
        ("src/api/routers/strategies.py", "list_strategies"),
        ("src/api/routers/strategies.py", "_current_regime"),
    ],
    "/api/v1/strategies/open-source": [
        ("src/api/routers/strategies.py", "list_open_source"),
    ],
    "/api/v1/signals/feed": [
        ("src/api/routers/signals.py", "get_signal_feed"),
    ],
    "/api/v1/signals/performance?method=official": [
        ("src/api/routers/signals.py", "get_signal_performance"),
    ],
    "/api/v1/signals/journal?limit=30&offset=0&status=all&method=official": [
        ("src/api/routers/signals.py", "get_signal_journal"),
    ],
    "/api/v1/proof/anchors": [
        ("src/api/routers/ohlcv.py", "proof_anchors"),
    ],
}


# ── 小工具 ───────────────────────────────────────────────────────────────────
def _main_tree() -> ast.Module:
    return ast.parse(MAIN_PY.read_text(encoding="utf-8"))


def _module_level(tree: ast.Module, name: str) -> ast.AST | None:
    """模块级赋值 `name = (...)` 的值节点。"""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    return node.value
    return None


def _tuple_strings(node: ast.AST | None) -> list[str]:
    """元组里的字符串常量(只取字面量,不看表达式)。"""
    if not isinstance(node, ast.Tuple):
        return []
    out = []
    for elt in node.elts:
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            out.append(elt.value)
    return out


def _func(tree: ast.Module, name: str) -> ast.AST | None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _referenced_names(fn: ast.AST) -> set[str]:
    """函数体里引用到的名字(Name + Attribute.attr)—— AST,不是原文匹配。"""
    out: set[str] = set()
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Name):
            out.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            out.add(sub.attr)
    return out


def _route_handlers() -> dict[str, tuple[str, str]]:
    """路由路径 → (相对文件, 函数名)。从 AST 的装饰器读出来 —— 不 import app。"""
    out: dict[str, tuple[str, str]] = {}
    for py in sorted((ROOT / "src/api").rglob("*.py")):
        rel = str(py.relative_to(ROOT))
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                    continue
                if dec.func.attr not in ("get", "post", "put", "delete"):
                    continue
                if not dec.args or not isinstance(dec.args[0], ast.Constant):
                    continue
                path = dec.args[0].value
                if isinstance(path, str) and path.startswith("/api/"):
                    out.setdefault(path, (rel, node.name))
    return out


# ── 判据 1:构造 ─────────────────────────────────────────────────────────────
def test_warm_loop_iterates_the_local_table_only():
    """预热循环遍历的必须是 `_WARM_PATHS_LOCAL`,而且循环体里不得再有旧的全集名字。"""
    tree = _main_tree()
    loop = _func(tree, "_public_cache_warm_loop")
    assert loop is not None, "预热循环不见了"

    iterated = []
    for node in ast.walk(loop):
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Name):
            iterated.append(node.iter.id)
    assert iterated == ["_WARM_PATHS_LOCAL"], (
        f"预热循环遍历的是 {iterated} —— 只能是 _WARM_PATHS_LOCAL(会打外网的那张表不进预热)")
    assert "_WARM_PATHS" not in {n.id for n in ast.walk(loop) if isinstance(n, ast.Name)}, (
        "循环体里还在引用旧的全集 `_WARM_PATHS`")

    # 两张表都必须在,而且是元组常量
    assert isinstance(_module_level(tree, "_WARM_PATHS_LOCAL"), ast.Tuple), "_WARM_PATHS_LOCAL 必须是模块级元组"
    assert isinstance(_module_level(tree, "_WARM_PATHS_EXTERNAL"), ast.Tuple), "_WARM_PATHS_EXTERNAL 必须是模块级元组"


# ── 判据 2:集合纪律 ─────────────────────────────────────────────────────────
def test_the_two_tables_are_disjoint_and_cover_everything_that_used_to_be_warmed():
    tree = _main_tree()
    local = _tuple_strings(_module_level(tree, "_WARM_PATHS_LOCAL"))
    ext_node = _module_level(tree, "_WARM_PATHS_EXTERNAL")
    ext_paths: list[str] = []
    reasons: dict[str, str] = {}
    assert isinstance(ext_node, ast.Tuple)
    for elt in ext_node.elts:
        assert isinstance(elt, ast.Tuple) and len(elt.elts) == 2, "EXTERNAL 的每一项都必须是 (路径, 理由)"
        p, r = elt.elts
        assert isinstance(p, ast.Constant) and isinstance(p.value, str)
        assert isinstance(r, ast.Constant) and isinstance(r.value, str)
        ext_paths.append(p.value)
        reasons[p.value] = r.value

    assert not (set(local) & set(ext_paths)), f"两张表有交集:{set(local) & set(ext_paths)}"
    assert len(local) == len(set(local)) and len(ext_paths) == len(set(ext_paths)), "同一张表里有重复"
    assert set(local) | set(ext_paths) == set(FROZEN_WARM_PATHS), (
        "并集必须还是改之前那 25 条 —— 少一条 = 有人把一条路径从登记里拿掉了;"
        f"多出来的:{set(local) | set(ext_paths) - set(FROZEN_WARM_PATHS)};"
        f"少了的:{set(FROZEN_WARM_PATHS) - (set(local) | set(ext_paths))}")
    assert set(ext_paths) == set(_EXTERNAL_CHAINS), "EXTERNAL 表与本文件的登记对不上"
    assert set(local) == set(_LOCAL_CHAINS), "LOCAL 表与本文件的登记对不上"

    for p, why in reasons.items():
        assert why.strip(), f"{p} 没写理由"
        assert ".py" in why, (
            f"{p} 的理由必须指到代码(哪个文件/哪一行),不能只写「它要花额度」——"
            f"否则这一列会变成一句空话,下一个人照着加回预热清单")
        assert "api/v1" not in why, f"{p} 的理由里混进了路径"

    # LOCAL 的路径条数比 EXTERNAL 少是正常的(预热清单本来就短),但不能空。
    assert local, "LOCAL 表空了 —— 预热循环会一条都不请求"


# ── 判据 3:登记必须跟代码对得上(第一跳 = 路由装饰器下面那个函数)────────────
def test_every_registered_path_still_resolves_to_the_handler_we_recorded():
    routes = _route_handlers()
    for table in (_EXTERNAL_CHAINS, _LOCAL_CHAINS):
        for path, chain in table.items():
            base = path.split("?")[0]
            assert base in routes, f"{path} 在代码里已经不是一条路由了 —— 登记要跟着改"
            rel, fn = routes[base]
            assert (rel, fn) == chain[0], (
                f"{path} 的 handler 变了:{rel}:{fn} ≠ 登记的 {chain[0]}")


# ── 判据 4:分类必须是真的 ───────────────────────────────────────────────────
def test_external_paths_really_do_reach_the_network():
    for path, chain in _EXTERNAL_CHAINS.items():
        hits = []
        for rel, fn in chain:
            f = ROOT / rel
            assert f.exists(), f"{path} 的链路指向不存在的文件 {rel}"
            node = _func(ast.parse(f.read_text(encoding="utf-8")), fn)
            assert node is not None, f"{path} 的链路指向不存在的函数 {rel}:{fn}"
            names = _referenced_names(node)
            if names & _NETWORK_MARKERS:
                hits.append(f"{rel}:{fn} → {sorted(names & _NETWORK_MARKERS)}")
        assert hits, (
            f"{path} 被登记成 EXTERNAL,但它的链路里一���能碰到网络入口 —— "
            f"要么它其实不外呼(那就该挪进 LOCAL),要么链路漏了一跳(登记要补)")


def test_local_paths_do_not_reach_the_network():
    for path, chain in _LOCAL_CHAINS.items():
        for rel, fn in chain:
            f = ROOT / rel
            assert f.exists(), f"{path} 的链路指向不存在的文件 {rel}"
            node = _func(ast.parse(f.read_text(encoding="utf-8")), fn)
            assert node is not None, f"{path} 的链路指向不存在的函数 {rel}:{fn}"
            hit = _referenced_names(node) & _NETWORK_MARKERS
            assert not hit, (
                f"{path} 被登记成 LOCAL(预热它 = 预热循环打外网),但 {rel}:{fn} 引用了 {sorted(hit)} "
                f"—— 它要么挪进 EXTERNAL,要么这条链路登记过时了")
