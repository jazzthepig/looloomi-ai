"""T-129 录写器测试:假消息 + 假磁盘 + 假时钟,确认每条都打到 acceptance:

- 10 秒一档 l2Book(节流正确)
- gz 行可读回 + 行数对
- UTC 日滚动(同日不动,跨日切到下一天目录)
- 磁盘 < 5 GB 停写并报
- 重连退避上限 30 秒
- 不读私钥、不写 Supabase
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import pathlib
import sys
import time

import pytest

from src.exec_host import recorder as R


# ── fakes ────────────────────────────────────────────────────────────────────
class _FakeWs:
    def __init__(self):
        self.sent: list[dict] = []

    def send(self, payload):
        self.sent.append(payload)

    def recv(self):
        raise NotImplementedError

    def close(self):
        pass


class _FakePoster:
    def __init__(self, raw):
        self._raw = raw
        self.calls = 0

    def post(self, payload):
        self.calls += 1
        return self._raw


class _FakeHost:
    """注入 _check_disk_free:能切 'disk_full' / 'disk_ok' 来测护栏。"""

    def __init__(self, free_gb: float = 100.0):
        self._free = free_gb

    def set(self, gb: float) -> None:
        self._free = gb

    def free_gb(self, _path):
        return self._free


# ── helpers ──────────────────────────────────────────────────────────────────

#: 合并方(10-19):除磁盘护栏的两项外,测试不依赖跑测试那台机器的剩余磁盘(沙箱只剩 4 GB 时 4 项全红)。
_ROOMY = {"disk_min_gb": 0.0}

def _l2(coin: str, t: int, n: int = 5, px_base: float = 100.0):
    bids = [[px_base - i, 1.0 + i, 1] for i in range(n)]
    asks = [[px_base + i, 1.0 + i, 1] for i in range(n)]
    return {"channel": "l2Book", "data": {"coin": coin, "time": t, "levels": [bids, asks]}}


def _trades(coin: str, t: int, n: int = 3, px_base: float = 100.0):
    arr = [{"coin": coin, "side": "buy" if i % 2 else "sell",
            "px": str(px_base + i * 0.1), "sz": "0.5", "time": t + i, "tid": t * 10 + i}
           for i in range(n)]
    return {"channel": "trades", "data": arr}


def _read_gz_lines(path: pathlib.Path):
    out = []
    with gzip.open(path, "rt") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


# ── 10 秒一档 ────────────────────────────────────────────────────────────────
def test_l2_throttles_to_one_per_10s_per_coin(tmp_path):
    ws, poster = _FakeWs(), _FakePoster([])
    rec = R.Recorder(
        **_ROOMY,
        base_dir=tmp_path / "rec",
        coins=["BTC"],
        ws=ws, poster=poster,
        clock=lambda: 1_000_000.0,
        wallclock=lambda: dt.datetime(2026, 10, 19, 12, 0, tzinfo=dt.timezone.utc),
    )
    day = "2026-10-19"
    # 同一秒连发 5 张 l2Book —— 应该只保留 1 张
    msgs = [_l2("BTC", t=1_700_000_000_000 + i * 100) for i in range(5)]
    for m in msgs:
        rec.handle(m)
    # 10 秒后又一张 —— 第二次保留
    rec.handle(_l2("BTC", t=1_700_000_010_000))
    rec.close()
    lines = _read_gz_lines(tmp_path / "rec" / day / "BTC.l2.jsonl.gz")
    assert len(lines) == 2
    assert [int(x["time_ms"]) for x in lines] == [1_700_000_000_000, 1_700_000_010_000]


def test_l2_throttle_is_per_coin(tmp_path):
    rec = R.Recorder(
        **_ROOMY,
        base_dir=tmp_path / "rec",
        coins=["BTC", "ETH"],
        ws=_FakeWs(), poster=_FakePoster([]),
        clock=lambda: 0.0,
        wallclock=lambda: dt.datetime(2026, 10, 19, 12, 0, tzinfo=dt.timezone.utc),
    )
    ts = 1_700_000_000_000
    for c in ("BTC", "ETH"):
        rec.handle(_l2(c, t=ts))   # 两个币同毫秒 —— 各自保留
        rec.handle(_l2(c, t=ts))   # 同币 0ms 后 —— 节流掉
    rec.close()
    day = "2026-10-19"
    assert len(_read_gz_lines(tmp_path / "rec" / day / "BTC.l2.jsonl.gz")) == 1
    assert len(_read_gz_lines(tmp_path / "rec" / day / "ETH.l2.jsonl.gz")) == 1


# ── trades 全留 + 可读回 ────────────────────────────────────────────────────
def test_trades_all_persisted_and_readable(tmp_path):
    rec = R.Recorder(
        **_ROOMY,
        base_dir=tmp_path / "rec",
        coins=["SOL"],
        ws=_FakeWs(), poster=_FakePoster([]),
        clock=lambda: 0.0,
        wallclock=lambda: dt.datetime(2026, 10, 19, 12, 0, tzinfo=dt.timezone.utc),
    )
    # 5 笔成交,同批次到达 —— 全部落盘
    rec.handle(_trades("SOL", t=1_700_000_000_000, n=5, px_base=200.0))
    rec.handle(_trades("SOL", t=1_700_000_000_500, n=3, px_base=200.5))
    rec.close()
    day = "2026-10-19"
    lines = _read_gz_lines(tmp_path / "rec" / day / "SOL.trades.jsonl.gz")
    assert len(lines) == 8
    assert all(x["kind"] == "trade" for x in lines)
    assert all(x["coin"] == "SOL" for x in lines)
    assert lines[0]["side"] in ("buy", "sell")
    # 行可解析 + 每行包含 ts_local_ms(供回放时序排序)
    assert all("ts_local_ms" in x for x in lines)


# ── UTC 日滚动 ──────────────────────────────────────────────────────────────
def test_day_rollover_writes_new_directory(tmp_path):
    """墙钟跨 UTC 00:00 后,下一条消息落到第二天目录;当天目录不再写。"""
    fake_wall = {"now": dt.datetime(2026, 10, 19, 23, 59, 50, tzinfo=dt.timezone.utc)}

    def _wall():
        return fake_wall["now"]

    rec = R.Recorder(
        **_ROOMY,
        base_dir=tmp_path / "rec",
        coins=["BTC"],
        ws=_FakeWs(), poster=_FakePoster([]),
        clock=lambda: 0.0,
        wallclock=_wall,
    )
    rec.handle(_l2("BTC", t=1_700_000_000_000))
    # 跨日
    fake_wall["now"] = dt.datetime(2026, 10, 20, 0, 0, 5, tzinfo=dt.timezone.utc)
    rec.handle(_l2("BTC", t=1_700_000_100_000))
    # 同日再写一张 —— 还是落 10-20
    rec.handle(_l2("BTC", t=1_700_000_200_000))
    rec.close()

    d19 = tmp_path / "rec" / "2026-10-19" / "BTC.l2.jsonl.gz"
    d20 = tmp_path / "rec" / "2026-10-20" / "BTC.l2.jsonl.gz"
    assert d19.exists()
    assert d20.exists()
    assert len(_read_gz_lines(d19)) == 1
    assert len(_read_gz_lines(d20)) == 2


def test_writer_rollover_does_not_drop_lines(tmp_path):
    """GzJsonlWriter.rollover 切换日期后旧句柄 close,新句柄 append。"""
    w = R.GzJsonlWriter(tmp_path / "rec", day="2026-10-19", kind="trades")
    w.write({"a": 1})
    w.rollover("2026-10-20")
    assert w.day == "2026-10-20"
    w.write({"b": 2})
    w.flush(); w.close()
    lines19 = _read_gz_lines(tmp_path / "rec" / "2026-10-19" / "trades.jsonl.gz")
    lines20 = _read_gz_lines(tmp_path / "rec" / "2026-10-20" / "trades.jsonl.gz")
    assert lines19 == [{"a": 1}]
    assert lines20 == [{"b": 2}]


# ── 磁盘护栏 ────────────────────────────────────────────────────────────────
def test_disk_below_min_halts_writes(monkeypatch, tmp_path, caplog):
    host = _FakeHost(free_gb=100.0)
    rec = R.Recorder(
                base_dir=tmp_path / "rec",
        coins=["BTC"],
        ws=_FakeWs(), poster=_FakePoster([]),
        clock=lambda: 0.0,
        wallclock=lambda: dt.datetime(2026, 10, 19, 12, 0, tzinfo=dt.timezone.utc),
        host=host,
    )
    caplog.set_level("ERROR", logger="exec_host.recorder")
    rec.handle(_l2("BTC", t=1))     # ok
    host.set(2.0)                    # < 5 GB
    rec.handle(_l2("BTC", t=2_000))  # 失败 → 标记 halted
    rec.handle(_l2("BTC", t=20_000)) # halted 后 no-op
    assert rec.disk_halted is True
    msgs = [r for r in caplog.records if "disk free" in r.message.lower()]
    assert msgs, "expected a disk-low error log"
    rec.close()
    day = "2026-10-19"
    lines = _read_gz_lines(tmp_path / "rec" / day / "BTC.l2.jsonl.gz")
    assert len(lines) == 1
    assert lines[0]["time_ms"] == 1


def test_disk_halted_skips_both_kinds(tmp_path):
    host = _FakeHost(free_gb=100.0)
    rec = R.Recorder(
                base_dir=tmp_path / "rec",
        coins=["BTC"],
        ws=_FakeWs(), poster=_FakePoster([]),
        clock=lambda: 0.0,
        wallclock=lambda: dt.datetime(2026, 10, 19, 12, 0, tzinfo=dt.timezone.utc),
        host=host,
    )
    host.set(2.0)
    rec.handle(_trades("BTC", t=1, n=2))
    rec.handle(_l2("BTC", t=2))
    assert rec.disk_halted is True
    rec.close()
    day = "2026-10-19"
    assert not (tmp_path / "rec" / day / "BTC.trades.jsonl.gz").exists()
    assert not (tmp_path / "rec" / day / "BTC.l2.jsonl.gz").exists()


# ── 重连退避 ────────────────────────────────────────────────────────────────
def test_backoff_caps_and_resets():
    b = R.Backoff(start=1.0, cap=30.0)
    delays = [b.next_delay() for _ in range(8)]
    assert delays[0] == 1.0
    assert delays[-1] == 30.0
    assert all(d <= 30.0 for d in delays)
    # 收到一条后清零
    b.note_ok()
    assert b.next_delay() == 1.0


def test_l2_throttle_is_independent_across_recorders():
    # 双 Recorder 各自节流,不该互相污染
    a = R.Recorder(base_dir=pathlib.Path("/tmp/x"), coins=[], ws=_FakeWs(), poster=_FakePoster([]))
    b = R.Recorder(base_dir=pathlib.Path("/tmp/y"), coins=[], ws=_FakeWs(), poster=_FakePoster([]))
    a.last_keep_ts["BTC"] = 1
    assert "BTC" not in b.last_keep_ts


# ── 名单:env + metaAndAssetCtxs top-30 ───────────────────────────────────────
def test_coin_roster_defaults_then_topn():
    from src.exec_host.recorder import coin_roster, DEFAULT_COINS
    meta = [("SOL", 9e9), ("AVAX", 5e9), ("BTC", 1e10), ("DOGE", 7e9), ("HYPE", 8e9)]
    out = coin_roster(DEFAULT_COINS, meta, top_n=30)
    # 默认顺序在前,重复不写
    assert out[0] == "BTC"
    assert out[1] == "ETH"
    assert out[2] == "SOL"
    assert out[3] == "HYPE"
    # env 已含 BTC,SOL,HYPE;新增的应该只剩 BTC(meta 排序最高)/HYPE 已被收录
    assert "AVAX" in out
    assert "DOGE" in out


def test_parse_meta_and_asset_ctxs_top_volume():
    raw = [
        {"universe": [{"name": "BTC"}, {"name": "ETH"}, {"name": "SOL"}]},
        [{"dayNtlVlm": "1.0e9"}, {"dayNtlVlm": "3.0e9"}, {"dayNtlVlm": "5.0e9"}],
    ]
    out = R.parse_meta_and_asset_ctxs(raw)
    assert out == [("SOL", 5e9), ("ETH", 3e9), ("BTC", 1e9)]


def test_refresh_roster_subscribes_unsub(tmp_path):
    ws = _FakeWs()
    # HL metaAndAssetCtxs 实际结构:[universe_dict, ctxs_list]
    raw = [
        {"universe": [{"name": "BTC"}, {"name": "ETH"}, {"name": "SOL"}, {"name": "AVAX"}]},
        [{"dayNtlVlm": "1e10"}] * 4,
    ]
    rec = R.Recorder(
        **_ROOMY,
        base_dir=tmp_path / "rec",
        coins=["BTC", "ETH"],
        ws=ws, poster=_FakePoster(raw),
        clock=lambda: 0.0,
        wallclock=lambda: dt.datetime(2026, 10, 19, 12, 0, tzinfo=dt.timezone.utc),
    )
    rec.subscribe_all()
    sent_before = len(ws.sent)
    rec.refresh_roster()
    sent_after = ws.sent[sent_before:]
    added = [m for m in sent_after if m["method"] == "subscribe"]
    removed = [m for m in sent_after if m["method"] == "unsubscribe"]
    assert any(m["subscription"]["coin"] == "SOL" for m in added), added
    assert all(m["subscription"]["coin"] != "BTC" for m in added)
    # BTC ETH 都在;AVAX 进 30 名内所以也会订阅
    assert any(m["subscription"]["coin"] == "AVAX" for m in added)
    assert removed == []


def test_refresh_roster_keeps_only_default_then_trims(tmp_path):
    ws = _FakeWs()
    raw = [
        {"universe": [{"name": "AVAX"}, {"name": "DOGE"}]},
        [{"dayNtlVlm": "1e10"}, {"dayNtlVlm": "5e9"}],
    ]
    rec = R.Recorder(
        **_ROOMY,
        base_dir=tmp_path / "rec",
        coins=["BTC", "ETH", "SOL", "HYPE"],
        ws=ws, poster=_FakePoster(raw),
        clock=lambda: 0.0,
        wallclock=lambda: dt.datetime(2026, 10, 19, 12, 0, tzinfo=dt.timezone.utc),
    )
    rec.refresh_roster()
    # 默认 4 个全在;AVAX / DOGE 进 30 名
    assert "BTC" in rec.coins and "ETH" in rec.coins
    assert "AVAX" in rec.coins


# ── 解析:l2Book 与 trades ───────────────────────────────────────────────────
def test_parse_l2_caps_at_20_levels_and_keeps_20_bids_20_asks():
    n = 30
    msg = _l2("BTC", t=1, n=n)
    parsed = R.parse_l2(msg)
    assert parsed is not None
    assert len(parsed["bids"]) == R.L2_DEPTH
    assert len(parsed["asks"]) == R.L2_DEPTH


def test_parse_l2_drops_non_l2_messages():
    assert R.parse_l2({"channel": "trades", "data": []}) is None
    assert R.parse_l2({"channel": "l2Book"}) is None
    assert R.parse_l2({}) is None


def test_parse_trades_flattens_one_message_multiple_rows():
    msg = _trades("BTC", t=1, n=4)
    out = R.parse_trade(msg)
    assert out is not None
    assert len(out["trades"]) == 4
    assert out["trades"][0]["coin"] == "BTC"
    assert out["trades"][0]["side"] in ("buy", "sell")


def test_handle_ignores_unknown_channels(tmp_path):
    rec = R.Recorder(
        **_ROOMY,
        base_dir=tmp_path / "rec",
        coins=["BTC"],
        ws=_FakeWs(), poster=_FakePoster([]),
        clock=lambda: 0.0,
        wallclock=lambda: dt.datetime(2026, 10, 19, 12, 0, tzinfo=dt.timezone.utc),
    )
    rec.handle({"channel": "subscriptionResponse", "data": {"method": "subscribe"}})
    rec.handle({"channel": "pong"})
    rec.handle({"channel": "ack"})
    day = "2026-10-19"
    assert not (tmp_path / "rec" / day / "BTC.l2.jsonl.gz").exists()


# ── 安全:不读 env var 名为 KEY, 也不引 supabase 路径 ─────────────────────────
def test_recorder_does_not_import_supabase_safeguard():
    """这条不会主动查 supabase(也不写 supabase);只确保 recorder 模块里没有 supabase 字样。

    防止以后有人顺手调用 supabase 接 Supabase(TRADE_PATH §3d)。"""
    src = pathlib.Path(R.__file__).read_text(encoding="utf-8")
    assert "supabase" not in src.lower(), "recorder must not talk to supabase"
    # 任何 `os.environ[...secret...]` 都不应该出现在 recorder
    forbidden = ("SECRET", "PRIVATE_KEY", "API_KEY", "WALLET_KEY", "EXECUTOR_TOKEN")
    for word in forbidden:
        assert word not in src, f"recorder must not read env var containing {word!r}"


def test_recorder_module_only_uses_stdlib_when_test_path_isolated():
    """record 的 import 面只在生产入口里需要 `websocket` / `urllib` —— 模块顶层不应引第三方。"""
    mod = sys.modules["src.exec_host.recorder"]
    src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
    # 模块级 import 不应出现 websocket / urllib(都在函数里)
    top_import_lines = [ln for ln in src.splitlines()
                        if ln.startswith("import ") or ln.startswith("from ")]
    top_imports = "\n".join(top_import_lines)
    assert "websocket" not in top_imports, top_imports
    assert "urllib" not in top_imports, top_imports


# ── 安全: handle() 拒收非 dict 消息(str / None) ──────────────────────────────
def test_handle_tolerates_non_dict_messages(tmp_path):
    rec = R.Recorder(
        **_ROOMY,
        base_dir=tmp_path / "rec",
        coins=["BTC"],
        ws=_FakeWs(), poster=_FakePoster([]),
        clock=lambda: 0.0,
        wallclock=lambda: dt.datetime(2026, 10, 19, 12, 0, tzinfo=dt.timezone.utc),
    )
    rec.handle({})
    rec.handle({"channel": "nonsense"})
    assert not (tmp_path / "rec" / "2026-10-19" / "BTC.l2.jsonl.gz").exists()


def test_the_production_entry_point_is_wired():
    """合并方(10-19)补:原版 run() 里有一行 `self._last_msg = txt`(run 不是方法,没有 self)——
    每条消息都 NameError、被当成断线、无限重连,一行都不会写;而且没有 __main__,systemd 拉起后进程直接退出。"""
    import ast
    import pathlib
    src = (pathlib.Path(R.__file__)).read_text(encoding="utf-8")
    run_fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "run")
    assert "self" not in {n.id for n in ast.walk(run_fn) if isinstance(n, ast.Name)}
    body = ast.unparse(run_fn)
    assert body.count("refresh_roster()") >= 2, "启动时就补名单,不等 24 小时"
    assert "'method': 'ping'" in body or '"method": "ping"' in body, "定时 ping,保活"
    assert 'if __name__ == "__main__":' in src
