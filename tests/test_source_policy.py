"""Bulk fan-out belongs on a paid source (S-205).

Jazz, 2026-08-23: 不可以那么依赖任何免费 api,大量多资产会被封啊。多并发高需求量
的我们要以 pro 的 coingecko 为主要来源。

He had said this before. It was violated twice in one week anyway:

  · deep_panel_collector — 262 symbols against Binance's free mirror. One symbol
    reachable; the panel sat dead for days (S-190).
  · hyperliquid_collector — 232 symbols against a free DEX endpoint at ~53 req/s.
    HTTP 429 on 57 including BTC, coverage 56%, write refused two days (S-204).

Both were "fixed" at the symptom — a floor that blocks, a gentler pace. Neither
touched the rule. A reminder given and violated twice is not a reminder; it has
to be something that fails a build.

AND THE REAL LESSON WAS CHEAPER THAN THE FIX. Hyperliquid's metaAndAssetCtxs
returns markPx, oraclePx, funding, openInterest and day volume for ALL 232 perps
in ONE request. The 232-call loop existed because nobody looked for a bulk
endpoint. The rate limit was not a wall to pace against — it was the venue
saying the question was wrong.
"""
import ast
import pathlib

import pytest

from src.data.market.source_policy import (
    assert_bulk_source, SourcePolicyError, BULK_THRESHOLD,
    PAID_SOURCES, FREE_SOURCES, bulk_endpoint_for)
from tests._source import code_only

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_a_bulk_fanout_over_a_free_source_raises():
    with pytest.raises(SourcePolicyError) as e:
        assert_bulk_source(232, "hyperliquid", job="daily bars")
    msg = str(e.value)
    assert "232" in msg and "free source" in msg
    assert "coingecko_pro" in msg, "the error must name where it SHOULD go"
    assert "metaAndAssetCtxs" in msg, (
        "when the free source has a bulk endpoint the error must say so — that "
        "is the actual fix, not a gentler pace")


def test_paid_sources_may_fan_out():
    assert_bulk_source(17000, "coingecko_pro", job="breadth")
    assert_bulk_source(500, "eodhd", job="tradfi bars")


def test_a_targeted_query_against_a_free_source_is_fine():
    """This is not 'free sources are bad'. One question is fine; a fan-out is not."""
    assert_bulk_source(BULK_THRESHOLD, "hyperliquid", job="targeted")


def test_the_threshold_needs_no_judgement_at_the_call_site():
    assert BULK_THRESHOLD <= 10, (
        f"threshold {BULK_THRESHOLD} — the two incidents were 262 and 232, and "
        f"any honest bulk job is far above this, so it should never be a close call")


def test_the_two_burned_sources_are_classified_free():
    for s in ("hyperliquid", "binance", "binance_vision", "yfinance"):
        assert s in FREE_SOURCES, f"{s} burned us; it must be classified free"
    assert "coingecko_pro" in PAID_SOURCES and "eodhd" in PAID_SOURCES


def test_the_venue_bulk_endpoint_is_recorded():
    hl = bulk_endpoint_for("hyperliquid")
    assert any("metaAndAssetCtxs" in k for k in hl), (
        "the one-call endpoint must be discoverable from the policy, or the "
        "next person writes the 232-call loop again")


def test_the_hyperliquid_fanout_is_gated():
    src = code_only((ROOT / "src/data/market/hyperliquid_collector.py").read_text())
    fn = src.split("async def collect_hyperliquid")[1]
    # S-296: 用途守卫内部调用数量守卫,所以这里认它。**两道都要在扇出之前。**
    gate = fn.find("assert_purpose_source(")
    loop = fn.find("asyncio.gather(")
    assert gate > 0, "the per-symbol path must consult the policy"
    assert gate < loop, "the gate must run BEFORE the fan-out, not alongside it"


def test_execution_fanout_must_carry_an_explicit_symbol_list():
    """S-296:名单从哪来,是这条规则的全部重量。

    HL 挂 233 个永续 —— 那是**场馆的库存**,不是我们的成交集。
    默认值等于把「挂牌」当「要交易」,而 S-204 那次 233 个标的的扇出
    正是这么来的。所以 execution 用途下的扇出必须由调用方显式传名单。
    """
    from src.data.market.source_policy import (
        EXECUTION, MARKET_DATA, PurposeMismatch, SourcePolicyError,
        assert_purpose_source)

    # 拿场馆挂牌当名单 —— 正是 S-204
    with pytest.raises(PurposeMismatch, match="没有显式传入成交名单"):
        assert_purpose_source(EXECUTION, "hyperliquid", n_assets=233,
                              job="daily bars", explicit_set=False)
    # ⚠️ 显式传名单**只解决出处,不解决体量**。233 个显式标的照样被数量守卫拦下 ——
    # 因为一份「233 个名字的成交集」就是把场馆挂牌换了个标签重新提交。
    # 两道守卫回答两个问题:名单从哪来 / 这个源扛不扛得住。
    with pytest.raises(SourcePolicyError, match="free source"):
        assert_purpose_source(EXECUTION, "hyperliquid", n_assets=233,
                              job="marks", explicit_set=True)
    # 真正的成交集是一小把名字 —— 自由源的定价方式就是「一次调用或者一小把」
    assert_purpose_source(EXECUTION, "hyperliquid", n_assets=5,
                          job="execution marks", explicit_set=True)
    # 面板行情走 HL —— 用途错了,数量再小也不该过
    with pytest.raises(PurposeMismatch, match="coingecko_pro"):
        assert_purpose_source(MARKET_DATA, "hyperliquid", n_assets=3,
                              job="frontend prices")


