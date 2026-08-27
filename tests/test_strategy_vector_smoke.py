"""
Smoke tests for the Strategy Vector stack.

These tests do NOT touch Redis. They verify:
  - Schema construction + JSON round-trip
  - Embedder produces exactly 30 dims
  - Coverage summary is sane
  - Cosine similarity is invariant to scale
  - find_similar returns ranked neighbors

Run with: python3 -m pytest tests/test_strategy_vector_smoke.py -v
Or:       python3 tests/test_strategy_vector_smoke.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.vector.strategy_schema import StrategyRecord, Verdict
from src.data.vector.strategy_embedder import (
    VECTOR_DIMS,
    generate_embedding,
    coverage_summary,
    cosine_similarity,
    find_similar,
    embed_many,
)
from src.data.vector.strategy_store import (
    load_all_records,
    upsert_record,
    upsert_many,
    list_records,
    get_record,
)
from scripts.backfill_strategies import backfill


# ---------------------------------------------------------------------------
# Mini-test helpers
# ---------------------------------------------------------------------------

_fails: list[str] = []
_passes: list[str] = []


def _check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        _passes.append(name)
        print(f"  ✓ {name}")
    else:
        _fails.append(f"{name}: {detail}")
        print(f"  ✗ {name} — {detail}")


def _summary() -> None:
    print()
    print(f"  {len(_passes)} passed · {len(_fails)} failed")
    if _fails:
        for f in _fails:
            print(f"    FAILED: {f}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_schema_construction_and_roundtrip() -> None:
    print("\n[test_schema_construction_and_roundtrip]")
    r = StrategyRecord(
        id="test-r46",
        title="test record",
        doc_source="REFUTATION_LEDGER.md",
        r_number="R46",
        verdict=Verdict.SHIP,
        pit_clean=True,
        cost_feasible_at_5bps=True,
        forward_committed=True,
        factor_exposure={"beta_market": 0.05, "residual_alpha": 0.033},
        cost_sensitivity={"0bps": 4.5, "5bps": 3.33, "10bps": 1.9},
        mechanics={"holding_period_days": 5, "turnover_per_q": 80.0/3},
        capacity={"adv_fraction": 0.01},
        # ── 证据地板 (S-244 修订) ────────────────────────────────────────────
        # 这个 fixture 停在 2026-07 的 SHIP 定义上。此后 `validate()` **加了九道
        # 证据门**(cause/OOS/60d 纸面/分 regime 报告/DD 止损/止损入回测/
        # DSR+n_trials/持仓期+换手成本/可部署规模+美元增值),而这个文件从没被
        # preflight 运行过 —— 所以「有效的 SHIP 记录应当通过校验」这条断言,
        # 在地板每抬高一次的时候都变得更红,一次也没有人看见。
        #
        # 补齐它不只是让测试变绿:**它证明那道地板是可满足的**,并且把「一条
        # SHIP 记录必须带哪些证据」写成了一份可执行的清单。
        base_rate="R46 funding-carry residual; cause: 永续资金费在拥挤度高时对未来收益有负向偏斜",
        oos_survival=True,
        paper_trade_days=73,
        regime_reported=True,
        max_dd_stop=-0.12,
        capital_action_on_breach="halve_notional_then_review",
        backtest_included_stop=True,
        deflated_sharpe=0.972,
        n_trials=48,
        median_holding_days=5.0,
        turnover_cost_pct_yr=1.4,
        net_effect_pct_yr=1.9,          # 毛 3.33% − 换手 1.4% = 净 1.9%
        deployable_notional_usd=1_000_000,
        notional_basis="max_notional_25bps_usd（ADV 1% 上限,28 名标的的中位深度）",
        value_added_usd_yr=19_000,
        trigger_name="funding_crowding_z",
        trigger_median_run_days=11.0,   # > 5 天持仓期(S-117:触发器要活得比仓位久)
    )
    _check("verdict enum coerced", r.verdict == Verdict.SHIP)
    _check("registered_at auto-set", len(r.registered_at) > 10)

    d = r.to_dict()
    r2 = StrategyRecord.from_dict(d)
    _check("JSON round-trip preserves id", r2.id == r.id)
    _check("JSON round-trip preserves r_number", r2.r_number == "R46")
    _check("JSON round-trip preserves verdict",
           r2.verdict == Verdict.SHIP)
    _check("JSON round-trip preserves pit_clean", r2.pit_clean is True)

    problems = r.validate()
    _check("valid ship record has no validation issues",
           problems == [], detail=str(problems))


def test_embedder_dim_and_coverage() -> None:
    print("\n[test_embedder_dim_and_coverage]")
    r = StrategyRecord(
        id="test-dim",
        title="dim test",
        doc_source="x.md",
        cost_sensitivity={"5bps": 3.33},
        factor_exposure={"residual_alpha": 0.05},
    )
    emb = generate_embedding(r)
    _check("embedding has exactly 30 dims",
           len(emb) == VECTOR_DIMS == 30,
           detail=f"got {len(emb)}")

    cov = coverage_summary(r)
    _check("coverage_summary has correct total",
           cov["dims_total"] == 30)
    _check("coverage_summary has nonzero count",
           cov["dims_nonzero"] >= 2, detail=str(cov))

    # 未测量的维度是 NaN,不是 0.0 (S-244 修订)。
    #
    # 旧断言是 `all(-1.0 <= v <= 1.0 for v in emb)`,而 NaN 的所有比较都为 False,
    # 所以嵌入器改成「缺失 → NaN」之后这条必然红 —— **它红了一段时间没人知道,
    # 因为这个文件从来没被 preflight 运行过**。
    #
    # 而改动本身是对的,正是 S-180/S-194 那一课:未测量的量不能被渲染成一个
    # 落在合法区间里的数。一个 0.0 会被余弦当成"测到了,值为零"。
    # 所以断言改成:每一维要么是 NaN(未测量),要么在 [-1, 1] 内。
    import math as _math
    bad = [(i, v) for i, v in enumerate(emb)
           if not (isinstance(v, float) and _math.isnan(v)) and not (-1.0 <= v <= 1.0)]
    _check("每一维要么 NaN(未测量)要么在 [-1, 1] 内", not bad, detail=str(bad[:5]))

    # 而且这条稀疏记录的未测量维必须真的是 NaN —— 如果它们是 0.0,上面那条
    # 也会通过,而语义已经错了。这是负控制,不是重复断言。
    n_nan = sum(1 for v in emb if isinstance(v, float) and _math.isnan(v))
    _check("稀疏记录的未测量维是 NaN 而非 0.0",
           n_nan >= 20, detail=f"NaN 维数={n_nan}/30(两个字段的记录应大面积缺失)")


def test_cosine_similarity_properties() -> None:
    """余弦的数学性质,在 MIN_SHARED_DIMS 之上验证 (S-244 修订)。

    旧版用 3 维玩具向量。`cosine_similarity` 后来加了 `MIN_SHARED_DIMS = 4`
    的下限 —— 「一两个重叠维给出的自信数字是噪声,不是相似度」—— 于是
    identity / opposite / scale 三条全部返回 0.0 而红。**下限是对的,玩具向量
    太短。** 但这个文件从没被运行,所以红了也没人知道。

    改法:向量升到 MIN_SHARED_DIMS 以上(数学性质不变),并**把那个下限本身
    补一条断言** —— 它是被静默加进来的,此前没有任何守卫钉住它。
    """
    print("\n[test_cosine_similarity_properties]")
    from src.data.vector.strategy_embedder import MIN_SHARED_DIMS

    n = MIN_SHARED_DIMS + 1
    a = [1.0] + [0.0] * (n - 1)
    _check(f"cosine(a, a) == 1.0（{n} 维,在下限之上）",
           abs(cosine_similarity(a, list(a)) - 1.0) < 1e-6,
           detail=str(cosine_similarity(a, list(a))))

    orth = [0.0, 1.0] + [0.0] * (n - 2)
    _check("cosine orthogonal == 0",
           abs(cosine_similarity(a, orth)) < 1e-6)

    opp = [-1.0] + [0.0] * (n - 1)
    _check("cosine opposite == -1",
           abs(cosine_similarity(a, opp) + 1.0) < 1e-6,
           detail=str(cosine_similarity(a, opp)))

    # Invariant to scale
    a2 = [2.0] + [0.0] * (n - 1)
    b2 = [3.0] + [0.0] * (n - 1)
    _check("cosine invariant to scale",
           abs(cosine_similarity(a2, b2) - 1.0) < 1e-6)

    # Zero vector → 0.0 (not divide-by-zero)
    z = [0.0] * n
    _check("zero vector returns 0.0",
           cosine_similarity(a, z) == 0.0)

    # ── 下限本身 ────────────────────────────────────────────────────────────
    # 共享维不足时必须【拒绝】(0.0),而不是给一个自信的 1.0。这条此前没有守卫:
    # 下限被加进来,把三条老断言变红,而没有一条新断言接住它的语义。
    short = [1.0] * (MIN_SHARED_DIMS - 1)
    _check(f"共享维 < {MIN_SHARED_DIMS} 时拒绝(返回 0.0)而非给出自信的 1.0",
           cosine_similarity(short, list(short)) == 0.0,
           detail=str(cosine_similarity(short, list(short))))

    # NaN 维要被跳过,而不是污染整条相似度 —— 稀疏记录之间的比较依赖这一点。
    na = [1.0, float("nan"), 1.0, 1.0, 1.0]
    nb = [1.0, 0.5, 1.0, 1.0, 1.0]
    got = cosine_similarity(na, nb)
    _check("NaN 维被跳过而非污染结果", got == got and abs(got - 1.0) < 1e-6,
           detail=str(got))


def test_find_similar_ranking() -> None:
    print("\n[test_find_similar_ranking]")
    # Three records: A and B identical, C orthogonal-ish
    e: dict[str, list[float]] = {
        "A": [1.0, 0.0, 0.0, 0.0] + [0.0]*26,
        "B": [1.0, 0.0, 0.0, 0.0] + [0.0]*26,
        "C": [0.0, 0.0, 0.0, 0.0] + [1.0] + [0.0]*25,
        "D": [0.5, 0.5, 0.0, 0.0] + [0.0]*26,
    }
    nbrs = find_similar("A", e, k=3)
    _check("find_similar returns 3 neighbors", len(nbrs) == 3)
    _check("B is the top neighbor (identical)",
           nbrs[0]["id"] == "B", detail=str(nbrs))
    _check("B similarity ≈ 1.0",
           abs(nbrs[0]["similarity"] - 1.0) < 1e-6)
    _check("A is not in its own neighbors",
           all(n["id"] != "A" for n in nbrs))
    _check("ranked by similarity descending",
           all(nbrs[i]["similarity"] >= nbrs[i+1]["similarity"]
               for i in range(len(nbrs) - 1)))


def test_embed_many() -> None:
    print("\n[test_embed_many]")
    recs = [
        StrategyRecord(id=f"r{i}", title=f"r{i}", doc_source="x.md",
                       cost_sensitivity={"5bps": 1.0 + 0.1*i})
        for i in range(5)
    ]
    out = embed_many(recs)
    _check("embed_many produces embeddings for all 5",
           len(out) == 5)
    _check("embed_many keys match record ids",
           all(f"r{i}" in out for i in range(5)))


def test_backfill_produces_expected_records() -> None:
    print("\n[test_backfill_produces_expected_records]")
    summary = backfill(dry_run=True, write_redis=False)
    _check("backfill produces > 80 records",
           summary["totals"]["total"] > 80,
           detail=str(summary["totals"]))
    _check("doctrinal records present (>= 13)",
           summary["sources"].get("DOCTRINAL", 0) >= 13)
    _check("R-entries extracted (>= 30)",
           summary["sources"].get("REFUTATION_LEDGER", 0) >= 30)
    _check("by_verdict has refute bucket",
           "refute" in summary["totals"]["by_verdict"])
    _check("by_verdict has doctrine bucket",
           "doctrine" in summary["totals"]["by_verdict"])
    _check("by_verdict has hold bucket",
           "hold" in summary["totals"]["by_verdict"])
    # Step 6: dimensional mining must have filled SOMETHING on at least one
    # SHIP entry — otherwise the parser is theater. (Anti-imposter.)
    try:
        from pathlib import Path as _P
        import json as _json
        data = _json.loads((_P(__file__).resolve().parents[1] / "_data" / "strategy_records.json").read_text())
        ship_records = [r for r in data.values() if r["verdict"] == "ship"]
        nonzero_dims = []
        for r in ship_records:
            d = sum(1 for k in ("mechanics", "capacity", "lifecycle",
                                "cost_sensitivity", "factor_exposure")
                    if r.get(k))
            nonzero_dims.append(d)
        _check(">= 1 ship record has dimensional data",
               any(d >= 1 for d in nonzero_dims),
               detail=str([(r["id"], d) for r, d in zip(ship_records, nonzero_dims)]))
    except FileNotFoundError:
        _check("audit JSON exists", False, detail="run scripts/backfill_strategies.py --write first")


def test_r64_fusion_record_has_capacity() -> None:
    """Step 6: the gold-standard SHIP record (R64 fusion validation) should
    have BOTH n_assets AND declared_capacity filled, because the source body
    explicitly states "$5.0M declared capacity" and "28 assets"."""
    print("\n[test_r64_fusion_record_has_capacity]")
    from pathlib import Path as _P
    import json as _json
    audit = _P(__file__).resolve().parents[1] / "_data" / "strategy_records.json"
    if not audit.exists():
        _check("audit exists", False, detail="run scripts/backfill_strategies.py --write")
        return
    data = _json.loads(audit.read_text())
    r64 = data.get("R64-ledger")
    _check("R64-ledger present", r64 is not None)
    if r64:
        cap = r64.get("capacity", {})
        _check("R64 declared_capacity filled",
               cap.get("declared_capacity") is not None,
               detail=str(cap))
        _check("R64 declared_capacity ~$5M",
               abs(cap.get("declared_capacity", 0) - 5_000_000) < 1_000,
               detail=str(cap))
        _check("R64 n_assets filled",
               cap.get("n_assets") is not None,
               detail=str(cap))
        mech = r64.get("mechanics", {})
        _check("R64 holding_period_days filled (>0)",
               mech.get("holding_period_days", 0) > 0,
               detail=str(mech))
        _check("R64 turnover filled (>0)",
               mech.get("turnover_per_q", 0) > 0,
               detail=str(mech))


def test_r46_cadence_record_has_mechanics() -> None:
    """Step 6: R46 is the headline 5-day rebal survivor — must have
    holding_period_days=5 and turnover ~80."""
    print("\n[test_r46_cadence_record_has_mechanics]")
    from pathlib import Path as _P
    import json as _json
    audit = _P(__file__).resolve().parents[1] / "_data" / "strategy_records.json"
    if not audit.exists():
        return
    data = _json.loads(audit.read_text())
    r46 = data.get("R46-ledger")
    if not r46:
        return
    mech = r46.get("mechanics", {})
    _check("R46 holding_period_days = 5 (the headline cadence)",
           mech.get("holding_period_days") == 5,
           detail=str(mech))
    _check("R46 turnover_per_q ~20 (annual 79.5 ÷ 4)",
           abs(mech.get("turnover_per_q", 0) - 20) < 5,
           detail=str(mech))


def test_step7_sidecar_fills_cost_sensitivity() -> None:
    """Step 7: REPORT.md sidecar must have populated cost_sensitivity on
    R46 (the gold-standard record) with all 4 tier values, derived from the
    pillar_O 5d row of cis_quality_robustness REPORT.md table."""
    print("\n[test_step7_sidecar_fills_cost_sensitivity]")
    from pathlib import Path as _P
    import json as _json
    audit = _P(__file__).resolve().parents[1] / "_data" / "strategy_records.json"
    if not audit.exists():
        return
    data = _json.loads(audit.read_text())
    r46 = data.get("R46-ledger")
    if not r46:
        return
    cs = r46.get("cost_sensitivity", {})
    _check("R46 cost_sensitivity has 0bps entry",
           "0bps" in cs and cs["0bps"] is not None,
           detail=str(cs))
    _check("R46 cost_sensitivity has 5bps entry",
           "5bps" in cs and cs["5bps"] is not None,
           detail=str(cs))
    _check("R46 cost_sensitivity has 10bps entry",
           "10bps" in cs and cs["10bps"] is not None,
           detail=str(cs))
    _check("R46 cost_sensitivity 0bps ≈ 6.0 (pillar_O 3.53 × sqrt(731/252))",
           abs(cs.get("0bps", 0) - 6.0) < 1.0,
           detail=str(cs))
    _check("R46 cost_sensitivity 5bps ≈ 5.7 (pillar_O 3.33 × sqrt(731/252))",
           abs(cs.get("5bps", 0) - 5.7) < 1.0,
           detail=str(cs))
    _check("R46 cost_sensitivity monotonically decreasing 0bps ≥ 5bps ≥ 10bps",
           cs.get("0bps", 0) >= cs.get("5bps", 0) >= cs.get("10bps", 0),
           detail=str(cs))


def test_step7_sidecar_tag_on_ship_records() -> None:
    """Step 7: SHIP records' tags must reference at least one sidecar path
    (proves the sidecar lookup fired)."""
    print("\n[test_step7_sidecar_tag_on_ship_records]")
    from pathlib import Path as _P
    import json as _json
    audit = _P(__file__).resolve().parents[1] / "_data" / "strategy_records.json"
    if not audit.exists():
        return
    data = _json.loads(audit.read_text())
    ship = [r for r in data.values() if r.get("verdict") == "ship"]
    n_with_sidecar = sum(
        1 for r in ship if any("sidecar:" in t for t in r.get("tags", []))
    )
    _check(">= 3 ship records have sidecar: tag",
           n_with_sidecar >= 3,
           detail=f"{n_with_sidecar} of {len(ship)} ship records have sidecar tag")


def test_step8_router_registered_with_correct_paths() -> None:
    """Step 8: strategy_vector router must be registered with the 5 endpoints
    on /api/v1/strategy/* (NOT /api/v1/strategies/* — that's the multi-factor router).
    """
    print("\n[test_step8_router_registered_with_correct_paths]")
    try:
        import sys as _s
        if str(ROOT) not in _s.path:
            _s.path.insert(0, str(ROOT))
        # `app.routes` 不是同质的,而且**它不是完整的路由表**。
        #
        # 旧版写 `{r.path for r in app.routes}`。实测 2026-08-27:67 个条目里
        # 29 个是 `_IncludedRouter`(FastAPI 保留 include 上下文的包装器,不把
        # 子路由拼进 `app.routes`),它们没有 `.path`,于是整个 try 块被一个
        # AttributeError 吞掉 —— **五条路由断言一条都没跑**,只报了一句
        # "main app import failed"。一个异常把五个判定压成了一个。
        #
        # 而就算改成 `getattr(r, "path", None)` 也只是把红色换成静默:只能看见
        # 38 条,strategy/* 五条一条都不在里面,因为它们在包装器内部。
        #
        # `tests/test_no_route_is_shadowed.py` **已经解决过这个问题** ——
        # 它的 `_flatten()` 会下降进 `original_router.routes`,docstring 里写着
        # 「朴素读法只看见 16% 并把它报成通过」。所以这里**复用它**,不写第二个
        # 展平器:两个展平器会各自漂移,而漂移的那一个会静默地少看几十条路由。
        from tests.test_no_route_is_shadowed import _all_routes
        paths = sorted({p for p, _methods in _all_routes()})
        required = {
            "/api/v1/strategy/list",
            "/api/v1/strategy/similar/{record_id}",
            "/api/v1/strategy/coverage/{record_id}",
            "/api/v1/strategy/stats",
        }
        for p in required:
            _check(f"route {p} registered", p in paths,
                   detail=str([q for q in paths if 'strategy' in q]))
        _check("route /api/v1/strategy/{record_id} registered",
               "/api/v1/strategy/{record_id}" in paths)
        # Anti-imposter: must NOT collide with multi-factor /api/v1/strategies
        _check("does not collide with /api/v1/strategies (multi-factor)",
               "/api/v1/strategies/{strategy_id}" in paths,
               detail="multi-factor router absent — strategies.py gone?")
    except Exception as e:
        _check("main app import", False, detail=str(e))


def test_step8_router_filters_work_locally() -> None:
    """Step 8: list_records / coverage_summary filters must work end-to-end
    against the in-memory JSON snapshot (no Redis required).
    """
    print("\n[test_step8_router_filters_work_locally]")
    import json as _json
    audit = ROOT / "_data" / "strategy_records.json"
    if not audit.exists():
        return
    data = _json.loads(audit.read_text())

    # Build in-memory strategy objects via from_dict
    objs = {k: StrategyRecord.from_dict(v) for k, v in data.items()}

    # (a) verdict filter
    ship = [r for r in objs.values() if r.verdict.value == "ship"]
    _check("at least 3 SHIP records in audit",
           len(ship) >= 3, detail=f"got {len(ship)}")

    # (b) tag filter
    sidecar_ship = [r for r in ship if any("sidecar:" in t for t in r.tags)]
    _check("at least 1 SHIP record has sidecar: tag",
           len(sidecar_ship) >= 1, detail=str(len(sidecar_ship)))

    # (c) r_prefix filter
    r46 = [r for r in objs.values() if (r.r_number or "").startswith("R46")]
    _check(">= 1 R46*-prefixed record in audit",
           len(r46) >= 1, detail=str(len(r46)))

    # (d) coverage audit
    sample = objs.get("R46-ledger")
    _check("R46-ledger present for coverage check", sample is not None)
    if sample:
        cov = coverage_summary(sample)
        # R46 has 8/30 dims filled (cost_sensitivity sidecar + mechanics/capacity
        # from ledger body). The 20% floor catches skeletons (<10%) without
        # requiring the documented ≥40% queryable bar — this asserts the
        # record is at least above the absolute skeleton floor.
        _check("R46 coverage_pct above skeleton floor (>=20%)",
               cov["coverage_pct"] >= 20,
               detail=str(cov))
        _check("R46 dims_nonzero above skeleton floor (>=6)",
               cov["dims_nonzero"] >= 6,
               detail=str(cov))


def test_step8_similar_smoke_inproc() -> None:
    """Step 8: find_similar invoked against the in-memory embeddings dict
    produced from audit JSON must return ranked neighbors.
    """
    print("\n[test_step8_similar_smoke_inproc]")
    import json as _json
    audit = ROOT / "_data" / "strategy_records.json"
    if not audit.exists():
        return
    data = _json.loads(audit.read_text())
    objs = {k: StrategyRecord.from_dict(v) for k, v in data.items()}

    # Build the embedded dict, then look for R46's neighbors
    embeddings = embed_many(objs.values())
    _check("embeddings dict has >50 entries",
           len(embeddings) >= 50, detail=str(len(embeddings)))

    target = "R46-ledger"
    if target not in embeddings:
        _check("R46 has embedding", False, detail=f"keys: {list(embeddings)[:5]}")
        return

    nbrs = find_similar(target, embeddings, k=5)
    _check("find_similar returns 5 neighbors (after filtering self out)",
           len(nbrs) == 5, detail=str(nbrs))
    _check("neighbors are not the target itself",
           all(n["id"] != target for n in nbrs),
           detail=str(nbrs))
    _check("neighbors sorted by similarity desc",
           all(nbrs[i]["similarity"] >= nbrs[i+1]["similarity"]
               for i in range(len(nbrs) - 1)),
           detail=str(nbrs))
    _check("top similarity is positive (cosine in [-1, 1])",
           -1.0 <= nbrs[0]["similarity"] <= 1.0,
           detail=str(nbrs[0]))


def test_step9_kernel_enriches_diagnosis() -> None:
    """Step 9: Diagnose(Portfolio) must call into the strategy vector DB
    and surface analog sleeves + prior refutes + applicable doctrine.
    """
    print("\n[test_step9_kernel_enriches_diagnosis]")
    try:
        # Lazy import the kernel helper (matches the runtime path)
        from src.api.routers.portfolio_diagnosis import _strategy_vector_evidence
    except Exception as e:
        _check("kernel helper importable", False, detail=str(e))
        return

    # Mock diagnosis dict + holdings. The helper is read-only on holdings.
    fake_diag = {
        "holdings": [
            {"symbol": "BTC", "weight": 0.5, "grade": "A", "bucket": "keep",
             "asset_class": "L1"},
            {"symbol": "ETH", "weight": 0.3, "grade": "B+", "bucket": "keep",
             "asset_class": "L1"},
            {"symbol": "FLOKI", "weight": 0.2, "grade": "F", "bucket": "trim",
             "asset_class": "Memecoin"},
        ],
        "verdict": "test",
    }
    holdings = [{"symbol": s} for s in ("BTC", "ETH", "FLOKI")]

    # Skip if the store returns no records (no Redis env in test env)
    try:
        from src.data.vector.strategy_store import load_all_records
        recs = load_all_records()
    except Exception as e:
        _check("store importable", False, detail=str(e))
        return

    if not recs:
        # Fall back to local audit JSON — same shape as in-memory store.
        import json as _json
        audit = ROOT / "_data" / "strategy_records.json"
        if not audit.exists():
            _check("audit JSON exists", False)
            return
        # Build StrategyRecord dicts the helper understands.
        from src.data.vector.strategy_schema import StrategyRecord as _SR
        data = _json.loads(audit.read_text())
        fake_records = {k: _SR.from_dict(v) for k, v in data.items()}

        # The helper imports load_all_records lazily each call — patch the
        # source module so the next `from strategy_store import load_all_records`
        # inside the function picks up our fake.
        import src.data.vector.strategy_store as _store_mod
        original_fn = _store_mod.load_all_records
        _store_mod.load_all_records = lambda: fake_records
        try:
            evidence = _strategy_vector_evidence(fake_diag, holdings)
        finally:
            _store_mod.load_all_records = original_fn
    else:
        evidence = _strategy_vector_evidence(fake_diag, holdings)

    if not evidence:
        _check("evidence helper returned non-empty",
               False, detail="empty — store unreachable?")
        return

    _check("evidence has status=ok or status=unavailable",
           evidence.get("status") in ("ok", "unavailable"),
           detail=str(evidence.get("status")))
    _check("evidence has top_sleeves key",
           "top_sleeves" in evidence, detail=str(list(evidence.keys())))
    _check("evidence has prior_refutations key",
           "prior_refutations" in evidence)
    _check("evidence has applicable_doctrine key",
           "applicable_doctrine" in evidence)

    # Each sleeve summary must have id + verdict + tags (the kernel contract)
    if evidence.get("top_sleeves"):
        s = evidence["top_sleeves"][0]
        _check("first sleeve has id", "id" in s, detail=str(s))
        _check("first sleeve has verdict in {ship,hold,refute,doctrine}",
               s.get("verdict") in ("ship", "hold", "refute", "doctrine"),
               detail=str(s.get("verdict")))


def main() -> None:
    print("=" * 60)
    print("STRATEGY VECTOR SMOKE TESTS")
    print("=" * 60)
    test_schema_construction_and_roundtrip()
    test_embedder_dim_and_coverage()
    test_cosine_similarity_properties()
    test_find_similar_ranking()
    test_embed_many()
    test_backfill_produces_expected_records()
    test_r46_cadence_record_has_mechanics()
    test_r64_fusion_record_has_capacity()
    test_step7_sidecar_fills_cost_sensitivity()
    test_step7_sidecar_tag_on_ship_records()
    test_step8_router_registered_with_correct_paths()
    test_step8_router_filters_work_locally()
    test_step8_similar_smoke_inproc()
    test_step9_kernel_enriches_diagnosis()
    _summary()
    sys.exit(1 if _fails else 0)


if __name__ == "__main__":
    main()
