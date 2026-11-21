"""CoinGecko 调用面的**形状守卫**(S-895 阶段 0/2)。

## 为什么要有这个测试

2026-11-17 起 CoinGecko 的**超额调用要钱**。S-894 建了闸门
(`src/data/market/cg_guard.py`),但闸门只罩住了 **11 个文件** —— 全仓库还有
**13 处裸 client** 直接打 CoinGecko,它们:

- 不受预算约束(闸门对它们是透明的),
- 不受熔断保护(上游 429 了它们照打),
- **不计入 `used_today`** ⇒ `/internal/cg-quota` 报的数字**从来不是**真实花销。

最后一条最要命:`docs/SPINE.md:170-174` 说「一个因错误理由变绿的检查,比红的
更坏 —— 红的会被修,绿的会被信任」。那个读数当时就是**因错误理由变绿**的。

## 三种 client 类型(判定写在代码里,不是嘴上说说)

| 类型 | 判据 | 允许吗 |
|---|---|---|
| `gated` | 这个请求用的 client 来自 `GuardedCGClient` / `_get_cg_client()` | ✅ 唯一正常形态 |
| `injected` | client 是**别的文件**注入的 | ✅ 注入方必须走闸门(登记在册) |
| `bare` | 上面都不是 | ⚠️ **必须在同一个文件里 `note_unbudgeted_call` 记账**,且登记在册 |

`bare` 不是「忘了改」,是**过渡期**。阶段 2 把它们收口进闸门之后,登记就要撤
(SPINE:184-213「一个能力只能有一条活路」—— 登记了就要真退役)。

**判定只看 AST,不看注释** —— 注释里写一句「以后接闸门」不算接了。

## 覆盖表 = 新增端点必须改这张表

`ALLOWED_BARE_CALL_SITES` 是**闸外文件 → 端点 → 理由**。
新加一个 CoinGecko 调用点,必须在这张表里登记 —— 那是一次**有意识的动作**,
而不是「顺手加一行请求」。

登记在册的 `bare` 里只有两个文件是**永久例外**:同步 `requests` 调用点。
`GuardedCGClient` 是 `httpx.AsyncClient` 的**子类**,同步代码用不了。
它们永远在闸门外,只能靠记账保证可见。
"""
from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── 扫描范围 ─────────────────────────────────────────────────────────────────

#: 扫 `src/`,但**排除**研究区 —— 那些脚本是一次性跑的挖掘脚本,不在生产的
#: 取数路径上(它们的额度消耗是**开发期**的,不是线上账单的)。
SCAN_ROOT = ROOT / "src"
SCAN_SKIP_DIRS = {"research"}

#: CoinGecko 的路径根。命中其一 ⇒ 这个请求是打 CoinGecko 的。
#: 少了这一层,`router.get("/api/v1/market/coingecko-markets")` 这种
#: **我们自己**的路由也会被算成 CoinGecko 调用。
CG_PATH_ROOTS = {
    "coins", "simple", "global", "ohlc", "rwas", "companies",
    "public_treasury", "derivatives", "search", "exchanges", "onchain",
    "market_chart",
}

#: 提到这些 ⇒ 这个请求是打 CoinGecko 的(URL 是拼出来的,抓不到字面路径)。
CG_BASE_MARKERS = (
    "CG_PRO_BASE", "CG_PUBLIC_BASE", "CG_BASE", "_CG_BASE", "_CG_PRO",
    "_cg_base()", "cg_base", "api.coingecko.com",
)

#: `/coins/` 后面这些是**子路径**,不是 coin id —— 不能把 `/coins/markets`
#: 归一成 `/coins/{id}`(那是两个不同的端点)。
COIN_SUBPATHS = {"markets", "list", "categories", "new", "trending"}

_PATH_RE = re.compile(r"/[A-Za-z0-9_{}.%-]+(?:/[A-Za-z0-9_{}.%-]+)*")
_PLACEHOLDER_RE = re.compile(r"\{[^{}]*\}")


