"""对外文本的边界(硬规则 1 与 8;11-14 Jazz「措辞与内部信息」)。

11-14 实测线上 121 个公开 GET 接口,22 个的响应里带着台账编号 / 仓库路径 / 基础设施名字 / 一条本机路径,`crowd-clock` 的五句
全是祈使句。原守卫只扫路由与前端的字面量;这些字符串写在数据层,由路由原样端出去。这里守的是已知的出口,线上全量由
`scripts/public_surface_scan.py` 在部署后逐接口核。
"""
import dataclasses
import pathlib
import re

from src.api.contracts import public_text as pt

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: 11-14 当天真在线上的句子 —— 守卫必须对它们每一句都响
WAS_LIVE = (
    "Fear extreme — a selective mean-reversion window, NOT a broad long: at a 30d horizon momentum has beaten reversal in crypto (R24), "
    "so size the contrarian sleeve modestly and wait for its own deep-extreme trigger.",
    "Basing — quiet accumulation of quality; low urgency, build the core.",
    "Trend-confirmation phase — the window to press confirmed strength (the trend sleeve's home).",
    "Late-cycle strength — trim into it, defend; crowded longs are flush fuel, do not chase.",
    "Topping — reduce gross, hedge; leadership narrowing as the marginal buyer thins.",
    "and price momentum are both accelerating — optimal entry before a trend becomes consensus.",
    "tilted toward the stronger half (S-581 / S-584).",
    "Captured by shorting the benchmark at the estimated β. Mirrors src/data/market/beta_adjust.py.",
    "/Users/sbb/.claude/projects/-Users-sbb/memory/r25-r73b-default-killed.md",
    "Binance geo-blocked on Railway — mitigated by CG Pro aggregation.",
    "use cash_book or sleeve_book (S-283, docs/NAV_POLICY.md §8).",
    "stored in Redis position store.",
    "core structurally dead (R57) — holding zero size, marking flat",
    "meet institutional threshold (58). T1 Mac Mini scores.",
    "mac_mini_T1_full",
    "railway_T2_estimate",
    "Check /internal/cis-scores payload and the [CONTRACT] warning in Railway logs.",
    "MIT · FREQTRADE",
)


def _findings(x):
    return pt.internal_findings(x) + pt.wording_findings(x)


def test_the_guard_fires_on_every_sentence_that_was_live():
    for s in WAS_LIVE:
        assert _findings(s), f"守卫没响:{s[:60]}"
    assert not _findings("Topping: leadership is narrowing and marginal demand is thinning.")
    assert not pt.internal_findings("MEV tip redistribution — structural yield premium"), "redistribution 里的 redis 不是 Redis"
    assert not pt.internal_findings("R2 of the regression was 0.31; S-1 filings are public")


def test_strip_refs_takes_only_parenthesised_ledger_ids():
    assert pt.strip_refs("held equally, tilted toward the stronger half (S-581 / S-584).") == "held equally, tilted toward the stronger half."
    assert pt.strip_refs("持有市场吃 beta;FoF 的本体(S-472/S-473/S-556)") == "持有市场吃 beta;FoF 的本体"
    assert pt.strip_refs("core inactive (R57) — flat") == "core inactive — flat"
    assert pt.strip_refs("worst-5% drawdown (about -25%)") == "worst-5% drawdown (about -25%)", "别的括号不动"
    d = pt.scrub({"title": "A (R57)", "doc_source": "/Users/x/memory/a.md", "n": 3, "tags": ["x (S-12)"]}, drop_keys=("doc_source",))
    assert d == {"title": "A", "n": 3, "tags": ["x"]}


def test_crowd_clock_describes_and_does_not_instruct():
    from src.data.market import crowd_clock as cc
    from tests.test_compliance_language import _FORBIDDEN
    assert set(cc._PHASE_POSTURE) == set(cc.PHASES)
    for phase, text in cc._PHASE_POSTURE.items():
        assert not _findings(text) and not _FORBIDDEN.search(text), f"{phase}: {text}"


