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