def test_the_loop_reads_the_venue_only_for_what_only_the_venue_knows():
    """S-296:`_hyperliquid_loop` 不再取面板日线。

    S-205 的数量守卫从 2026-08-23 起正确地拦住了那个扇出,而**没有人接手** ——
    hyperliquid 停在 08-23,CG Pro 只覆盖 25 个标的,面板 262 个里 237 个
    两周没有日线来源。**一个只拦不导的守卫,会把违规变成缺口。**
    """
    main = code_only((ROOT / "src/api/main.py").read_text())
    loop = main.split("async def _hyperliquid_loop")[1].split("\nasync def ")[0]
    assert "collect_venue_marks" in loop, (
        "场馆循环必须走一次请求的 venue_snapshot 路径")
    assert "collect_hyperliquid" not in loop, (
        "面板日线不走 HL —— 那是 market_data 用途,归 CoinGecko Pro")
    # S-294 接错过一次:SourcePolicyError 是设计错误,不是覆盖率拒绝。
    assert "refused=" not in loop, (
        "本循环没有覆盖率地板,它的失败都是真故障。把设计错误记成"
        "「正确地拒绝写」,等于把它伪装成健康")


def test_the_one_call_snapshot_exists_and_does_not_loop():
    src = code_only((ROOT / "src/data/market/hyperliquid_collector.py").read_text())
    fn = src.split("async def venue_snapshot")[1].split("\nasync def ")[0]
    assert "metaAndAssetCtxs" in fn
    assert "Semaphore" not in fn and "gather" not in fn, (
        "venue_snapshot must be ONE request — a loop here would recreate the "
        "problem it exists to remove")
    assert "return None" in fn or "_f" in fn, (
        "absent venue fields must be None, not 0.0 (I1) — a funding rate of 0.0 "
        "and an unknown funding rate size a book differently")


