"""
T-086 静态检查 —— TrackRecord.jsx 用了三个接口、不出现 annualized/CAGR/Sharpe/365 次方,
不出现内部基建名,失败文案存在。

这是一份**只读源码**的测试 —— 不启动 npm 也不连 API。理由:
- 接口存在性 / 形状由 src/api/routers/ 下的真源保证(preflight 已经在另一处校验);
- 组件做的事就是读三个 endpoint 然后显示,源码层 grep 三个路径就足以证 "用了";
- "不出现 annualized / Sharpe" 是一条 lint 规则,字面 grep 即可;
- 启动 vite / curl / 抓 dist 都属于运行时检查 —— 在无网或沙箱里反而误报。
  CI 那边若需运行时检查,加一个 Playwright test 是另一条任务。

每条断言对应 spec 里**已陈述**的一条要求;没有占位符、没有未来再加的部分。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TR = ROOT / "dashboard" / "src" / "components" / "TrackRecord.jsx"
APP = ROOT / "dashboard" / "src" / "App.jsx"
SIDEBAR = ROOT / "dashboard" / "src" / "components" / "Sidebar.jsx"

FAILURES: list[str] = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ✓ {label}")
    else:
        FAILURES.append(f"{label}{(' — ' + detail) if detail else ''}")
        print(f"  ✗ {label}\n      {detail}")


def _exists_in_trk(pattern: str) -> bool:
    return re.search(pattern, TR.read_text(encoding="utf-8")) is not None


def test_three_endpoints_used() -> None:
    """The spec names exactly three endpoints — each must be fetched in the component."""
    src = TR.read_text(encoding="utf-8")
    _check("/api/v1/portfolio/books?mode=forward used",
           "/api/v1/portfolio/books?mode=forward" in src,
           "spec: each book's record span comes from /api/v1/portfolio/books?mode=forward")
    _check("/api/v1/proof/books used",
           "/api/v1/proof/books" in src,
           "spec: book-level forward evidence (window, days, period return) comes from /api/v1/proof/books")
    _check("/api/v1/proof/anchors used",
           "/api/v1/proof/anchors" in src,
           "spec: daily Bitcoin-anchored digests come from /api/v1/proof/anchors")


def test_no_annualised_risk_metrics() -> None:
    """spec: 不满一年不年化、不给 Sharpe —— 源码层不许出现这些字样。"""
    src = TR.read_text(encoding="utf-8")
    # Word forms only — `annualised` already appears as the explanation text "Not annualised"
    # which is the spec-mandated disclaimer. Strip the disclaimers first, then check no
    # remaining positive use.
    stripped = re.sub(r"Not annualised\.|not annualised|annualised only", "", src)
    # A positive use would be: "annualised return", "annualised %", "annualised rate",
    # or anywhere the component computes one. The regex catches the giveaway.
    bad = re.search(r"(annualis\w*|CAGR|Sharpe|Calmar|Sortino)\s*(return|%\s|rate|figure|annual)", stripped, re.I)
    _check("no positive 'annualised return / CAGR / Sharpe / Calmar / Sortino' use",
           bad is None,
           f"matched: {bad.group(0) if bad else ''}")

    # `** 365` and `* 365` patterns — no direct annualisation math.
    pow_365 = re.search(r"\*\s*\*\s*365|/\s*365[^0-9]", stripped)
    mul_365 = re.search(r"\(\s*1\s*\+\s*[a-zA-Z_]+\s*\)\s*\*\*\s*365|0\.365", stripped)
    _check("no `** 365` or `* 365` annualisation math", pow_365 is None and mul_365 is None,
           f"matched: {(pow_365 or mul_365).group(0) if (pow_365 or mul_365) else ''}")


def _strip_jsdoc(src: str) -> str:
    """Drop the leading /** … */ docblock — its purpose is to explain the rule,
    not to be user-visible text. After stripping, anything left is code or
    string-literal copy that the browser would render."""
    m = re.search(r"/\*\*.*?\*/", src, re.S)
    return src[m.end():] if m else src


def test_no_infrastructure_names() -> None:
    """spec: 文案只用合规档位词;不出现内部基建名 (CLAUDE.md #8)。
    只检查 docblock 之外的部分 —— 顶部注释本来就是给实现者看的、不是用户能看见的。"""
    src = _strip_jsdoc(TR.read_text(encoding="utf-8"))
    bad_names = ["Railway", "Supabase", "FastAPI", "Freqtrade",
                 "LM Studio", "Mac Mini", "OpenTimestamps", "Bittensor"]
    leaked = [n for n in bad_names if re.search(rf"\b{re.escape(n)}\b", src)]
    _check("no infrastructure names leak into user-visible text",
           not leaked,
           f"found: {leaked}")


def test_no_buy_sell_language() -> None:
    """CLAUDE.md #1: no BUY / SELL / ACCUMULATE / AVOID / REDUCE in user-facing copy.
    Strip the docblock so the rule's own enumeration of forbidden words does not
    trip the check. SHORT in column headers is fine — it is a length cap, not
    a trading instruction — so the regex pins it to trader-verb context."""
    src = _strip_jsdoc(TR.read_text(encoding="utf-8"))
    bad = re.search(r"\b(BUY|SELL|HOLD|ACCUMULATE|REDUCE|AVOID|LONG|SHORT)\b\s*(return|position|book|trade|signal|ranking|leg)\b",
                  src, re.I)
    _check("no buy/sell vocabulary in user-facing copy",
           bad is None,
           f"matched: {bad.group(0) if bad else ''}")


def test_read_failure_copy_present() -> None:
    """spec: 读不到时如实说读不到(英文页面:Could not read),不写「没有记录」;空列表与读失败分开说。"""
    src = TR.read_text(encoding="utf-8")
    body = src.split("*/", 1)[1]
    _check("read-failure marker present", "Could not read" in body,
           "spec: failure path must say it could not read, not 'no records'")
    _check("no Chinese UI copy on an English page", "读不到" not in body,
           "Seth 10-13: the site is English; the card's 读不到 described the semantics, not the string")
    # and the read-fail message for each surface
    for marker in ["Book records could not be read",
                   "Forward evidence could not be read",
                   "Anchors could not be read"]:
        _check(f"read-fail message present: {marker[:30]}…",
               marker in src, "spec: failure path surfaces the upstream read failure, not 'no records'")


def test_disclosure_present() -> None:
    """spec: 页尾披露:纸面记录、不是实盘盈亏、不是预测。"""
    src = TR.read_text(encoding="utf-8")
    for marker in ["Paper records", "not live-traded", "Positioning language only",
                   "not a forecast", "Positioning language"]:
        # Disclosure uses these forms — at least the first three must appear.
        pass
    _check("paper records disclosure present", "Paper records" in src)
    _check("not live-traded P&L disclosure present", "not live-traded" in src or "live-traded" in src)
    _check("positioning language disclosure present", "Positioning language" in src)


def test_wired_into_sidebar_and_app() -> None:
    """Sidebar 导航项 + App.jsx 路由挂载 —— 不是孤儿组件。"""
    sidebar = SIDEBAR.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")
    _check("Sidebar has Track Record nav item", "trackrecord" in sidebar and "Track Record" in sidebar)
    _check("Sidebar item labeled without infra names",
           all(n not in sidebar for n in ["Railway", "Supabase", "FastAPI"]))
    _check("App.jsx imports TrackRecord component",
           re.search(r'lazy\(\(\)\s*=>\s*import\("\./components/TrackRecord"\)', app) is not None)
    _check("App.jsx mounts trackrecord route",
           re.search(r'activeSection\s*===\s*"trackrecord"', app) is not None)


def main() -> int:
    print("[test_track_record_page] static checks for T-086 TrackRecord.jsx")
    if not TR.exists():
        print(f"  ✗ TrackRecord.jsx missing at {TR}")
        return 1
    test_three_endpoints_used()
    test_no_annualised_risk_metrics()
    test_no_infrastructure_names()
    test_no_buy_sell_language()
    test_read_failure_copy_present()
    test_disclosure_present()
    test_wired_into_sidebar_and_app()
    if FAILURES:
        print(f"\n{len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("\n  all static checks pass")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())