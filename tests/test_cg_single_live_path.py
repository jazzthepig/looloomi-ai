"""CoinGecko「一个能力只有一条活路」的**调用点级**守卫(S-895 阶段 5)。

## 为什么在 `test_cg_call_sites.py` 之外还要这一个

`test_cg_call_sites.py` 管的是**文件级**:哪个文件可以打哪个端点。
它看不见「同一个文件里有两处实现同一个形状」——而那正是 S-895 阶段 5 里
真实发生过的事:

| 端点 | 阶段 5 之前 | 现在 |
|---|---|---|
| `/coins/{id}` | 4 处(开发者数据 / 分类 / VC 组合 / 社区数据) | **1 处**(`get_cg_coin_payload`) |
| `/coins/{id}/tickers` | 2 处(交易所集中度 / ticker 列表) | **1 处**(`get_cg_tickers_payload`) |
| `/coins/list` | 3 处(面板解析 / 永续市值回填 / 持有人表) | **1 处 + 1 条登记例外** |
| `/coins/categories/list` | 2 处(分类 id 集合 / 名字→id 映射) | **1 处**(`get_cg_category_list_payload`) |
| `/coins/categories` | 2 处(分类日度快照 / VC 组合面板) | **1 处**(`get_cg_categories_payload`) |
| `/search/trending` | 2 处(前端 trending 栏 / CIS trending map) | **1 处**(`get_cg_trending_payload`) |

⇒ **重复的形状是同一个端点 + 同一组参数**。判据是 `SPINE.md:188-191`
「**不能给出不同答案 ⇒ 是重复**」:不同的参数形状 / 不同的失败语义 ⇒
**问的不是同一个问题** ⇒ 不是重复,登记在册即可。

## 两张表

- `SINGLE_PATH_ENDPOINTS` —— **必须只有一条活路**的端点(收敛完成的那些)。
  断言它们真的只有 1 个文件、1 个调用点。
- `EXCEPTIONS` —— **登记在册的多活路**端点:每条路径都必须写清**为什么**
  它问的不是同一个问题。理由为空 ⇒ 断言红。

⚠ **登记了就要真退役**(`SPINE.md:184-213`):这张表里任何一条登记,
一旦代码里那个调用点没了 ⇒ 断言红(「登记要跟着代码一起退役」)。
反过来也一样:代码里新出现的调用点没登记 ⇒ 断言红。

⇒ 下一个 agent 想开第二条活路,必须先在这里写一行理由 —— 那是一次
**有意识的动作**,不是「顺手加一行请求」。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: 复用 `test_cg_call_sites.py` 的扫描器(同一套归一规则 ⇒ 两张表说的是同一件事)。
_spec = importlib.util.spec_from_file_location("_cg_call_sites", ROOT / "tests" / "test_cg_call_sites.py")
_cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cs)

scan_repo = _cs.scan_repo
scan_file = _cs.scan_file
DYNAMIC_ENDPOINT_SITES = _cs.DYNAMIC_ENDPOINT_SITES


# ── 表一:必须只有一条活路的端点 ───────────────────────────────────────────────

#: 端点 → 该端点**必须**只有 1 个文件、1 个调用点。
#:
#: 收敛完成的家族(S-895 阶段 5)+ 本来就只有一条的端点。
SINGLE_PATH_ENDPOINTS: set[str] = {
    # ── S-895 阶段 5 收敛出来的 ────────────────────────────────────────────
    "/coins/{id}",
    "/coins/{id}/tickers",
    "/coins/categories/list",
    "/coins/categories",
    "/search/trending",
    # ── 本来就只有一条的 ────────────────────────────────────────────────────
    "/coins/{id}/circulating_supply_chart",
    "/coins/{id}/history",
    "/coins/{id}/market_chart",
    "/coins/{id}/market_chart/range",
    "/derivatives/exchanges/{id}",
    "/exchanges/{id}/volume_chart/range",
    "/global",
    "/onchain/networks/{id}/tokens/{id}/top_holders",
    "/public_treasury/{id}",
    "/companies/public_treasury/{id}",
}


# ── 表二:登记在册的多活路端点 ─────────────────────────────────────────────────

#: 端点 → ((文件, 该文件里的调用点数, 为什么这是**另一条**活路), …)
#:
#: 理由必须写清「**为什么它问的不是同一个问题**」——
#: 参数形状不同 / 失败语义不同 / 消费方不同 / 源不可变 ⇒ 是不同的活路。
#: ⚠ 理由为空或等于「同上」⇒ 断言红。登记不是空白名单。
EXCEPTIONS: dict[str, tuple[tuple[str, int, str], ...]] = {
    "/coins/list": (
        ("src/data/market/data_layer.py", 1,
         "共享活路:`get_cg_coin_list`(面板解析 + 持有人表共用同一份载荷)"),
        ("src/data/market/perp_mcap_backfill.py", 1,
         "登记例外:它要 `status=active,inactive` 过滤(含已下架的币);"
         "`/coins/list` 的响应里**没有 per-coin 的 status 字段**(实测:只有 id/name/platforms/symbol)"
         "⇒ 拿到全量也**本地筛不出** ⇒ 必须自己打"),
    ),
    "/coins/markets": (
        ("src/data/market/data_layer.py", 4,
         "四个**查询形状**:按 id 取 / 严格版(读不到抛异常,参数是子集) / 按分类取成员 / 新上架"
         "⇒ 失败语义与参数集都不同(`get_cg_markets_raw` 的 docstring 里逐条列了)"),
        ("src/api/routers/cis.py", 1,
         "watchlist 面板:按 id + 30d 变化率,自带 60s 缓存(前端形状,不是 CIS 扇出)"),
        ("src/data/market/cg_panel_sync.py", 1,
         "面板市值解析:翻页取前 1000 名(4 次批量读;client 由 main.py 注入 —— 注入方走闸门)"),
    ),
    "/coins/{id}/ohlc/range": (
        ("src/data/market/data_layer.py", 1,
         "读路径:单窗口取数(带缓存)"),
        ("src/data/market/deep_walk.py", 1,
         "深回填:175 天一块 + 接缝重叠一天(S-258 的分块形状 —— 不是同一个问题)"),
    ),
    "/derivatives": (
        ("src/data/market/derivatives_market.py", 1,
         "写入端:每 6 小时把全市场永续落进 `derivatives_market_daily`"),
        ("src/data/cis/positioning.py", 1,
         "**读库优先**的兜底:表超两个周期没写上才打 API(两个额度池,但只有一个会被触发)"),
        ("src/data/market/data_layer.py", 1,
         "CIS 用的另一份口径(只留 CIS 宇宙里的永续,300s 缓存)"),
    ),
    "/global/market_cap_chart": (
        ("src/data/market/data_layer.py", 1,
         "读路径:返回 {market_cap, volume} 原始数组"),
        ("src/data/market/global_history.py", 1,
         "轨迹写入端:自己带 `days` 参数 + **不吃 CMC 兜底**"
         "(轨迹要同源可比 —— 换源会污染序列,`DATA_ARCHITECTURE.md:70` source 不可变)"),
    ),
    "/rwas/markets": (
        ("src/data/market/data_layer.py", 1,
         "读路径:单页读(RWA 列表,不带翻页)"),
        ("src/data/rwa/collect.py", 2,
         "采集端:`per_page=250` **翻页**取完 + 按 issuer 过滤反查(形状不同)"),
    ),
    "/rwas/issuers/list": (
        ("src/data/market/data_layer.py", 1,
         "读路径:单页读(发行方列表,不带翻页)"),
        ("src/data/rwa/collect.py", 1,
         "采集端:同一端点,但走自己的翻页 client(与上面那两处同一批采集)"),
    ),
    "/simple/price": (
        ("src/api/routers/trading.py", 2,
         "标记价:单标的(带 EODHD 兜底)/ 批量 —— 两者共用同一份 per-symbol 价格缓存"),
    ),
}


# ── 工具 ─────────────────────────────────────────────────────────────────────

def _sites_by_endpoint() -> dict[str, dict[str, list]]:
    """端点 → 文件 → [(行号, kind), …](只扫非动态端点)。"""
    out: dict[str, dict[str, list]] = {}
    for rel, sites in scan_repo().items():
        for s in sites:
            if s.endpoint == "(dynamic)":
                continue
            out.setdefault(s.endpoint, {}).setdefault(rel, []).append((s.line, s.kind))
    return out


def _all_endpoints() -> set[str]:
    eps: set[str] = set()
    for rel, sites in scan_repo().items():
        for s in sites:
            if s.endpoint != "(dynamic)":
                eps.add(s.endpoint)
    return eps


# ── 断言 ─────────────────────────────────────────────────────────────────────

def test_每个端点都登记了活路():
    """**新增端点必须改表。** 没登记的端点一律不允许存在。

    这是「让下一个 agent 开不了洞」的那一层:新开一个 CG 调用点会在这里
    红掉 ⇒ 那是一次**有意识的动作**(登记 = 承认它存在、知道它归谁管)。
    """
    eps = _all_endpoints()
    known = SINGLE_PATH_ENDPOINTS | set(EXCEPTIONS)
    missing = sorted(eps - known)
    assert not missing, (
        "这些 CoinGecko 端点没登记在任何一张表里 —— 新增端点必须改表:\n  "
        + "\n  ".join(missing))
    stale = sorted(known - eps)
    assert not stale, (
        "表里登记的端点代码里已经没有了 —— 登记要跟着代码一起退役"
        "(SPINE:184-213):\n  " + "\n  ".join(stale))


def test_单活路端点真的只有一条():
    """`SINGLE_PATH_ENDPOINTS` 里的端点:1 个文件、1 个调用点。

    「同一个文件里写了两遍同一个形状」也算两条活路 —— 阶段 5 收敛掉的
    `/search/trending`(前端那栏 + CIS 的 trending map)就是这个形状。
    """
    by_ep = _sites_by_endpoint()
    bad: list[str] = []
    for ep in sorted(SINGLE_PATH_ENDPOINTS):
        files = by_ep.get(ep)
        if not files:
            bad.append(f"{ep} —— 代码里没有这个调用了(登记要撤)")
            continue
        if len(files) != 1:
            bad.append(f"{ep} —— 有 {len(files)} 个文件在打它:{sorted(files)}")
            continue
        rel, sites = next(iter(files.items()))
        if len(sites) != 1:
            bad.append(f"{ep} —— {rel} 里有 {len(sites)} 个调用点(同形状写了两遍)")
    assert not bad, (
        "这些端点应该只有**一条**活路,但代码里不是:\n  " + "\n  ".join(bad))


def test_例外的每条路径都写清了理由():
    """**登记不是空白名单。** 每条额外活路都要说清「为什么问的不是同一个问题」。"""
    bad: list[str] = []
    for ep, paths in EXCEPTIONS.items():
        for rel, _n, why in paths:
            if not why or len(why.strip()) < 12:
                bad.append(f"{ep} → {rel} —— 理由太短/为空")
    assert not bad, "例外路径必须写清理由(为什么它问的不是同一个问题):\n  " + \
                    "\n  ".join(bad)


def test_例外的调用点数跟代码对得上():
    """登记的**调用点数**也要是真的 —— 否则登记表跟代码说的不是同一件事。"""
    by_ep = _sites_by_endpoint()
    bad: list[str] = []
    for ep, paths in EXCEPTIONS.items():
        files = by_ep.get(ep, {})
        for rel, n, _why in paths:
            got = len(files.get(rel, []))
            if got != n:
                bad.append(f"{ep} → {rel} —— 登记 {n} 个调用点,代码里 {got} 个")
    assert not bad, "例外登记的调用点数跟代码对不上:\n  " + "\n  ".join(bad)


def test_例外里没有多出来的文件():
    """例外表登记了这两个端点 ⇒ 代码里**只该**有这些文件在打。"""
    by_ep = _sites_by_endpoint()
    bad: list[str] = []
    for ep, paths in EXCEPTIONS.items():
        registered = {rel for rel, _n, _why in paths}
        actual = set(by_ep.get(ep, {}))
        for rel in sorted(actual - registered):
            bad.append(f"{ep} → {rel} —— 代码里有,登记里没有")
    assert not bad, "例外端点出现了未登记的文件:\n  " + "\n  ".join(bad)


def test_社交采集器只做消费_不再持有第二条活路():
    """`src/data/narrative/social_collector.py` **不再持有 CG client**。

    阶段 5 之前它自己打 `/coins/{id}`(社区数据那一层)⇒ 同一族端点两条活路。
    现在它只**消费** `data_layer.get_cg_coin_payload`。
    """
    rel = "src/data/narrative/social_collector.py"
    sites = scan_file(ROOT / rel)
    assert not sites, (
        f"{rel} 又有了 CoinGecko 调用点 —— `/coins/{id}` 就多了一条活路:\n  "
        + "\n  ".join(f"{s.path}:{s.line} {s.endpoint} ({s.kind})" for s in sites))
    src = (ROOT / rel).read_text(encoding="utf-8")
    assert "get_cg_coin_payload" in src, f"{rel} 没有走共享取数口"
    for marker in ("_get_cg_client", "GuardedCGClient", "api.coingecko.com", "CG_PRO_BASE"):
        assert marker not in src, f"{rel} 又自己持有 CG client({marker})—— 那就是第二条活路"


def test_动态端点的文件都登记了理由():
    """路径在变量里的文件 ⇒ 端点由调用方给 ⇒ 必须在册,且要写明端点由谁决定。"""
    dyn_files = {rel for rel, sites in scan_repo().items()
                 if any(s.endpoint == "(dynamic)" for s in sites)}
    missing = sorted(dyn_files - set(DYNAMIC_ENDPOINT_SITES))
    assert not missing, "这些文件扫出了动态端点但没登记 —— 登记必须写明端点由谁决定:\n  " + \
                         "\n  ".join(missing)