def test_no_new_module_fans_out_over_a_free_endpoint_uncounted():
    """Static sweep: a per-symbol loop against a free host, with no policy call
    in the same function. Matches the CONSTRUCT (a loop plus a free URL), not a
    name — see tests/_source.py for why that distinction keeps mattering.

    ⚠️ **扫描范围原本只有 `src/data`,而 ① 的价格加载器在 `src/research`** (S-300)。
    2026-09-05 实测:`causal_positioning.load_binance_panel` 对
    `fapi.binance.com` 逐标的取 klines + fundingRate,24 个标的 = 每天约 48 次
    调用,**而它从来没有被这条扫描看见过** —— 因为它在另一个目录。

    这是本周第 N 次同一句话:**作用域比问题小一格的守卫,读起来就是覆盖。**
    而这一次它漏掉的,恰好是要拿真钱去跑的那本账的价格源。

    范围改成整个 `src/`。**一个「哪些源不能扇出」的规则,和文件放在哪个目录无关。**
    """
    _HTTP_METHODS = {"get", "post", "request", "send", "stream"}
    #: 看起来像 HTTP 客户端的接收者。名字集合是从仓里实际用法抽的,
    #: 不是想象的 —— `c.get` / `client.post` / `httpx.get` / `session.get`。
    _CLIENT_NAMES = {"c", "client", "cl", "httpx", "requests", "session",
                     "http", "_client", "aclient", "s"}
    FREE_HOSTS = ("api.hyperliquid.xyz", "data-api.binance.vision",
                  "fapi.binance.com", "api.binance.com")
    offenders = []
    for path in (ROOT / "src").rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        src = code_only(path.read_text())
        if not any(h in src for h in FREE_HOSTS):
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = ast.get_source_segment(src, fn) or ""
            if not any(h in body for h in FREE_HOSTS):
                continue
            # A FAN-OUT is a gather over a VARIABLE-LENGTH list — `gather(*[...])`
            # — not any gather at all. `_binance_perp` awaits three fixed
            # endpoints for ONE symbol; the first version of this scan flagged
            # it, which is the same "matched a construct that merely resembles
            # the target" error this file's siblings keep hitting. The Starred
            # argument is the distinction, and it is exact.
            # 本函数(含嵌套)里自己定义的、内部会打网络的取数函数名。
            # `load_binance_panel` 的 `klines` / `funding` 就是这种 ——
            # 循环里只看到 `klines(sym)`,网络在它里面。
            _LOCAL_FETCHERS = {
                d.name for d in ast.walk(fn)
                if isinstance(d, (ast.FunctionDef, ast.AsyncFunctionDef))
                and d is not fn
                and any(getattr(c.func, "attr", None) in _HTTP_METHODS
                        and getattr(getattr(c.func, "value", None), "id", None)
                        in _CLIENT_NAMES
                        for c in ast.walk(d) if isinstance(c, ast.Call))
            }
            fans_out = False
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                name = (node.func.attr if isinstance(node.func, ast.Attribute)
                        else getattr(node.func, "id", None))
                if name == "gather" and any(isinstance(a, ast.Starred) for a in node.args):
                    fans_out = True
                if name == "Semaphore":
                    fans_out = True
            # ⚠️ **上面两条只认异步扇出** (S-300)。`load_binance_panel` 是一个
            # 同步 `for a in assets:` 循环,里面对 `fapi.binance.com` 逐标的取
            # klines + fundingRate —— 24 个标的、每天约 48 次调用,**而这条扫描
            # 看不见它**,因为它既没有 gather 也没有 Semaphore。
            #
            # 扫描把「扇出」定义成了 asyncio 的两个构件,而扇出是
            # **「对着一个源循环 N 次」**,与并发模型无关。
            # 一个 for 循环打 48 次和一个 gather 打 48 次,对被打的那一端
            # 完全一样 —— 而 429 是那一端发的。
            #
            # > **守卫对目标的定义比目标窄,和没有守卫的区别只是它让人放心。**
            #
            # 判据仍然要精确:循环体里**真的有**那个 host 才算,
            # 一个恰好在循环外调用免费源一次的函数不算。
            if not fans_out:
                for node in ast.walk(fn):
                    if not isinstance(node, (ast.For, ast.AsyncFor, ast.While,
                                             ast.ListComp, ast.DictComp,
                                             ast.SetComp, ast.GeneratorExp)):
                        continue
                    # ⚠️ 不能只找循环体里的 host **字面量**。
                    # `load_binance_panel` 写的是 `base = "https://fapi.binance.com"`
                    # 在外层,循环里调的是 `klines(sym)`,而 `klines` 用的是
                    # f-string 拼 `base` —— **三处都没有那个字面量**。
                    # 第一版这么写,于是它照样漏掉了 ① 的价格源:
                    # 一个 URL 只要被赋给变量,就从字符串匹配里消失了。
                    #
                    # 判据放回构件本身:**这个函数引用了免费源,并且它有一个
                    # 带调用的循环。** 这两件事同时成立,就是「对着一个源循环 N 次」。
                    # 宁可宽一点 —— 误报的成本是加一次 gate 或一条显式豁免,
                    # 漏报的成本是 ① 的价格源两个月没人看见。
                    # 判据是**循环里有没有网络调用**,不是有没有任何调用。
                    # `collect_venue_marks` 的循环只在拼行(HTTP 是循环外那一次),
                    # 把它判成扇出就是又一次「匹配了看起来像目标的构件」——
                    # 而这条守卫的兄弟们已经在这上面栽过好几次。
                    # ⚠️ `a.get("funding_1h")` 和 `client.get(url)` 在 AST 上
                    # 只差一个接收者。第一版按方法名判,于是 `collect_venue_marks`
                    # 那个只在拼行的循环被判成扇出 —— **dict.get 被当成了 HTTP get。**
                    # 判据加上接收者:客户端名,或者被 await(dict.get 不会被 await)。
                    def _hits_network(n_) -> bool:
                        for c in ast.walk(n_):
                            if not isinstance(c, ast.Call):
                                continue
                            a = getattr(c.func, "attr", None)
                            recv = getattr(getattr(c.func, "value", None), "id", None)
                            if a in _HTTP_METHODS and recv in _CLIENT_NAMES:
                                return True
                            # 循环里调了本模块定义的取数函数(klines / funding / …)
                            fid = getattr(c.func, "id", None)
                            if fid and fid in _LOCAL_FETCHERS:
                                return True
                        return False

                    if _hits_network(node):
                        fans_out = True
                        break
            # S-296:用途守卫内部就调数量守卫,两者都算「已闸」。
            # 只认 `assert_bulk_source` 会把正确升级过的调用点判成违规 ——
            # **一个守卫认不出比自己更严的守卫,就是在惩罚修复。**
            gated = ("assert_bulk_source" in body
                     or "assert_purpose_source" in body)
            if fans_out and not gated:
                offenders.append(f"{path.relative_to(ROOT)}::{fn.name}")
    # ── 已知未闸,只减不增 (S-300) ────────────────────────────────────────────
    #
    # 扫描范围从 `src/data` 放宽到 `src/`、并且把**同步 for 循环**也算作扇出
    # 之后,一次浮出 7 处。**它们不是新出现的,是一直在那里而扫描看不见。**
    # 一次全修会让这条守卫变成一次大重构的门,而一个逼人做大重构的守卫会被绕过。
    #
    # 所以按仓里既有的模式(`NOT_WIRED_YET` / `NO_BEAT_BUDGET`)登记:
    # **名字全部可见、每条带理由、只减不增。这张表是工作队列,不是豁免。**
    KNOWN_UNGATED: dict[str, str] = {
        # ⚠️ P0 —— ① 的价格源。要拿真钱跑的那本账,每天 24 标的 × 2 端点
        # ≈ 48 次调用打在 fapi.binance.com 上,没有过任何策略闸。
        # 而 v5 的 inception reason 写着 v4 的「Binance → Hyperliquid oracle」
        # 价格参考「is RETAINED」—— **代码里没有 HL 价格路径,只有注释里有。**
        # 散文说换了源,代码在打 Binance。这条动到前向记录的定义,需 Jazz 定夺。
        "src/research/strategies/causal_positioning.py::load_binance_panel":
            "① beta_core 的价格源;与 v5 inception reason 声称的 HL oracle 不一致",
        # 这两本账的 NAV 表**至今 0 行**(2026-09-05 实测),而心跳报 ok。
        # 「从没写过一行」和「在免费源上扇出」很可能是同一件事的两面。
        "src/data/signals/factor_tilt_paper.py::_fetch_close_live":
            "factor_tilt_nav 至今 0 行 —— 疑与此扇出同因",
        "src/data/signals/pod_aggregator_paper.py::_fetch_close_funding_live":
            "pod_aggregator_nav 至今 0 行 —— 疑与此扇出同因",
        # 以下为离线研究脚本:不在任何循环里,跑一次要人手动起。
        # 优先级低,但**不是零** —— 它们照样会把我们的 IP 打进 429。
        "src/research/crowd_clock_backtest.py::run": "离线回测脚本",
        "src/research/cis_regime_studies/causal_sleeve_extension.py::fetch_binance_panel":
            "离线研究脚本",
        "src/research/factory/volume_factory_universe.py::fetch_symbol_ohlcv":
            "离线研究脚本",
    }
    new = [o for o in offenders if o not in KNOWN_UNGATED]
    assert not new, (
        "fan-out over a free endpoint with no source-policy gate:\n  "
        + "\n  ".join(new)
        + "\n(check bulk_endpoint_for(source) first — the venue may answer in one call)")
    # 只减不增:修好一处就从表里删一处,表变短是唯一允许的方向。
    still = sorted(set(offenders) & set(KNOWN_UNGATED))
    assert len(still) <= len(KNOWN_UNGATED), "budget may only shrink"
    if len(still) < len(KNOWN_UNGATED):
        stale_entries = sorted(set(KNOWN_UNGATED) - set(offenders))
        raise AssertionError(
            "这些条目已经修好了,从 KNOWN_UNGATED 删掉它们:\n  "
            + "\n  ".join(stale_entries)
            + "\n(一张留着幽灵的豁免表会让人学会忽略它)")


