"""`/internal/` 的鉴权按【行为】验,不按拼写验 (S-262).

## 为什么必须是行为验

我今天先后写了三个静态扫描器来数「有几条 `/internal/` 路由没有 token 门」:

    第一版  查 `'x_internal_token' in blk`            → 报 13 条
    第二版  查 `'x_internal_token != _INTERNAL_TOKEN'` → 报 22 条
    真相    两个都错

第二版的 9 条「新发现」里有 `/internal/rebalance`、`/internal/sl-tp-exit`、
`/internal/research-intake`、`/internal/asset-vectors/rebuild` —— **动作端点**,
看起来是重大暴露。逐条打开一看,**四条全都有门**,只是变量名不同
(`expected` / `tok` 而不是 `_INTERNAL_TOKEN`)。

> **扫描器匹配的是拼写,不是「这条路由会不会拒绝无凭证的调用者」。**

而这不只是数错了。同一轮里我给两条端点加门,**连续四次写出只在错误路径上
才炸的代码**:

    ① `_INTERNAL_TOKEN` 在 main.py 里不存在(那个常量只在 routers/*.py)  → NameError
    ② `HTTPException` 在 main.py 里没导入(它用 JSONResponse)          → NameError
    ③ 函数体后面有局部 `import os`,让 `os` 在整个作用域变成局部名        → UnboundLocalError
    ④ (以上三次都发生在同一段十行的代码里)

**四次全部:import 过、py_compile 过、正常路径过。** 只有真的有人不带 token
来打时才炸 —— 而那时返回的是 500,不是 401。**静态检查一次都抓不到。**
抓到它们的是 TestClient 打了一个真请求。

所以这条守卫**打真请求**:枚举每一条 `/internal/` 路由,不带 token 打一次,
断言它不返回 2xx。

## 第一次跑就抓到我自己写窄了 —— 三处

**① 只用 GET 探。** 于是 `/internal/rebalance`、`/internal/sl-tp-exit`、
`/internal/cis-scores` 这些 **POST-only** 端点回 404,而我把 404 读成了「收好口了」。
**404 不是「有门」,是「这条路由不接受这个方法」。** 一条 POST 端点的暴露面
只有用 POST 才测得出来。守卫的面比它名字宣称的窄 —— 这正是本文件 docstring
批评的那件事,发生在为它写的守卫里。

**② 把 404 / 401 / 抛异常折叠成了「非 2xx」。** 三个状态,一个表示:

    401/403  有门,拒了               ← 唯一算「安全」的
    404      方法不对 / 没挂载         ← 什么都没证明
    422      body 校验先炸            ← **鉴权是过了还是没过,不知道**
    EXC      处理器自己炸(=500)      ← 最危险的伪装

**③ 422 是这里最需要分辨的状态。** 它意味着请求**进到了 body 校验**。
真相只能靠「发一个形状合法的 body」逼出来 —— 实测 11 条 422 端点里 9 条
是 401(门在 `_auth()` helper 里,内联比较的扫描器看不见,第六次),
1 条 key 猜错了(补对 → 403),**1 条真的 200**:

    /internal/telegram/webhook  →  {"ok": true}      无凭证

    if secret and request.headers.get(...) != secret:   # secret 未设 ⇒ 整个门跳过

缺席的 secret 和正确的 secret 走了同一个放行分支。一个从没设过这个变量的
部署,对外看起来跟配好的一模一样。**已改为 fail-closed(503)。**

## 路由枚举必须下降进 `_IncludedRouter`

`app.routes` 里 router 挂载的路由被包在 `_IncludedRouter` 里(S-233 同一课),
朴素读法只看得见 `main.py` 自己的 12 条,而实际有 40 条。
复用 `tests/test_no_route_is_shadowed._flatten()` —— **不写第二个展平器**。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_FAILURES: list[str] = []

#: 有意公开的 `/internal/` 路由 + 原因。**名单只能减。**
#:
#: 「公开」在这里是一个有代价的选择,所以每一条都要说清楚**谁在无凭证地读它**,
#: 以及**它暴露的是形状还是状态**。形状(schema echo)可以公开;
#: 状态与业绩不行 —— 那正是 S-262 收掉 prediction-track-record 的理由。
#:
#: ⚠️ 初版的理由有一半是**编的**:我给 `beta-core-clock-size` / `beta-core-probe` /
#: 三条 schema 回声都写了「external_probe.sh 无凭证读」,而 grep 一遍脚本,
#: 它们**根本不在探针读的 14 条里**。写下一个看起来合理的理由,和核过一个理由,
#: 在文件里长得一模一样。下面每一条的读者都是 grep 出来的。
_PROBE = "external_probe.sh 无凭证读(已 grep 核对)"
PUBLIC_BY_DESIGN: dict[str, str] = {
    # ── 契约回声:只有形状,没有数值 ────────────────────────────────────
    "/internal/cis-scores/schema":
        "CLAUDE.md 规则 #2:Mac↔Railway 契约的 live echo,冲突时它说了算。" + _PROBE,
    "/internal/mac-push/schema": "契约回声,只有形状。" + _PROBE,
    "/internal/asset-vectors/schema": "契约回声,只有形状。探针不读,但同族契约,公开一致",
    "/internal/strategy-records/schema": "契约回声,只有形状。探针不读",
    "/internal/research-intake/schema": "契约回声,只有形状。探针不读",
    "/internal/mac-write/schema": "契约回声,只有形状。S-277:Mac 侧照它构造 payload,不要照 Mac 侧代码猜列名 —— 抄来的列名会把笔误一起抄过来",
    # ── 部署/运维健康:被无凭证的脚本读,收口会打断部署门 ──────────────
    "/internal/build-state":
        "smoke_test / post_deploy_check / deploy_health_gate / postdeploy_verify 四个脚本无凭证读",
    "/internal/data-freshness": _PROBE + ";docstring 写明它就是为该探针建的",
    "/internal/data-coverage":
        "S-276:minimax-c 跨 lane 读的回填基线。只有覆盖形状没有价格数值,"
        "而他不该拿到 service_role(Jazz 2026-08-30)。收口等于逼他继续"
        "拿单一个源当基线 —— 那正是 M-118 重复劳动的根因",
    "/internal/health-summary": _PROBE + ";S-262 已把 mac_mini_push 改名去掉硬件泄漏",
    "/internal/loop-health": _PROBE + " / loop_health.py",
    "/internal/vdb-health": "postdeploy_verify.sh 无凭证读",
    "/internal/beta-core-clock": _PROBE,
    "/internal/beta-core-clock-q":
        "与 beta-core-clock 同族的时钟读数,同批公开。**探针不读** —— "
        "留着是因为收口它要先确认 Mac 侧没在轮询,那是跨 lane 的确认",
}

#: 「有意公开」之外的第二类豁免:**坏掉的**路由。
#:
#: 和公开名单分开,因为它们是两件事 —— 一条 501/500 的路由不是被允许公开,
#: 它是**没人知道它已经死了**。合在一起会让「坏」悄悄继承「被批准」的语气。
KNOWN_BROKEN: dict[str, str] = {
    "/internal/beta-core-clock-size":
        "ImportError: clock_q_continuity 不在 src/data/signals/* 里(main.py:1697,1760)。"
        "端点 500,不是 401。探针不读它,所以没人发现。**修复归 beta-core 时钟的 owner**,"
        "不在本次 S-262 的范围内 —— 这里登记它,是为了它不再以「非 2xx」的样子冒充安全。",
}


def _check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ✓ {label}")
    else:
        _FAILURES.append(f"{label}{(' — ' + detail) if detail else ''}")
        print(f"  ✗ {label}\n      {detail}")


#: 形状合法的 body。**存在的理由:422 什么都不证明。**
#:
#: 不带 body 打一条 POST 端点得到 422,只说明 body 校验先炸了 —— 鉴权是过了
#: 还是根本没跑,从外面看不出来。给它一个能过校验的 body,状态码才回到由
#: 「有没有门」单独决定。实测:11 条 422 里 9 条其实是 401,1 条是我 key 猜错,
#: **1 条真的返回 200**(telegram/webhook,secret 未设时 fail-open)。
VALID_BODIES: dict[str, dict] = {
    "/internal/ai-briefing": {},
    "/internal/asset-vectors": {"rows": [{"symbol": "BTC"}]},
    "/internal/asset-vectors-history": {"rows": [{"symbol": "BTC", "schema_version": 3}]},
    "/internal/cis-scores": {"scores": [], "assets": []},
    "/internal/factor-hypotheses": {"hypotheses": []},
    "/internal/macro-brief": {},
    "/internal/quant-push": {"rows": []},
    "/internal/research-intake": {"rows": []},
    "/internal/risk-meter-history": {"p_d": "2026-08-30"},
    "/internal/strategy-records": {"rows": []},
    "/internal/telegram/webhook": {"message": {"text": "/x", "chat": {"id": 1}}},
}

GATED, OPEN, WRONG_SHAPE, BROKEN = "gated", "open", "wrong_shape", "broken"

#: **配置缺失时拒绝**的路由:503 是有意的,不是崩溃。
#:
#: 需要单独一类,是因为「503 因为没配」和「500 因为炸了」在状态码上一模一样,
#: 而我第一版把 `>= 500` 一律判成 BROKEN —— 于是刚修好的 fail-closed 门被守卫
#: 报成故障。**同一个折叠形状,这个文件里第三次,写在批评它的守卫里。**
#:
#: 还有第二个理由,S-238:这条路由的裁决**依赖环境**。生产上
#: `TELEGRAM_WEBHOOK_SECRET` 有值 → 无凭证得 403;沙箱里没值 → 503。
#: 一条随机器变的断言不是比率器。登记在这里 = 两个码都接受,且都算「拒绝了」。
FAIL_CLOSED_WHEN_UNCONFIGURED: dict[str, str] = {
    "/internal/telegram/webhook":
        "S-262:secret 未设时从 fail-open(200)改为 fail-closed(503)。"
        "生产有 secret ⇒ 403;本地无 secret ⇒ 503。两者都是拒绝。",
}


def _probe(client, method: str, path: str) -> tuple[str, str]:
    """不带凭证打一次,返回四值裁决之一 —— **不是「2xx / 非 2xx」**。

    折叠成两值正是初版的错:404(方法不对)、422(body 先炸)、抛异常(=500)
    全都长得像「安全」,而三者一个都没证明这条路由会拒绝无凭证的调用者。
    """
    kwargs = {"json": VALID_BODIES[path]} if method == "POST" and path in VALID_BODIES else {}
    try:
        r = client.request(method, path, **kwargs)
    except Exception as e:                                    # noqa: BLE001
        # 鉴权分支上抛异常 = 生产返回 500 而不是 401。四次实测都是这个形状。
        return BROKEN, f"{type(e).__name__}: {str(e)[:70]}"
    sc = r.status_code
    if sc in (401, 403):
        return GATED, str(sc)
    if sc == 503 and path in FAIL_CLOSED_WHEN_UNCONFIGURED:
        return GATED, "503 未配置 → 拒绝(登记在 FAIL_CLOSED_WHEN_UNCONFIGURED)"
    if 200 <= sc < 300:
        return OPEN, f"{sc} ({len(r.content)}B)"
    if sc >= 500:
        return BROKEN, f"{sc}: {r.text[:70]}"
    return WRONG_SHAPE, f"{sc}: {r.text[:70]}"   # 404 / 422 / 400 —— 什么都没证明


def _internal_routes():
    from tests.test_no_route_is_shadowed import _all_routes   # 不写第二个展平器
    out: dict[str, set[str]] = {}
    for p, ms in _all_routes():
        if not p.startswith("/internal/") or "{" in p:
            continue
        ms = ms if isinstance(ms, (list, set, tuple)) else [ms]
        out.setdefault(p, set()).update(m for m in ms if m not in ("HEAD", "OPTIONS"))
    return out


def test_every_internal_route_rejects_an_anonymous_caller():
    """打真请求,**用这条路由真正接受的方法**,四值裁决。"""
    os.environ.setdefault("INTERNAL_TOKEN", "guard-test-token")

    from fastapi.testclient import TestClient

    from src.api.main import app

    routes = _internal_routes()
    _check(f"枚举到 {len(routes)} 条 /internal/ 路由(下降进 _IncludedRouter)",
           len(routes) >= 20,
           f"只有 {len(routes)} 条 —— 朴素读 app.routes 只能看见 main.py 的 12 条")

    posts = sum(1 for ms in routes.values() if "POST" in ms)
    _check(f"用真实方法探(其中 {posts} 条是 POST,GET 打它们只会得到无意义的 404)",
           posts >= 10, f"只识别出 {posts} 条 POST —— 方法枚举可能没跟着路由一起展平")

    c = TestClient(app)
    exempt = set(PUBLIC_BY_DESIGN) | set(KNOWN_BROKEN)
    leaked, broken, unproven = [], [], []
    for p, methods in sorted(routes.items()):
        for m in sorted(methods):
            verdict, note = _probe(c, m, p)
            if verdict == OPEN and p not in PUBLIC_BY_DESIGN:
                leaked.append(f"{m} {p} → {note}")
            elif verdict == BROKEN and p not in KNOWN_BROKEN:
                broken.append(f"{m} {p} → {note}")
            elif verdict == WRONG_SHAPE and m == "POST" and p not in exempt:
                # 一条 POST 端点回 422/400 而我又没给它合法 body ⇒ 这次探测
                # **没有证明任何事**。沉默地当它安全,就是初版犯的错。
                unproven.append(f"{m} {p} → {note}  (给 VALID_BODIES 补一个合法 body)")

    _check("没有未登记的 /internal/ 路由对匿名调用者返回 2xx", not leaked,
           "; ".join(leaked[:5]))
    _check("没有未登记的路由在无凭证请求上抛异常(异常 = 500 而不是 401)",
           not broken, "; ".join(broken[:3]))
    _check("每条 POST 端点都被真正证明过(422 不算证明)", not unproven,
           "; ".join(unproven[:4]))

    # 名单只能减。**判据是 GATED,不是「非 2xx」** —— 否则一条坏掉的路由
    # 会被读成「已收口」,催我把它从名单删掉,而它在生产里照样 2xx。
    stale = []
    for p, why in PUBLIC_BY_DESIGN.items():
        if p not in routes:
            stale.append(f"{p}(路由已不存在)")
            continue
        if all(_probe(c, m, p)[0] == GATED for m in sorted(routes[p])):
            stale.append(f"{p}(已加门)")
    _check(f"PUBLIC_BY_DESIGN 里没有已收口/已消失的条目({len(stale)} 条待删)",
           not stale, "删掉这些行:" + ", ".join(stale[:5]))


def test_the_two_closed_routes_actually_reject():
    """S-262 收掉的两条 —— 三态都验:无 token / 错 token / 对 token。

    只验「无 token 被拒」不够:一个把所有请求都拒掉的路由也能通过那条断言,
    而那是把端点关死,不是加门。
    """
    os.environ["INTERNAL_TOKEN"] = "guard-test-token"

    from fastapi.testclient import TestClient

    from src.api.main import app
    c = TestClient(app)

    for p in ("/internal/prediction-track-record", "/internal/r77-forward-episodes"):
        no = c.get(p).status_code
        bad = c.get(p, headers={"X-Internal-Token": "wrong"}).status_code
        ok = c.get(p, headers={"X-Internal-Token": "guard-test-token"}).status_code
        _check(f"{p} 无 token → 401", no == 401, str(no))
        _check(f"{p} 错 token → 401", bad == 401, str(bad))
        _check(f"{p} 对 token → 非 401(不是把端点关死)", ok != 401, str(ok))


def test_no_hardware_names_in_public_internal_payloads():
    """规则 #8 延伸到 API 响应,不只是前端 (S-262)。

    今早修掉 `QuantMonitor.jsx` 两处模型名时(S-237),那条守卫只扫
    `dashboard/src/*.jsx` —— **API 响应不在它的扫描范围内**。
    于是 `/internal/health-summary` 的检查名叫 `mac_mini_push`、无鉴权公网可读,
    从未被任何东西看过。**守卫检查的面比它名字宣称的窄**,今天第四次。

    首跑抓到三处,而三处**不是同一类东西**,不能一起修:

        "Railway fills a deterministic fallback…"   契约里的描述文字 → 已改「the API」
        "supabase unconfigured — … Railway env set"  运维错误消息   → 见 FROZEN
        source: 'macmini_orderbook'                  **契约枚举值**  → 跨 lane

    最后一条改不得:它是 Mac↔Railway 契约里两侧都在读的值,单方面改名
    就是规则 #2 说的那种「先改代码后改契约」。要动它得先进 MINIMAX_SYNC §2、
    两侧确认、bump SCHEMA_VERSION。**把它冻结并写明原因,比偷偷改掉诚实。**
    """
    os.environ.setdefault("INTERNAL_TOKEN", "guard-test-token")

    from fastapi.testclient import TestClient

    from src.api.main import app

    # 冻结项:已知、有理由、**不许再增加**。key 是 (路由, 词)。
    FROZEN = {
        ("/internal/cis-scores/schema", "macmini"):
            "契约枚举值 executability.source='macmini_orderbook',两侧都在读。"
            "改名 = 契约变更,须先进 MINIMAX_SYNC §2 + bump SCHEMA_VERSION。",
        ("/internal/mac-push/schema", "railway"):
            "§NO-DIRECT-SUPABASE 这条 doctrine 文字本身在描述写入路径,"
            "受众是 Mac 侧工程,不是投资人。规则 #8 管的是 strategy.html 那一类面。",
        ("/internal/beta-core-clock-q", "railway"):
            "运维错误消息「Railway env set」—— 告诉运维该去哪设变量,"
            "去掉厂商名会让这条消息不可执行。同上,非投资人面。",
    }
    banned = ("mac_mini", "macmini", "ollama", "gemma", "railway", "fastapi", "upstash")
    c = TestClient(app)
    hits, thawed = [], []
    for p in sorted(PUBLIC_BY_DESIGN):
        try:
            r = c.get(p)
        except Exception:                                     # noqa: BLE001
            continue
        if not (200 <= r.status_code < 300):
            continue
        body = r.text.lower()
        for b in banned:
            if b in body and (p, b) not in FROZEN:
                hits.append(f"{p} 含 '{b}'")
            elif b not in body and (p, b) in FROZEN:
                thawed.append(f"{p}/{b}")
    _check("公开的 /internal/ 响应里没有新增的硬件/厂商名", not hits, "; ".join(hits[:5]))
    # 冻结名单同样只能减:已经清掉的词还留在里面 → 下一处泄漏会被它掩护。
    _check(f"FROZEN 里没有已清理的条目({len(thawed)} 条待删)", not thawed,
           "已不再出现,删掉:" + ", ".join(thawed[:4]))


if __name__ == "__main__":
    print("── /internal/ 鉴权:打真请求,不看拼写 (S-262) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED:")
        for f in _FAILURES:
            print(f"   - {f}")
        sys.exit(1)
    print("\n✓ /internal/ 鉴权守卫全绿")