def _normalize(path: str) -> str:
    """`/coins/{coin_id}` → `/coins/{id}`;砍掉 host 与 `/api/v3`。"""
    s = path
    if "://" in s:
        s = s.split("://", 1)[1]
        s = s.split("/", 1)[1] if "/" in s else ""
    segs = [p for p in s.split("/") if p]
    # 砍掉 host 段(第一段带 "." 的就是主机名)
    if segs and "." in segs[0]:
        segs = segs[1:]
    # 砍掉 `api/v3`
    if len(segs) >= 2 and segs[0] == "api" and segs[1] == "v3":
        segs = segs[2:]
    s = "/" + "/".join(segs)
    parts = s.split("/")
    if len(parts) >= 3 and parts[1] == "coins" and parts[2] not in COIN_SUBPATHS:
        parts[2] = "{id}"
    # 所有占位符统一成 `{id}` —— `/public_treasury/{cid}` 与
    # `/companies/public_treasury/{coin}` 是同一个额度池。
    s = "/".join(parts)
    s = _PLACEHOLDER_RE.sub("{id}", s)
    s = s.split("?", 1)[0]
    return s


def _paths_in(segment: str) -> set[str]:
    """从一段调用源码里认出 CoinGecko 的路径。"""
    out: set[str] = set()
    for m in _PATH_RE.finditer(segment):
        cand = _normalize(m.group(0))
        segs = [p for p in cand.split("/") if p]
        if not segs:
            continue
        if segs[0] in CG_PATH_ROOTS:
            out.add(cand)
    return out


def _is_cg_call(segment: str) -> bool:
    if any(marker in segment for marker in CG_BASE_MARKERS):
        return True
    return bool(_paths_in(segment))


class Site:
    """一个 CoinGecko 调用点。"""

    __slots__ = ("path", "line", "endpoint", "receiver", "kind")

    def __init__(self, path: str, line: int, endpoint: str, receiver: str, kind: str):
        self.path = path
        self.line = line
        self.endpoint = endpoint
        self.receiver = receiver
        self.kind = kind

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Site {self.path}:{self.line} {self.endpoint} {self.kind}>"


def _receiver(call: ast.Call) -> str:
    f = call.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
        return f.value.id
    return ""


def _is_get_cg_client(node: ast.AST) -> bool:
    """`_get_cg_client()` 这个调用。"""
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "_get_cg_client")


def _is_guarded_ctor(node: ast.AST) -> bool:
    """`GuardedCGClient(...)` 这个构造。"""
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Name) and f.id == "GuardedCGClient":
            return True
        if isinstance(f, ast.Attribute) and f.attr == "GuardedCGClient":
            return True
    return False


def _is_bare_ctor(node: ast.AST) -> bool:
    """`httpx.AsyncClient(...)` / `httpx.Client(...)`。"""
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr in ("AsyncClient", "Client"):
            v = f.value
            if isinstance(v, ast.Name) and v.id == "httpx":
                return True
    return False


def _assigned_kind(value: ast.AST) -> str:
    """一个赋值语句的右端是什么 client。"""
    if _is_get_cg_client(value) or _is_guarded_ctor(value):
        return "gated"
    if _is_bare_ctor(value):
        return "bare"
    return "unknown"