def test_the_scanners_blind_spot_is_stated_not_hidden():
    """This sweep only sees a fan-out when the loop AND the free URL sit in the
    SAME function. `consolidator.fetch_venue_overlay` gathers over venues while
    the URLs live in `_binance_perp` one call down — invisible here.

    That case is not a violation (it fans out over VENUES for one asset, ~5
    requests, not over assets), but the blind spot is real and the next one
    might be. Stated rather than left implicit, because an empty check and a
    passing check look identical from outside — the failure mode this whole
    session kept finding.

    Closing it properly needs a call-graph, which is worth doing when a second
    instance appears and not before."""
    scanned, with_urls = 0, 0
    FREE_HOSTS = ("api.hyperliquid.xyz", "data-api.binance.vision",
                  "fapi.binance.com", "api.binance.com")
    for path in (ROOT / "src/data").rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        scanned += 1
        if any(h in code_only(path.read_text()) for h in FREE_HOSTS):
            with_urls += 1
    assert scanned > 20, f"only {scanned} modules scanned — the sweep is not reaching src/data"
    assert with_urls >= 3, (
        f"only {with_urls} modules reference a free host; the sweep should be "
        f"finding several — if this drops to 0 the scan has silently stopped working")
    print(f"\n  scanned {scanned} modules · {with_urls} touch a free host "
          f"· cross-function fan-outs NOT covered (stated blind spot)")
