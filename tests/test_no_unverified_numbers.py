"""S-549(Jazz 10-12「删掉」):没被样本外验证过的数字不上页面、不进对外接口。

策略卡片曾写「目标年化 15–25% / 7–15% APY / 12–20%」「最大回撤 < 15% / 5% / 10%」,开源区写样本内
「Sharpe 6.2 · 32% CAGR」—— 和同一页组合器显示的真实记录并排。这里守两件事:页面源码里不再出现目标收益 /
回撤承诺的写法;开源策略目录不带样本内业绩数字。
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGES = ROOT / "dashboard" / "src"

FORBIDDEN = [
    (re.compile(r"Target (Return|APY|Yield)"), "target return / APY label"),
    (re.compile(r"\bmaxDD\s*:"), "max-drawdown promise field"),
    (re.compile(r"\d+\s*[–-]\s*\d+%\s*(ann|APY)", re.I), "return range presented as a target"),
    (re.compile(r"Sharpe \{s\.metrics"), "in-sample Sharpe headline"),
]


def test_no_target_returns_or_drawdown_promises_on_pages():
    hits = []
    for f in sorted(PAGES.rglob("*.jsx")):
        txt = f.read_text(encoding="utf-8")
        for rx, what in FORBIDDEN:
            for m in rx.finditer(txt):
                line = txt.count("\n", 0, m.start()) + 1
                hits.append(f"{f.relative_to(ROOT)}:{line} {what}: {m.group(0)!r}")
    assert not hits, "unverified forward numbers on a user-facing page:\n  " + "\n  ".join(hits)


def test_open_source_catalog_carries_no_in_sample_figures():
    from src.api.routers.strategies import OPEN_SOURCE_STRATEGIES
    for s in OPEN_SOURCE_STRATEGIES:
        assert s.get("metrics") is None, s["id"]
        assert "profitable" not in (s.get("honest_note") or "").lower(), s["id"]


def _served_pages():
    """vite.config.js 的 input = 实际被构建、被托管的页面。没在里面的 html(如下线的 win.html)不检查。"""
    cfg = (ROOT / "dashboard" / "vite.config.js").read_text(encoding="utf-8")
    live = [ln for ln in cfg.splitlines() if not ln.strip().startswith("//")]
    return [ROOT / "dashboard" / m for m in re.findall(r"resolve\(__dirname,\s*'([^']+\.html)'\)", "\n".join(live))]


def test_served_pages_make_no_regulatory_or_stale_count_claims():
    """S-552:strategy.html 的分享描述写「Hong Kong regulated」(我们没有持牌);多处写死「84 assets / 80+ assets」
    (实际 58,且会变);win.html 公开了机器型号与基础设施。被托管的页面里不能再出现这些。"""
    bad = [
        (re.compile(r"Hong Kong regulated|regulated in Hong Kong|SFC[- ]licensed|licensed by", re.I), "regulatory claim"),
        (re.compile(r"\b8\d\+?\s+assets\b", re.I), "hard-coded asset count"),
        (re.compile(r"Mac Mini|M4 Pro|Gemma|48\s?GB", re.I), "hardware internals"),
    ]
    hits = []
    pages = _served_pages()
    assert pages, "no served pages parsed from vite.config.js"
    for f in pages:
        txt = f.read_text(encoding="utf-8")
        for rx, what in bad:
            for m in rx.finditer(txt):
                hits.append(f"{f.name}:{txt.count(chr(10), 0, m.start()) + 1} {what}: {m.group(0)!r}")
    assert not hits, "\n  ".join(["served page claims:"] + hits)