def scan_file(path: Path) -> list[Site]:
    """扫一个文件里的 CoinGecko HTTP 调用点。"""
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
    except Exception:
        return []
    rel = str(path.relative_to(ROOT))

    # 文件级事实:这个文件自己造了什么 client。
    file_constructs_bare = any(_is_bare_ctor(n) for n in ast.walk(tree))
    file_is_gated = any(
        (isinstance(n, ast.Call) and _is_get_cg_client(n))
        or (isinstance(n, ast.Name) and n.id == "GuardedCGClient")
        or (isinstance(n, ast.Attribute) and n.attr == "GuardedCGClient")
        for n in ast.walk(tree)
    )
    # 文件级事实:这个文件是不是**整个**都在打 CoinGecko。
    # (`requests.get(url, …)` 里 URL 是变量 —— 调用点本身看不出是哪个厂商,
    #  只能靠「这个文件有 CG 的 base」判断。)
    file_hits_cg = any(marker in text for marker in CG_BASE_MARKERS)

    out: list[Site] = []

    def visit(node: ast.AST, params: set[str], assigns: dict[str, str]) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = node.args
            names = {x.arg for x in list(a.args) + list(a.posonlyargs) + list(a.kwonlyargs)}
            if a.vararg:
                names.add(a.vararg.arg)
            if a.kwarg:
                names.add(a.kwarg.arg)
            # **继承**外层的参数与赋值 —— 闭包里的 `client` 就是外层那个。
            params = params | names
            assigns = dict(assigns)
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.AST):
            k = _assigned_kind(node.value)
            if k != "unknown":
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        assigns[tgt.id] = k
        if (isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None
                and _is_bare_ctor(node.value)):
            tgt = node.targets[0] if isinstance(node, ast.Assign) else node.target
            if isinstance(tgt, ast.Name):
                assigns[tgt.id] = "bare"
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if not isinstance(item.optional_vars, ast.Name):
                    continue
                ctx = item.context_expr
                if _is_bare_ctor(ctx):
                    assigns[item.optional_vars.id] = "bare"
                elif _is_guarded_ctor(ctx) or _is_get_cg_client(ctx):
                    assigns[item.optional_vars.id] = "gated"
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("get", "post", "put", "delete", "request")):
            seg = ast.get_source_segment(text, node) or ""
            # `requests.get(url, …)` —— URL 在变量里 ⇒ 调用点看不出厂商,
            # 只能靠「这个文件有 CG 的 base」判断。同步点永远在闸门外。
            is_requests_call = (isinstance(node.func.value, ast.Name)
                                and node.func.value.id in ("requests", "httpx")
                                and file_hits_cg)
            if _is_cg_call(seg) or is_requests_call:
                paths = _paths_in(seg)
                endpoint = sorted(paths)[0] if paths else "(dynamic)"
                recv = _receiver(node)
                # ── 判定这个请求的 client 是什么 ──────────────────────────
                if _is_get_cg_client(node.func.value):
                    kind = "gated"
                elif recv:
                    k = assigns.get(recv, "unknown")
                    if k in ("gated", "bare"):
                        kind = k
                    elif recv in params:
                        # 参数注入:注入方在**别的文件** ⇒ 外部注入;
                        # 注入方在**本文件** ⇒ 本文件造裸 client 就是裸的,
                        # 本文件走闸门就是闸内的。
                        if file_constructs_bare:
                            kind = "bare"
                        elif file_is_gated:
                            kind = "gated"
                        else:
                            kind = "injected"
                    else:
                        kind = "gated" if file_is_gated else "bare"
                else:
                    kind = "gated" if file_is_gated else "bare"
                out.append(Site(rel, node.lineno, endpoint, recv, kind))
        for child in ast.iter_child_nodes(node):
            visit(child, params, assigns)

    visit(tree, set(), {})
    return out


