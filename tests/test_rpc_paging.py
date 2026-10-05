"""S-487:返回集合的库函数要分页读全 —— PostgREST 对 RPC 也只给前 1,000 行,而且不报错。

`core_alpha_daily('2023-01-01')` 有 4,119 行(三臂 × 1,373 天),按 α 排序;
`supabase_rpc` 只拿到前 1,000 行 = 只有 α=0(等权),① 那一臂整条不见。lane B 在 T-047 里发现。
"""
import asyncio
import pathlib
import re

import src.api.store as store


class _Resp:
    def __init__(self, rows, status=200):
        self._rows, self.status_code, self.text = rows, status, ""

    def json(self):
        return self._rows


def _patch(monkeypatch, pages):
    calls = []

    async def fake(method, url, **kw):
        calls.append(kw.get("params"))
        return pages[len(calls) - 1]
    monkeypatch.setattr(store, "_SB_URL", "https://x.supabase.co")
    monkeypatch.setattr(store, "_SB_KEY", "k")
    monkeypatch.setattr(store, "_supabase_request_with_retry", fake)
    return calls


def test_reads_every_page_and_passes_filters(monkeypatch):
    rows = [{"i": i} for i in range(2119)]
    calls = _patch(monkeypatch, [_Resp(rows[:1000]), _Resp(rows[1000:2000]), _Resp(rows[2000:])])
    out = asyncio.run(store.supabase_rpc_all("core_alpha_daily", {"p_start": "2023-01-01"}, {"alpha": "eq.1"}))
    assert out == rows
    assert [c["offset"] for c in calls] == ["0", "1000", "2000"]
    assert all(c["alpha"] == "eq.1" and c["limit"] == "1000" for c in calls)


def test_a_failed_page_is_none_not_a_partial_list(monkeypatch):
    _patch(monkeypatch, [_Resp([{"i": i} for i in range(1000)]), _Resp({"message": "timeout"}, 500)])
    assert asyncio.run(store.supabase_rpc_all("core_alpha_daily", {"p_start": "2023-01-01"})) is None


def test_no_unpaged_call_to_core_alpha_daily():
    src = pathlib.Path(__file__).resolve().parents[1] / "src"
    bad = [str(p) for p in src.rglob("*.py")
           if re.search(r"supabase_rpc\(\s*[\"']core_alpha_daily", p.read_text(encoding="utf-8"))]
    assert not bad, f"core_alpha_daily 要用 supabase_rpc_all 读(4,119 行 > 1,000):{bad}"