def test_track_record_lines_strategy_cards_and_books_leave_clean():
    from src.api.routers.strategies import STRATEGIES
    from src.data.accounting.other_lines import LINES
    from src.data.accounting.registry import BOOKS
    for line in LINES:
        for f in dataclasses.fields(line):
            v = getattr(line, f.name)
            assert not (isinstance(v, str) and pt.internal_findings(v)), f"{line}: {pt.internal_findings(v)}"
            assert not (isinstance(v, str) and pt.wording_findings(v)), f"{line}: {pt.wording_findings(v)}"
    for s in STRATEGIES.values():
        assert not _findings(s["description"]), s["description"]
    assert all("fq_class" in s and "freqtrade_class" not in s for s in STRATEGIES.values()), "Jazz 11-14:这个名字对外叫 fq"
    from src.data.cis.provenance import attach_provenance  # noqa: F401 —— 引擎标签不带设备名
    import src.data.cis.provenance as prov
    assert not pt.internal_findings(open(prov.__file__, encoding="utf-8").read().split('"engine":')[1].split("\n")[0])
    for b in BOOKS:                                             # 登记表对内保留括号里的编号;出门那一步(/proof/books)过 scrub
        assert not pt.internal_findings(pt.scrub(dataclasses.asdict(b))), (b.id, pt.internal_findings(pt.scrub(dataclasses.asdict(b))))


def test_strategy_records_leave_without_their_source_path():
    from src.api.routers import strategy_vector as sv
    d = sv._public({"id": "x", "title": "Pair trade (R73)", "doc_source": "/Users/sbb/.claude/projects/memory/x.md", "verdict": "refute"})
    assert "doc_source" not in d and d["title"] == "Pair trade" and not pt.internal_findings(d)
    src = (ROOT / "src/api/routers/strategy_vector.py").read_text(encoding="utf-8")
    assert ".to_dict()" in src and src.count("_public(") >= 5 and '"by_source"' not in src, "每一处 to_dict 都要过 _public;by_source 的键就是路径"


_LIT = re.compile(r'"([^"\\]{12,400})"|\'([^\'\\]{12,400})\'|>([^<>{}]{12,400})<')


def _rendered_literals(text: str):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)             # 块注释(含 {/* … */})
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("//"):
            continue
        code = re.split(r"(?:^|\s)//\s", line)[0]
        for m in _LIT.finditer(code):
            lit = next(g for g in m.groups() if g)
            if not lit.startswith(("http://localhost", "https://")):
                yield i, lit


def test_dashboard_source_and_llms_txt_name_no_internals():
    bad = []
    for p in sorted((ROOT / "dashboard/src").rglob("*.js*")):
        for i, lit in _rendered_literals(p.read_text(encoding="utf-8", errors="ignore")):
            m = pt.INTERNAL.search(lit)
            if m:
                bad.append(f"{p.relative_to(ROOT)}:{i}: {m.group(0)!r} in {lit[:70]!r}")
    for i, line in enumerate((ROOT / "dashboard/public/llms.txt").read_text(encoding="utf-8").splitlines(), 1):
        m = re.search(r"railway|redis|mac mini|supabase|upstash|ollama|fastapi|lm studio", line, re.I)
        if m:
            bad.append(f"dashboard/public/llms.txt:{i}: {m.group(0)!r}")
    for name in ("dashboard/public/privacy.html", "dashboard/dist/privacy.html"):      # Jazz 11-14:隐私页也不点名
        for i, line in enumerate((ROOT / name).read_text(encoding="utf-8").splitlines(), 1):
            m = re.search(r"supabase|upstash|railway|\bredis\b", line, re.I)
            if m:
                bad.append(f"{name}:{i}: {m.group(0)!r}")
    assert not bad, "前端 / llms.txt 里有内部名字:\n  " + "\n  ".join(bad[:20])


def test_scan_script_judges_a_payload_the_same_way():
    import importlib.util
    spec = importlib.util.spec_from_file_location("pss", ROOT / "scripts" / "public_surface_scan.py")
    pss = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pss)
    hit = pss.judge("/api/v1/x", {"note": "core dead (R57)", "posture": "trim into it, defend; do not chase"})
    assert hit["internal"] and hit["wording"]
    assert pss.judge("/api/v1/x", {"note": "Topping: leadership is narrowing."}) is None
    assert pss.judge("/api/v1/intelligence/macro-events", {"events": [{"title": "Analysts say investors should watch X"}]}) is None, "第三方标题带署名引用,不算我们的话"
    assert pss.public_get_paths({"paths": {"/api/v1/a": {"get": {}}, "/internal/b": {"get": {}}, "/api/v1/c/{id}": {"get": {}}, "/api/v1/d": {"post": {}}}}) == ["/api/v1/a"]