def scan_repo() -> dict[str, list[Site]]:
    out: dict[str, list[Site]] = {}
    for dirpath, dirnames, filenames in os.walk(SCAN_ROOT):
        dirnames[:] = [d for d in dirnames
                       if d not in SCAN_SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            p = Path(dirpath) / fn
            sites = scan_file(p)
            if sites:
                out[str(p.relative_to(ROOT))] = sites
    return out


# ── 登记在册 ─────────────────────────────────────────────────────────────────

#: 允许留在闸门外的文件 → (端点…, 理由)
#:
#: 两个**永久**例外是同步 `requests` 调用点 —— `GuardedCGClient` 是
#: `httpx.AsyncClient` 的子类,同步代码用不了。要收口它们得先把调用链改成
#: 异步,那是另一个改动。**在收口之前,它们必须靠记账保持可见。**
#: 其余是**过渡期**:阶段 1/2 收口进闸门之后,登记要跟着撤。
ALLOWED_BARE_CALL_SITES: dict[str, tuple[tuple[str, ...], str]] = {
    "src/data/market/exchange_data.py": (
        ("/simple/price", "/coins/{id}/market_chart"),
        "同步 `requests` 调用点 —— GuardedCGClient 是 async 子类,同步代码用不了",
    ),
    "src/analytics/mmi/mmi_index_v3.py": (
        ("/coins/{id}/market_chart",),
        "同步 `requests` 调用点(批处理脚本)—— 同上",
    ),
    # ⚠️ S-895 阶段 2 已撤的四条(收口进闸门/单一活路):
    #   `src/data/rwa/collect.py` · `src/data/cis/cis_provider.py` ·
    #   `src/data/market/deep_walk.py` · `src/data/market/global_history.py`
    # ⚠️ `src/api/routers/trading.py` **已撤** —— 阶段 1(S-895)收口进闸门。
    # 留着一条登记 = 一个已经不裸的文件继续占着「豁免」名额 ⇒ 白名单变永久豁免。
}

#: **覆盖表** —— CG 端点 → 允许调用它的文件 → 允许的 client 类型。
#:
#: 这张表是「新增端点必须改这张表」的地方(计划 §5.1)。没登记的端点
#: **一律不允许**出现在任何文件里 ⇒ 新开一个 CG 调用点必须显式登记,
#: 那是一次**有意识的动作**,而不是「顺手加一行请求」。
#:
#: 端点按 `tests/test_cg_call_sites.py::_normalize` 归一(占位符 → `{id}`)。
#: `(dynamic)` = URL 在变量里、调用点抓不到端点 —— 那时按**文件**登记。
#:
#: client 类型:
#:   `gated`    —— 闸门内(`GuardedCGClient` / `_get_cg_client()`)
#:   `injected` —— client 由别的文件注入,注入方必须走闸门
#:   `bare`     —— 闸门外(只允许两个永久同步例外)
#:
#: ⚠️ **同端点的多个查询形状不是重复**(`SPINE.md:188-191`「不能给出不同答案
#: ⇒ 是重复」):`/coins/markets` 有三个形状 —— 按 id、按 category、新上架。
#: 它们问的不是同一个问题,所以分别登记、各自保留。
#:
#: ⚠️ 这张表按**静态扫出的**端点登记。同步 `requests` 的两个永久例外
#: (`exchange_data.py` / `mmi_index_v3.py`)的 URL 在变量里 ⇒ 它们的端点登记在
#: `ALLOWED_BARE_CALL_SITES` 与 `DYNAMIC_ENDPOINT_SITES` 里,不在这里。
CG_ENDPOINT_COVERAGE: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # (端点, (允许的文件…, (允许的 client 类型…)))
    "/global": (
        ("src/data/market/data_layer.py",),
        ("gated",),
    ),
    "/global/market_cap_chart": (
        ("src/data/market/data_layer.py", "src/data/market/global_history.py"),
        ("gated",),
    ),
    "/coins/markets": (
        ("src/api/routers/cis.py",
         "src/data/market/cg_panel_sync.py",
         "src/data/market/data_layer.py"),
        ("gated", "injected"),
    ),
    "/coins/list": (
        ("src/data/market/data_layer.py", "src/data/market/perp_mcap_backfill.py"),
        ("gated",),
    ),
    "/coins/{id}": (
        ("src/data/market/data_layer.py",),
        ("gated",),
    ),
    "/coins/{id}/tickers": (
        ("src/data/market/data_layer.py",),
        ("gated",),
    ),
    "/coins/{id}/market_chart": (
        ("src/data/market/data_layer.py",),
        ("gated",),
    ),
    "/coins/{id}/ohlc/range": (
        ("src/data/market/data_layer.py", "src/data/market/deep_walk.py"),
        ("gated",),
    ),
    "/coins/{id}/market_chart/range": (
        ("src/data/market/data_layer.py",),
        ("gated",),
    ),
    "/coins/{id}/history": (
        ("src/data/market/data_layer.py",),
        ("gated",),
    ),
    "/coins/{id}/circulating_supply_chart": (
        ("src/data/market/data_layer.py",),
        ("gated",),
    ),
    "/coins/categories": (
        ("src/data/market/data_layer.py",),
        ("gated",),
    ),
    "/coins/categories/list": (
        ("src/data/market/data_layer.py",),
        ("gated",),
    ),
    "/simple/price": (
        ("src/api/routers/trading.py", "src/data/market/data_layer.py"),
        ("gated",),
    ),
    "/derivatives": (
        ("src/data/cis/positioning.py", "src/data/market/data_layer.py",
         "src/data/market/derivatives_market.py"),
        ("gated",),
    ),
    "/derivatives/exchanges/{id}": (
        ("src/data/market/data_layer.py",),
        ("gated",),
    ),
    "/exchanges/{id}/volume_chart/range": (
        ("src/data/market/exchange_volume.py",),
        ("gated",),
    ),
    "/rwas/markets": (
        ("src/data/market/data_layer.py", "src/data/rwa/collect.py"),
        ("gated",),
    ),
    "/rwas/issuers/list": (
        ("src/data/market/data_layer.py", "src/data/rwa/collect.py"),
        ("gated",),
    ),
    "/onchain/networks/{id}/tokens/{id}/top_holders": (
        ("src/data/market/data_layer.py",),
        ("gated",),
    ),
    "/public_treasury/{id}": (
        ("src/data/entity/writer.py",),
        ("injected",),
    ),
    "/companies/public_treasury/{id}": (
        ("src/data/entity/writer.py",),
        ("injected",),
    ),
    "/search/trending": (
        ("src/data/market/data_layer.py",),
        ("gated",),
    ),
}

