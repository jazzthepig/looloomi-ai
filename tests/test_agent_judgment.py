"""agent 判断臂(S-725,11-05):档案只来自已落表的字段、概率归一不截断、理由过中英文合规、模型不通当天空着、入账作者 ai:<模型>。"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.execution import agent_judgment as aj  # noqa: E402

DEC = {"d": "2026-11-05", "rule_exposure": 1.0, "probs": {"down": 0.2, "flat": 0.5, "up": 0.3}, "bucket": "up|RISK_ON", "n_bucket": 900,
       "inputs": {"btc_close": 80000.0, "mom_200": 0.1, "probs_knn": {"down": 0.25, "flat": 0.45, "up": 0.3}, "probs_window": None,
                  "window_matches": [{"d": "2023-01-10", "dist": 1.2, "fwd_30d": 0.2}], "events_7d": {"listing": 3}}}


def test_dossier_has_no_rule_exposure_and_no_nulls():
    doc = aj.dossier(DEC, [{"title": "x" * 300, "published_at": "2026-11-05T01:00:00+00:00"}])
    flat = json.dumps(doc)
    assert "rule_exposure" not in flat and "probs_window" not in doc["state"]
    assert doc["state"]["btc_close"] == 80000.0 and doc["base_rate_same_state"]["n_days"] == 900
    assert len(doc["news_48h"][0]["title"]) == 160
    assert aj.dossier_hash(doc) == aj.dossier_hash(json.loads(flat))


def test_parse_reply_normalises_without_clipping_and_rejects_garbage():
    got = aj.parse_reply({"down": 0.0, "flat": 0.62, "up": 0.40, "rationale": "Breadth is firm.", "drivers": ["breadth_above_ma50"],
                          "change_mind": "A drop in breadth."})
    assert got["probs"] == {"down": 0.0, "flat": round(0.62 / 1.02, 4), "up": round(0.40 / 1.02, 4)}
    assert got["rationale"] == "Breadth is firm." and got["drivers"] == ["breadth_above_ma50"]
    assert aj.parse_reply({"down": 0.5, "flat": 0.5, "up": 0.5}) is None          # 和 1.5:没按三档答
    assert aj.parse_reply({"down": "x", "flat": 0.5, "up": 0.5}) is None
    assert aj.parse_reply({"down": -0.1, "flat": 0.6, "up": 0.5}) is None
    assert aj.parse_reply(None) is None


def test_compliance_filters_english_and_chinese_but_keeps_probs():
    assert aj.comply("Funding is crowded; I would buy the dip.") is None
    assert aj.comply("资金费拥挤,建议逢低加仓。") is None
    assert aj.comply("资金费拥挤,上方空头强平价集中。") == "资金费拥挤,上方空头强平价集中。"
    got = aj.parse_reply({"down": 0.3, "flat": 0.4, "up": 0.3, "rationale": "sell now"})
    assert got["rationale"] is None and got["probs"]["flat"] == 0.4


def test_author_name_is_ledger_safe():
    assert aj.author_for("MiniMax-M3") == "ai:MiniMax-M3" and aj.author_for("org/model v2") == "ai:org-model-v2"


def _patch(monkeypatch, reply, have=None, dec=(DEC,), configured=True):
    import src.api.store as store
    import src.data.evaluation.scenario_ledger as sl
    import src.data.narrative.llm_narrator as llm
    import src.data.style.header as hdr
    up, subs = {}, []

    async def read_all(t, params):
        if t == aj.TABLE:
            return have or []
        if t == "exposure_decision_daily":
            return list(dec)
        if t == "feed_items":
            return [{"title": "BTC holds", "published_at": "2026-11-05T01:00:00+00:00", "score": 3}]
        raise AssertionError(t)

    async def ups(t, rows, on_conflict):
        up[t] = rows
        return True

    async def chat(messages, temperature=0.4):
        assert temperature == aj.TEMPERATURE and "DOSSIER" in messages[1]["content"]
        return reply

    async def submit(entries, author, now=None):
        subs.append((author, entries))
        return {"ok": True, "ids": [e["id"] for e in entries]}
    monkeypatch.setattr(hdr, "_read_all", read_all)
    monkeypatch.setattr(store, "supabase_upsert_table", ups)
    monkeypatch.setattr(llm, "_chat", chat)
    monkeypatch.setattr(llm, "configured", lambda: configured)
    monkeypatch.setattr(llm, "_MODEL", "MiniMax-M3")
    monkeypatch.setattr(sl, "submit", submit)
    return up, subs


def test_run_once_writes_three_entries_for_yesterday(monkeypatch):
    up, subs = _patch(monkeypatch, '```json\n{"down":0.25,"flat":0.45,"up":0.30,"rationale":"Base rate holds.","drivers":["probs_uncond"],"change_mind":"x"}\n```')
    r = asyncio.run(aj.run_once(dt.datetime(2026, 11, 6, 3, 0, tzinfo=dt.timezone.utc)))
    assert r["ok"] and r["d"] == "2026-11-05" and r["author"] == "ai:MiniMax-M3" and r["scenarios"] == 3
    author, entries = subs[0]
    assert author == "ai:MiniMax-M3" and [e["id"] for e in entries] == ["A-2026-11-05-down", "A-2026-11-05-flat", "A-2026-11-05-up"]
    assert entries[0]["hi"] == 72000.0 and entries[2]["lo"] == 88000.0 and entries[1]["prob"] == 0.45
    row = up[aj.TABLE][0]
    assert row["probs"] == {"down": 0.25, "flat": 0.45, "up": 0.3} and row["scenario_ids"] == ["A-2026-11-05-down", "A-2026-11-05-flat", "A-2026-11-05-up"]


def test_run_once_skips_when_model_silent_or_decision_missing(monkeypatch):
    _patch(monkeypatch, None)
    r = asyncio.run(aj.run_once(dt.datetime(2026, 11, 6, 3, 0, tzinfo=dt.timezone.utc)))
    assert r["status"] == "refused" and r["refused"] and not r["ok"] and "2026-11-05" in r["why"], "模型不通要留原因,不能记成 ok"
    _patch(monkeypatch, "{}", dec=())
    assert "还没落表" in asyncio.run(aj.run_once(dt.datetime(2026, 11, 6, 3, 0, tzinfo=dt.timezone.utc)))["why"]
    _patch(monkeypatch, "{}", have=[{"d": "2026-11-05"}])
    assert "已写" in asyncio.run(aj.run_once(dt.datetime(2026, 11, 6, 3, 0, tzinfo=dt.timezone.utc)))["why"]
    _patch(monkeypatch, "{}", configured=False)
    r = asyncio.run(aj.run_once(dt.datetime(2026, 11, 6, 3, 0, tzinfo=dt.timezone.utc)))
    assert "未配" in r["why"] and r["status"] == "refused"
    _patch(monkeypatch, '{"down": 0.5}')
    assert asyncio.run(aj.run_once(dt.datetime(2026, 11, 6, 3, 0, tzinfo=dt.timezone.utc)))["status"] == "refused"


def test_wiring():
    assert "_agent_judgment_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    assert '"/internal/agent-judgment"' in (ROOT / "src/api/routers/admin.py").read_text(encoding="utf-8")
    mig = (ROOT / "migrations/2026-11-05_agent_judgment_daily.sql").read_text(encoding="utf-8")
    for col in aj.WRITES_COLUMNS[aj.TABLE]:
        assert col in mig, col


def test_llm_base_url_is_normalised_for_minimax_only():
    """11-05:第一次留下的原因是 HTTP 302(Railway 里是 http://api.minimax.io,没 https、没 /v1)。只修 MiniMax 公网域名。"""
    from src.data.narrative.llm_narrator import normalize_base as n
    assert n("http://api.minimax.io") == "https://api.minimax.io/v1"
    assert n(" https://api.minimax.io/v1/ \n") == "https://api.minimax.io/v1"
    assert n("api.minimaxi.chat") == "https://api.minimaxi.chat/v1"
    assert n("http://192.168.1.5:1234/v1") == "http://192.168.1.5:1234/v1", "局域网 LM Studio 不动"
    assert n("https://api.openai.com/v1") == "https://api.openai.com/v1" and n("") == ""
