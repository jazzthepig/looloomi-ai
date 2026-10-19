"""T-130:头部账户持仓轮询 —— 名单筛选 / 记录字段 / 单地址失败隔离 / 节流 / 落盘 gzip+JSONL。"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import pathlib
import urllib.error

import pytest

from src.exec_host import whales


# ── 假数据 ────────────────────────────────────────────────────────────────────
def _row(addr: str, av: str, month_pnl: str) -> dict:
    return {
        "ethAddress": addr,
        "accountValue": av,
        "windowPerformances": [
            ["day", {"pnl": "0", "roi": "0", "vlm": "0"}],
            ["week", {"pnl": "0", "roi": "0", "vlm": "0"}],
            ["month", {"pnl": month_pnl, "roi": "0", "vlm": "0"}],
            ["allTime", {"pnl": "0", "roi": "0", "vlm": "0"}],
        ],
    }


@pytest.fixture
def tmp_paths(tmp_path):
    rec = tmp_path / "rec"
    addr = tmp_path / "whales_addresses.txt"
    return rec, addr


# ── select_addresses ──────────────────────────────────────────────────────────
def test_select_addresses_filters_by_av_and_pnl_topn():
    rows = [
        _row("0x" + "a" * 40, "2000000", "1000"),   # AV≥1M, pnl=1000
        _row("0x" + "b" * 40, "500000", "9999"),    # AV<1M,过滤
        _row("0x" + "c" * 40, "3000000", "500"),    # AV≥1M, pnl=500
        _row("0x" + "d" * 40, "1500000", "300"),    # AV≥1M, pnl=300
        _row("0x" + "e" * 40, "12000000", "200"),   # AV≥1M, pnl=200
        _row("0x" + "f" * 40, "9999", "8888"),      # AV<1M,过滤
    ]
    out = whales.select_addresses(rows, top_n=3, av_min_usd=1_000_000)
    # 按 month pnl 降序:a(1000), c(500), d(300) → 取 3
    assert out == ["0x" + "a" * 40, "0x" + "c" * 40, "0x" + "d" * 40]


def test_select_addresses_dedupes_case_insensitive():
    rows = [
        _row("0xABCDEF" + "0" * 34, "2000000", "1000"),
        _row("0xabcdef" + "0" * 34, "5000000", "2000"),  # 重复地址
    ]
    out = whales.select_addresses(rows, top_n=10, av_min_usd=1_000_000)
    assert len(out) == 1
    assert out[0] == "0xabcdef" + "0" * 34


def test_select_addresses_topn_cap():
    rows = [_row("0x" + f"{i:040x}", "2000000", str(1000 - i)) for i in range(50)]
    out = whales.select_addresses(rows, top_n=10, av_min_usd=1_000_000)
    assert len(out) == 10


def test_select_addresses_handles_malformed_pnl():
    rows = [
        _row("0x" + "1" * 40, "2000000", "not-a-number"),
        _row("0x" + "2" * 40, "2000000", "100"),
    ]
    out = whales.select_addresses(rows, top_n=10, av_min_usd=1_000_000)
    # malformed → 0,NaN 排序时置底,选 2(100) 排前
    assert out[0] == "0x" + "2" * 40


# ── load_addresses_from_file ──────────────────────────────────────────────────
def test_load_addresses_from_file_skips_comments_and_bad(tmp_paths):
    _, addr = tmp_paths
    addr.write_text(
        "# header\n"
        "0x" + "a" * 40 + "\n"
        "0x" + "B" * 40 + "\n"           # 大小写,正常化为小写
        "not-an-address\n"
        "0x" + "c" * 33 + "\n"          # 长度不够
        "0x" + "a" * 40 + "\n"          # 重复
        "\n"
    )
    out = whales.load_addresses_from_file(addr)
    assert out == ["0x" + "a" * 40, "0x" + "b" * 40]


def test_load_addresses_missing_file(tmp_paths):
    _, addr = tmp_paths
    assert whales.load_addresses_from_file(addr) == []


# ── parse_clearinghouse ───────────────────────────────────────────────────────
def test_parse_clearinghouse_basic_fields():
    addr = "0x" + "a" * 40
    raw = {
        "assetPositions": [
            {"position": {
                "coin": "BTC", "szi": "-2584.67833",
                "entryPx": "76204.7", "positionValue": "213613325.26",
                "unrealizedPnl": "-16648662.20",
                "leverage": {"type": "cross", "value": 5},
                "marginUsed": "42722665.05",
            }, "type": "oneWay"},
        ],
        "marginSummary": {"accountValue": "149186014.43"},
    }
    recs = whales.parse_clearinghouse(addr, raw, ts_ms=1_700_000_000_000)
    assert len(recs) == 1
    r = recs[0]
    assert r["address"] == addr
    assert r["coin"] == "BTC"
    assert r["szi"] == pytest.approx(-2584.67833, abs=1e-5)
    assert r["entryPx"] == pytest.approx(76204.7, abs=1e-4)
    assert r["positionValue"] == pytest.approx(213613325.26, abs=1e-2)
    assert r["unrealizedPnl"] == pytest.approx(-16648662.20, abs=1e-2)
    assert r["leverage"] == 5
    assert r["leverageType"] == "cross"
    assert r["marginUsed"] == pytest.approx(42722665.05, abs=1e-2)
    assert r["accountValue"] == pytest.approx(149186014.43, abs=1e-2)
    assert r["ts"] == 1_700_000_000_000


def test_parse_clearinghouse_empty_returns_empty():
    raw = {
        "assetPositions": [],
        "marginSummary": {"accountValue": "0.0"},
    }
    assert whales.parse_clearinghouse("0x" + "a" * 40, raw, ts_ms=0) == []


def test_parse_clearinghouse_skips_zero_szi():
    raw = {"assetPositions": [{"position": {"coin": "BTC", "szi": "0",
                                            "entryPx": "1", "positionValue": "0",
                                            "leverage": {"type": "cross", "value": 1},
                                            "marginUsed": "0"}, "type": "oneWay"}],
          "marginSummary": {"accountValue": "0.0"}}
    assert whales.parse_clearinghouse("0x" + "a" * 40, raw, ts_ms=0) == []


def test_parse_clearinghouse_invalid_input_returns_empty():
    assert whales.parse_clearinghouse("0x" + "a" * 40, None, ts_ms=0) == []
    assert whales.parse_clearinghouse("0x" + "a" * 40, "not-a-dict", ts_ms=0) == []
    assert whales.parse_clearinghouse("0x" + "a" * 40, {"assetPositions": "garbage"}, ts_ms=0) == []


# ── append_records / 落盘 gzip+JSONL ─────────────────────────────────────────
def test_append_records_creates_gz_jsonl(tmp_paths):
    rec, _ = tmp_paths
    day = "2026-10-19"
    n = whales.append_records(
        [{"ts": 1, "address": "0x" + "a" * 40, "coin": "BTC", "szi": 0.1,
          "entryPx": 100.0, "positionValue": 10.0, "unrealizedPnl": 0.0,
          "leverage": 1, "leverageType": "cross", "marginUsed": 10.0,
          "accountValue": 1000.0}],
        rec, day,
    )
    assert n == 1
    p = rec / f"{day}.jsonl.gz"
    assert p.exists()
    with gzip.open(p, "rt", encoding="utf-8") as f:
        lines = f.read().splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["coin"] == "BTC"
    assert obj["address"] == "0x" + "a" * 40


def test_append_records_appends(tmp_paths):
    rec, _ = tmp_paths
    day = "2026-10-19"
    whales.append_records([{"x": 1}], rec, day)
    whales.append_records([{"x": 2}, {"x": 3}], rec, day)
    with gzip.open(rec / f"{day}.jsonl.gz", "rt", encoding="utf-8") as f:
        objs = [json.loads(l) for l in f.read().splitlines() if l]
    assert objs == [{"x": 1}, {"x": 2}, {"x": 3}]


def test_append_records_empty_is_noop(tmp_paths):
    rec, _ = tmp_paths
    n = whales.append_records([], rec, "2026-10-19")
    assert n == 0
    assert not (rec / "2026-10-19.jsonl.gz").exists()


# ── fetch_one + 单地址失败隔离 ───────────────────────────────────────────────
class _FakeInfo:
    """可注入 info POST;失败用例用 raise 表达。"""

    def __init__(self, responses: dict[str, Exception | dict]):
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, payload: dict) -> dict:
        addr = payload["user"]
        self.calls.append((addr, payload))
        v = self.responses[addr]
        if isinstance(v, Exception):
            raise v
        return v


def _fetcher_with(info_callable: _FakeInfo, lb: dict | Exception | None = None) -> whales.Fetcher:
    f = whales.Fetcher(timeout=1.0)
    f.info = info_callable        # type: ignore[assignment]
    if lb is not None:
        f.leaderboard = lambda url="x": (lb if not isinstance(lb, Exception) else (lb.__class__(lb.args)))   # type: ignore[assignment]
    return f


def test_fetch_one_retries_then_succeeds():
    calls = {"n": 0}

    def fake(payload):
        calls["n"] += 1
        if calls["n"] < 2:
            raise TimeoutError("boom")
        return {"assetPositions": [], "marginSummary": {"accountValue": "0"}}

    f = whales.Fetcher(timeout=1.0)
    f.info = fake  # type: ignore[assignment]
    recs, err = whales.fetch_one("0x" + "a" * 40, f, retries=2)
    assert err is None
    assert recs == []
    assert calls["n"] == 2


def test_fetch_one_returns_error_after_max_retries():
    def fake(payload):
        raise TimeoutError("always")

    f = whales.Fetcher(timeout=1.0)
    f.info = fake  # type: ignore[assignment]
    recs, err = whales.fetch_one("0x" + "a" * 40, f, retries=2)
    assert recs is None
    assert err is not None
    assert "TimeoutError" in err


def test_fetch_one_returns_error_on_http_422():
    def fake(payload):
        raise urllib.error.HTTPError("https://api", 422, "Unprocessable Entity", {}, None)

    f = whales.Fetcher(timeout=1.0)
    f.info = fake  # type: ignore[assignment]
    recs, err = whales.fetch_one("0x" + "a" * 40, f, retries=0)
    assert recs is None
    assert err is not None
    assert "HTTPError" in err


# ── run_round: 综合 ───────────────────────────────────────────────────────────
def test_run_round_happy_path_records_and_dedupes(tmp_paths):
    rec, addr_file = tmp_paths
    a1, a2 = "0x" + "a" * 40, "0x" + "b" * 40
    # leaderboard 单次返回,几行
    lb = {
        "leaderboardRows": [
            _row(a1, "5000000", "1000"),
            _row(a2, "3000000", "500"),
            _row("0x" + "f" * 40, "100", "9999"),  # AV<1M
        ]
    }
    info_responses = {
        a1: {"assetPositions": [
            {"position": {"coin": "BTC", "szi": "-100", "entryPx": "70000",
                          "positionValue": "7000000", "unrealizedPnl": "-100",
                          "leverage": {"type": "cross", "value": 3},
                          "marginUsed": "2333333"}, "type": "oneWay"}],
             "marginSummary": {"accountValue": "9000000"}},
        a2: {"assetPositions": [
            {"position": {"coin": "ETH", "szi": "200", "entryPx": "3500",
                          "positionValue": "700000", "unrealizedPnl": "50",
                          "leverage": {"type": "isolated", "value": 2},
                          "marginUsed": "350000"}, "type": "oneWay"},
            {"position": {"coin": "SOL", "szi": "0", "entryPx": "100",
                          "positionValue": "0", "leverage": {"type": "cross", "value": 1},
                          "marginUsed": "0"}, "type": "oneWay"}],
             "marginSummary": {"accountValue": "4000000"}},
    }
    info = _FakeInfo(info_responses)
    f = whales.Fetcher(timeout=1.0)
    f.leaderboard = lambda url="x": lb          # type: ignore[assignment]
    f.info = info                                # type: ignore[assignment]

    now = dt.datetime(2026, 10, 19, 12, 0, tzinfo=dt.timezone.utc)
    stats = whales.run_round(now, f, rec_dir=rec, address_file=addr_file,
                             round_budget=10, sleep_between=0)
    assert stats["source"] == "leaderboard"
    assert stats["addresses"] == 2
    assert stats["queried"] == 2
    assert stats["ok"] == 2
    assert stats["empty"] == 0
    assert stats["failed"] == 0
    assert stats["records"] == 2        # SOL 被 szi=0 滤掉
    assert stats["day"] == "2026-10-19"

    with gzip.open(rec / "2026-10-19.jsonl.gz", "rt", encoding="utf-8") as fh:
        objs = [json.loads(l) for l in fh.read().splitlines() if l]
    coins = sorted(o["coin"] for o in objs)
    assert coins == ["BTC", "ETH"]
    btc = next(o for o in objs if o["coin"] == "BTC")
    assert btc["address"] == a1
    assert btc["leverage"] == 3
    assert btc["leverageType"] == "cross"
    eth = next(o for o in objs if o["coin"] == "ETH")
    assert eth["address"] == a2
    assert eth["leverage"] == 2
    assert eth["leverageType"] == "isolated"


def test_run_round_single_address_failure_does_not_break_round(tmp_paths):
    rec, addr_file = tmp_paths
    good, bad = "0x" + "a" * 40, "0x" + "b" * 40

    def fake_info(payload):
        if payload["user"] == bad:
            raise TimeoutError("conn refused")
        return {"assetPositions": [{"position": {"coin": "BTC", "szi": "1",
                                                "entryPx": "100", "positionValue": "100",
                                                "leverage": {"type": "cross", "value": 1},
                                                "marginUsed": "100"}, "type": "oneWay"}],
                "marginSummary": {"accountValue": "1000"}}

    lb = {"leaderboardRows": [_row(good, "2000000", "100"), _row(bad, "2000000", "50")]}
    f = whales.Fetcher(timeout=1.0)
    f.leaderboard = lambda url="x": lb          # type: ignore[assignment]
    f.info = fake_info                          # type: ignore[assignment]

    stats = whales.run_round(dt.datetime(2026, 10, 19, 0, 0, tzinfo=dt.timezone.utc),
                             f, rec_dir=rec, address_file=addr_file, round_budget=10, sleep_between=0)
    assert stats["ok"] == 1
    assert stats["failed"] == 1
    assert stats["records"] == 1
    assert any("0xbbb" in e for e in stats["errors"])


def test_run_round_throttle_caps_round_budget(tmp_paths):
    rec, addr_file = tmp_paths
    addrs = ["0x" + f"{i:040x}" for i in range(10)]
    lb = {"leaderboardRows": [_row(a, "2000000", str(1000 - i)) for i, a in enumerate(addrs)]}
    info_responses = {a: {"assetPositions": [], "marginSummary": {"accountValue": "1000"}} for a in addrs}
    info = _FakeInfo(info_responses)
    f = whales.Fetcher(timeout=1.0)
    f.leaderboard = lambda url="x": lb          # type: ignore[assignment]
    f.info = info                                # type: ignore[assignment]

    stats = whales.run_round(dt.datetime(2026, 10, 19, 0, 0, tzinfo=dt.timezone.utc),
                             f, rec_dir=rec, address_file=addr_file, round_budget=3, sleep_between=0)
    assert stats["addresses"] == 10
    assert stats["queried"] == 3          # cap
    assert len(info.calls) == 3


def test_run_round_falls_back_to_file_when_leaderboard_fails(tmp_paths):
    rec, addr_file = tmp_paths
    addr_file.write_text("0x" + "a" * 40 + "\n0x" + "b" * 40 + "\n")
    a1, a2 = "0x" + "a" * 40, "0x" + "b" * 40
    info_responses = {a1: {"assetPositions": [], "marginSummary": {"accountValue": "0"}},
                      a2: {"assetPositions": [], "marginSummary": {"accountValue": "0"}}}
    info = _FakeInfo(info_responses)
    f = whales.Fetcher(timeout=1.0)
    f.leaderboard = lambda url="x": (_ for _ in ()).throw(TimeoutError("lb down"))  # type: ignore[assignment]
    f.info = info                                                                # type: ignore[assignment]

    stats = whales.run_round(dt.datetime(2026, 10, 19, 0, 0, tzinfo=dt.timezone.utc),
                             f, rec_dir=rec, address_file=addr_file, round_budget=10, sleep_between=0)
    assert stats["source"] == "file"
    assert stats["addresses"] == 2
    assert stats["ok"] == 2


def test_run_round_addresses_cached_within_day(tmp_paths):
    rec, addr_file = tmp_paths
    a = "0x" + "a" * 40
    lb = {"leaderboardRows": [_row(a, "2000000", "100")]}
    call_log = {"lb": 0, "info": 0}

    def fake_lb(url="x"):
        call_log["lb"] += 1
        return lb

    def fake_info(payload):
        call_log["info"] += 1
        return {"assetPositions": [], "marginSummary": {"accountValue": "0"}}

    f = whales.Fetcher(timeout=1.0)
    f.leaderboard = fake_lb                    # type: ignore[assignment]
    f.info = fake_info                          # type: ignore[assignment]

    cache: dict = {}
    now1 = dt.datetime(2026, 10, 19, 0, 0, tzinfo=dt.timezone.utc)
    whales.run_round(now1, f, cache=cache, rec_dir=rec, address_file=addr_file, sleep_between=0)
    now2 = dt.datetime(2026, 10, 19, 0, 15, tzinfo=dt.timezone.utc)
    whales.run_round(now2, f, cache=cache, rec_dir=rec, address_file=addr_file, sleep_between=0)
    assert call_log["lb"] == 1              # 一天内只取一次
    assert call_log["info"] == 2            # 每轮都拉


def test_run_round_recovers_when_leaderboard_returns_empty(tmp_paths):
    rec, addr_file = tmp_paths
    addr_file.write_text("0x" + "a" * 40 + "\n")
    a = "0x" + "a" * 40
    info = _FakeInfo({a: {"assetPositions": [], "marginSummary": {"accountValue": "0"}}})
    f = whales.Fetcher(timeout=1.0)
    f.leaderboard = lambda url="x": {"leaderboardRows": []}     # type: ignore[assignment]
    f.info = info                                                # type: ignore[assignment]
    stats = whales.run_round(dt.datetime(2026, 10, 19, 0, 0, tzinfo=dt.timezone.utc),
                             f, rec_dir=rec, address_file=addr_file, sleep_between=0)
    assert stats["source"] == "file"
    assert stats["ok"] == 1