#: URL 在变量里、**静态扫不出端点**的文件 → 端点由谁决定。
#:
#: 这些文件用的是**路径参数化**的写法(`client.get(f"{CG_BASE}{path}")`),
#: 端点在运行期才定 ⇒ 覆盖表按**文件**登记,并写明路径的来源。
#: 登记了不等于免检 —— 它们的 client 类型仍要过闸门。
DYNAMIC_ENDPOINT_SITES: dict[str, str] = {
    "src/data/market/cg_supply.py":
        "路径参数化:`fetch(path)` —— 端点由本文件的 `pick()` 决定"
        "(`/coins/list/new` + 逐币 `/coins/{id}/supply_breakdown`)",
    "src/data/market/token_holders.py":
        "路径参数化:`fetch(path)` —— 端点由本文件的 `choose()` 决定"
        "(只剩逐币 `holders_chart`;`/coins/list` 已收敛到 `data_layer.get_cg_coin_list`"
        " —— S-895 阶段 5)",
    "src/data/ops/news_feed.py":
        "路径参数化:`for path in (\"/news\", \"/insights\")` —— 两个端点写死在调用点",
    "src/data/entity/writer.py":
        "路径参数化:`get(path)` —— treasury 采集,端点由调用方给"
        "(`/public_treasury/{id}` 与 `/companies/public_treasury/{id}`)",
    "src/data/market/exchange_data.py":
        "同步 `requests` 点,URL 在变量里(永久例外)",
    "src/analytics/mmi/mmi_index_v3.py":
        "同步 `requests` 点,URL 在变量里(永久例外)",
}

#: 允许**注入** client 的文件 → (注入方文件, 理由)
ALLOWED_INJECTED_CLIENT_SITES: dict[str, tuple[str, str]] = {
    "src/data/entity/writer.py": (
        "src/api/main.py",
        "treasury 采集循环在 main.py 里注入 GuardedCGClient(S-894)",
    ),
    "src/data/market/cg_panel_sync.py": (
        "src/api/main.py",
        "面板回填循环在 main.py 里注入 GuardedCGClient(S-894)",
    ),
}


# ── 断言 ─────────────────────────────────────────────────────────────────────

