"""外部注意力数据入库(S-628 / S-629):映射规则按预注册写死、配额不被重启烧掉、key 不进输出、主程序真的排了循环。"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.market import social_ingest as si  # noqa: E402

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


class _R:
    def __init__(self, ok=True, why=""):
        self.ok, self.why = ok, why


def test_mapping_rule_is_the_preregistered_one():
    assert si.normalize_symbol("1000PEPE") == "PEPE"
    assert si.normalize_symbol("1000000MOG") == "MOG"
    assert si.normalize_symbol("1INCH") == "1INCH"
    assert si.normalize_symbol("1000") == "1000"
    projects = [
        {"slug": "pepe", "ticker": "PEPE", "marketcapUsd": 5e9},
        {"slug": "threshold", "ticker": "T", "marketcapUsd": 1e8},
        {"slug": "t-small", "ticker": "T", "marketcapUsd": 1e6},
        {"slug": "one-a", "ticker": "ONE", "marketcapUsd": None},
        {"slug": "one-b", "ticker": "ONE"},
        {"slug": "Bad Slug", "ticker": "BAD"},
    ]
    rows, info = si.build_slug_map(projects, ["1000PEPE", "T", "ONE", "BAD", "NEIROETH"])
    by = {r["symbol"]: r for r in rows}
    assert by["1000PEPE"]["slug"] == "pepe"
    assert by["T"]["slug"] == "threshold" and by["T"]["n_candidates"] == 2, "撞名取市值最大的"
    assert by["ONE"]["slug"] is None and "ONE" in info["ambiguous_unresolved"], "撞名又没市值 ⇒ 不进,不瞎选"
    assert by["BAD"]["slug"] is None, "slug 不合法的项目不拿来拼查询"
    assert by["NEIROETH"]["slug"] is None and "NEIROETH" in info["unmatched"]
    assert len(rows) == 5, "没匹配上的也落一行,免得每天重试"


def test_parse_per_slug_fans_out_to_symbols():
    payload = [{"datetime": "2026-01-01T00:00:00Z", "data": [{"slug": "pepe", "value": 12}, {"slug": "x", "value": 1}]},
               {"datetime": "2026-01-02T00:00:00Z", "data": [{"slug": "pepe", "value": None}]}]
    rows = si.parse_per_slug(payload, {"pepe": ["1000PEPE"]}, "social_volume_total")
    assert [(r["symbol"], r["d"], r["value"]) for r in rows] == [("1000PEPE", "2026-01-01", 12.0), ("1000PEPE", "2026-01-02", None)]


def test_plan_skips_when_fetched_today_and_rebuilds_map_only_when_needed():
    p = si.plan_santiment({"last_fetch": "2026-10-20T03:00:00+00:00", "universe": ["A"], "map": {"A": "a"}}, NOW)
    assert p["due"] is False, "同一天重启不能再烧 Santiment 的月配额"
    p = si.plan_santiment({"last_fetch": "2026-10-19T03:00:00+00:00", "universe": ["A", "B"], "map": {"A": "a"},
                           "map_built_at": "2026-10-18T00:00:00+00:00"}, NOW)
    assert p["due"] and p["need_map"] is False and p["missing_from_map"] == ["B"], "新名字等映射满 7 天再重建"
    p = si.plan_santiment({"universe": ["A"], "map": {}}, NOW)
    assert p["due"] and p["need_map"]


def test_groups_backfill_new_names_and_refetch_a_short_tail():
    last = {"A|m": "2026-09-19", "B|m": "2026-09-18", "C|m": "2026-03-01"}
    g = si.groups_for("m", ["A", "B", "C", "D"], last, date(2026, 10, 20))
    assert g[si.SAN_BACKFILL_FROM] == ["D"]
    assert g["2026-09-15"] == ["A", "B"], "尾部从最早的 last_d 往回 3 天"
    assert "C" not in sum(g.values(), []), "停更的序列不追"
    g = si.groups_for("m", ["A", "D"], last, date(2026, 10, 20), include_new=False)
    assert si.SAN_BACKFILL_FROM not in g, "有 slug 但没数据的名字不每天回补一年"
    assert si.batch_size(415) == 19 and si.batch_size(5) == si.MAX_BATCH and si.batch_size(10_000) == si.MIN_BATCH


def test_run_santiment_end_to_end_with_complexity_split(monkeypatch):
    monkeypatch.setattr(si, "SAN_SLEEP_S", 0)
    calls, upserts = [], {}

    async def gql(q, variables=None):
        calls.append(q)
        if "allProjects" in q:
            return {"allProjects": [{"slug": "aa", "ticker": "A", "marketcapUsd": 1.0},
                                    {"slug": "bb", "ticker": "B", "marketcapUsd": 2.0}]}
        if q.count('"') >= 6 and '"aa","bb"' in q:
            raise RuntimeError("Santiment errors: query complexity too high")
        slug = "aa" if '"aa"' in q else "bb"
        return {"getMetric": {"timeseriesDataPerSlugJson": [
            {"datetime": "2025-10-20T00:00:00Z", "data": [{"slug": slug, "value": 3}]}]}}

    async def upsert(table, rows, on_conflict):
        upserts.setdefault(table, []).extend(rows)
        return _R()

    plan = {"universe": ["A", "B", "Z"], "map": {}, "last": {}, "last_fetch": None}
    r = asyncio.run(si.run_santiment(plan, NOW, gql, upsert))
    assert r["status"] == "ok", r
    assert {x["symbol"] for x in upserts["santiment_slug_map"]} == {"A", "B", "Z"}
    sd = upserts["social_daily"]
    assert {(x["symbol"], x["metric"]) for x in sd} == {(s, m) for s in "AB" for m in si.SAN_METRICS}
    assert all(x["fetched_at"].startswith("2026-10-20") for x in sd), "带上 fetched_at,「今天取过」才判得出来"
    assert r["detail"]["calls"] == len(calls)


def test_sharpe_snapshot_and_history(monkeypatch):
    monkeypatch.setattr(si, "SHARPE_SLEEP_S", 0)
    tok = lambda tid, ms: {"id": tid, "symbol": tid.upper(), "mindsharePct": ms, "delta7d": None, "narrativeIds": ["ai"]}

    async def get(path, params=None):
        params = params or {}
        if path == "narratives/data":
            return {"data": {"narratives": [{"id": "ai"}]}}
        if params.get("historical"):
            return {"data": {"snapshots": [
                {"snapshot_at": "2026-10-18T00:00:00.000Z", "narrative_id": "ai", "mindshare_pct": 1.0, "token_count": 5},
                {"snapshot_at": "2026-10-19T00:00:00.000Z", "narrative_id": "ai", "mindshare_pct": 2.0, "token_count": 5}]}}
        toks = [tok("fet", 1.5)] if params.get("narrative") else [tok("bitcoin", 6.4), tok("fet", 1.5)]
        return {"data": {"tokens": toks, "total": 2}, "meta": {"as_of": "2026-10-20T00:05:12.958Z"}}

    up = {}

    async def upsert(table, rows, on_conflict):
        up.setdefault(table, []).extend(rows)
        return _R()

    r = asyncio.run(si.run_sharpe({"sharpe_last_snap": "2026-10-19", "sharpe_last_narr": "2026-10-18T00:00:00+00:00"},
                                  NOW, get, upsert))
    assert r["status"] == "ok", r
    keys = [(x["snap_d"], x["win"], x["token_id"]) for x in up["sharpe_mindshare_snap"]]
    assert len(keys) == len(set(keys)) == 4, "按叙事补的代币与主表重复 ⇒ 去重,否则 upsert 报错"
    assert [x["snapshot_at"][:10] for x in up["sharpe_narrative_mindshare"]] == ["2026-10-19"], "只要库里没有的"
    r = asyncio.run(si.run_sharpe({"sharpe_last_snap": "2026-10-20"}, NOW, get, upsert))
    assert r.get("skipped"), "今天的快照已在就不再取"


def test_errors_never_carry_the_keys(monkeypatch):
    from src.data.market import data_layer as dl
    monkeypatch.setenv("SANTIMENT_KEY", "SANTI_SENTINEL")
    monkeypatch.setenv("SHARPE_AI_KEY", "sk_live_SENTINEL")

    class _Resp:
        status_code = 429
        text = "rate limited"
        headers = {"x-ratelimit-remaining-month": "0", "x-quota-remaining": "7"}

        def json(self):
            return {}

    class _C:
        async def post(self, *a, **k):
            return _Resp()

        async def get(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(dl, "_get_misc_client", lambda: _C())
    for coro in (dl.get_santiment_gql("{ x }"), dl.get_sharpe_v1("mindshare/data")):
        try:
            asyncio.run(coro)
            raise AssertionError("429 必须报错")
        except RuntimeError as e:
            assert "SENTINEL" not in str(e)
    assert dl.QUOTA_SEEN["santiment"]["x-ratelimit-remaining-month"] == "0"
    assert dl.QUOTA_SEEN["sharpe"]["x-quota-remaining"] == "7"
    assert "SENTINEL" not in json.dumps(dl.QUOTA_SEEN)


def test_main_schedules_the_loop_and_migration_matches():
    src = (ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
    assert "_asyncio.create_task(_social_ingest_loop())" in src
    body = src.split("async def _social_ingest_loop", 1)[1].split("@app.on_event", 1)[0]
    assert body.count("_record_loop_attempt(") >= 2
    sql = (ROOT / "migrations" / "2026-10-20_social_daily.sql").read_text(encoding="utf-8")
    for t in ("santiment_slug_map", "social_daily", "sharpe_mindshare_snap", "sharpe_narrative_mindshare"):
        assert f"create table if not exists public.{t}" in sql
    assert "primary key (source, symbol, metric, d)" in sql and "primary key (snap_d, win, token_id)" in sql
    assert "revoke all on function public.social_ingest_plan() from public, anon, authenticated" in sql