def test_每个裸CG调用点都在记账():
    """**闸门外也要看得见。**

    裸 client 绕过了预算、绕过了熔断、也绕过了计数 —— 它唯一还剩下的东西
    就是 `note_unbudgeted_call` 这一行记账。没有它,那个请求就是**完全
    不可见**的一次可能扣钱的调用。
    """
    repo = scan_repo()
    offenders: list[str] = []
    for rel, sites in repo.items():
        bare = [s for s in sites if s.kind == "bare"]
        if not bare:
            continue
        if rel in ALLOWED_BARE_CALL_SITES:
            continue
        offenders.append(f"{rel}:{bare[0].line} {bare[0].endpoint}")
    assert not offenders, (
        "这些文件在**闸门外**打 CoinGecko,而且没登记、没记账 —— "
        "一次可能扣钱的请求完全不可见:\n  " + "\n  ".join(offenders))


def test_登记在册的例外每个都还在记账():
    """登记了就要真登记 —— 例外文件里必须真的有 `note_unbudgeted_call`。"""
    missing: list[str] = []
    for rel in ALLOWED_BARE_CALL_SITES:
        p = ROOT / rel
        assert p.exists(), f"登记在册的 {rel} 不存在了 —— 登记要跟着代码一起退役"
        if "note_unbudgeted_call" not in p.read_text(encoding="utf-8"):
            missing.append(rel)
    assert not missing, "这些例外文件不再记账了(收口进闸门了就该把登记撤掉):\n  " + \
                         "\n  ".join(missing)


def test_登记的端点跟文件实际打的对得上():
    """登记的**端点**也要是真的 —— 否则登记表跟代码说的不是同一件事。"""
    repo = scan_repo()
    bad: list[str] = []
    for rel, (endpoints, _why) in ALLOWED_BARE_CALL_SITES.items():
        sites = repo.get(rel, [])
        seen = {s.endpoint for s in sites}
        # 文件里出现的 CG 路径字面量(URL 在变量里时,调用点抓不到端点)
        seen |= _paths_in((ROOT / rel).read_text(encoding="utf-8"))
        for ep in endpoints:
            if ep not in seen:
                bad.append(f"{rel}: 登记了 {ep},但文件里没看到(实际:{sorted(seen)})")
    assert not bad, "登记的端点跟代码对不上:\n  " + "\n  ".join(bad)


def test_登记在册的例外没有变成死的():
    """登记的例外如果已经不裸了(收口进闸门了),登记必须撤。"""
    repo = scan_repo()
    stale: list[str] = []
    for rel in ALLOWED_BARE_CALL_SITES:
        sites = repo.get(rel, [])
        if not any(s.kind == "bare" for s in sites):
            stale.append(rel)
    assert not stale, (
        "这些文件已经不裸了(已收口进闸门)—— 登记在册的例外必须撤掉"
        "(SPINE:184-213「登记了就要真退役」):\n  " + "\n  ".join(stale))


def test_注入client的文件_注入方必须走闸门():
    """`injected` 只在注入方走闸门时才成立 —— 否则闸门被绕了一圈。"""
    repo = scan_repo()
    for rel, sites in repo.items():
        if not any(s.kind == "injected" for s in sites):
            continue
        assert rel in ALLOWED_INJECTED_CLIENT_SITES, (
            f"{rel} 接收注入的 client,但没登记 —— 注入方是谁?")
        injector, _why = ALLOWED_INJECTED_CLIENT_SITES[rel]
        injector_text = (ROOT / injector).read_text(encoding="utf-8")
        assert "GuardedCGClient" in injector_text, \
            f"注入方 {injector} 没有用 GuardedCGClient —— 闸门被绕了一圈"


def test_注入的登记没有变成死的():
    repo = scan_repo()
    stale = [rel for rel in ALLOWED_INJECTED_CLIENT_SITES
             if not any(s.kind == "injected" for s in repo.get(rel, []))]
    assert not stale, "登记在册的注入点已经不注入了 —— 登记必须撤掉:\n  " + \
                      "\n  ".join(stale)


def test_闸门内的文件真的用了闸门():
    """`gated` 的判定不能靠一个字符串匹配蒙混过关(注释里写「接了闸门」不算)。

    ⚠ S-895 阶段 5:`src/data/narrative/social_collector.py` **从这张表里退出了**
    —— 它不再持有 CG client,只做**消费**(取数收敛到 `data_layer` 一处)。
    留着它 = 一条已经不成立的登记(SPINE:184-213「登记了就要真退役」)。
    它现在是**纯消费者**这件事由 `tests/test_cg_single_live_path.py` 钉死。
    """
    for rel in ("src/data/market/data_layer.py",
                "src/api/main.py",
                # S-895 阶段 1:交易路由的标记价取数收口进闸门。
                "src/api/routers/trading.py"):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        uses = any(
            (isinstance(n, ast.Call) and _is_get_cg_client(n))
            or (isinstance(n, ast.Name) and n.id == "GuardedCGClient")
            or (isinstance(n, ast.Attribute) and n.attr == "GuardedCGClient")
            for n in ast.walk(tree)
        )
        assert uses, f"{rel} 没有接闸门"


def test_每个CG端点都在覆盖表里():
    """**新增端点必须改这张表。** 没登记的端点一律不允许存在。

    这条是「让下一个 agent 开不了洞」的那一层(计划 §5.1):新开一个 CG
    调用点会在这里红掉 ⇒ 那是一次**有意识的动作**(登记 = 承认这个端点
    存在、知道它归谁管),而不是「顺手加一行请求」。
    """
    repo = scan_repo()
    missing: list[str] = []
    for rel, sites in repo.items():
        for s in sites:
            if s.endpoint == "(dynamic)":
                if rel not in DYNAMIC_ENDPOINT_SITES:
                    missing.append(
                        f"{rel}:{s.line} (dynamic) —— 端点在变量里,按文件登记 "
                        f"(见 DYNAMIC_ENDPOINT_SITES)")
                continue
            entry = CG_ENDPOINT_COVERAGE.get(s.endpoint)
            if entry is None:
                missing.append(f"{rel}:{s.line} {s.endpoint} —— 端点没登记在覆盖表里")
                continue
            files, kinds = entry
            if rel not in files:
                missing.append(f"{rel}:{s.line} {s.endpoint} —— 覆盖表里没登记这个文件")
            if s.kind not in kinds:
                missing.append(f"{rel}:{s.line} {s.endpoint} —— client 类型 "
                               f"{s.kind} 不在允许集 {kinds}")
    assert not missing, (
        "这些 CoinGecko 调用点没登记在覆盖表里 —— 新增端点/文件必须改表:\n  "
        + "\n  ".join(missing))


def test_覆盖表没有变成死的():
    """登记了就要真退役(SPINE:184-213)。"""
    repo = scan_repo()
    seen: dict[str, set[str]] = {}
    for rel, sites in repo.items():
        for s in sites:
            if s.endpoint != "(dynamic)":
                seen.setdefault(s.endpoint, set()).add(rel)
    stale: list[str] = []
    for ep, (files, _kinds) in CG_ENDPOINT_COVERAGE.items():
        for rel in files:
            if rel not in seen.get(ep, set()):
                stale.append(f"{ep} → {rel} —— 代码里已经没有这个调用了")
    assert not stale, (
        "覆盖表里的登记已经不成立了 —— 登记要跟着代码一起退役:\n  "
        + "\n  ".join(stale))


def test_动态端点的登记没有变成死的():
    repo = scan_repo()
    dyn_files = {rel for rel, sites in repo.items()
                 if any(s.endpoint == "(dynamic)" for s in sites)}
    stale = [rel for rel in DYNAMIC_ENDPOINT_SITES if rel not in dyn_files]
    assert not stale, (
        "登记成动态端点的文件已经不扫出动态调用了 —— 登记必须撤掉:\n  "
        + "\n  ".join(stale))
    missing = [rel for rel in dyn_files if rel not in DYNAMIC_ENDPOINT_SITES]
    assert not missing, (
        "这些文件扫出了动态端点但没登记 —— 登记必须写明端点由谁决定:\n  "
        + "\n  ".join(missing))
