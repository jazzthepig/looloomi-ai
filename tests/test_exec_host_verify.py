"""主机复核(S-666 / S-667):主机不信上游。

守的东西:规则 V 与预注册一字不差(阈值是常量,改了这里就红);V7 只栽 V7 时 V′ 仍算过;签名覆盖判断的全部语义、
被改一个字就不认;没有有效签名的判断开不了 J 票、放大不了 R-v2 的风险;report 不拦 R-v2、enforce 按 V′ 拦;
签名的有效期与 Railway 的 governing_call 同一规则;Railway 收签名时只核内容一致与时间;主机守每票风险 ≤ 2%;
1000 倍面值的币安名字对得上 HL 的 k 币。
"""
import datetime as dt
import importlib.util
import json
from pathlib import Path

import pytest

from src.data.execution import regime_call as rc
from src.exec_host import runner as rn
from src.exec_host import tickets, verify

ROOT = Path(__file__).resolve().parents[1]
KEY = "11" * 32
NOW = dt.datetime(2026, 10, 22, 0, 50, tzinfo=dt.timezone.utc)
ASOF = "2026-10-21"
MASTER = "0x" + "ef" * 20


def _bars(n=260, end=ASOF, breakout=True, vol=1e6, base=10.0):
    """n 根日线,信号日(最后一根)收盘突破前 40 根最高(breakout)或不突破。"""
    end_d = dt.date.fromisoformat(end)
    out = []
    for i in range(n):
        d = end_d - dt.timedelta(days=n - 1 - i)
        c = base + 0.001 * i
        out.append({"d": d.isoformat(), "o": c, "h": c * 1.02, "l": c * 0.98, "c": c, "v": vol})
    last = out[-1]
    if breakout:
        last.update(c=base * 1.2, h=base * 1.22, o=base * 1.1)
    return out


def _stop(bars):
    m = verify.rv2_check(bars, bars[-1]["d"], bars[-1]["c"], 0.1)["metrics"]
    return m["stop_frac_hl"]


# ── 规则 V ─────────────────────────────────────────────────────────────────────
def test_rule_v_constants_are_the_preregistered_ones():
    assert (verify.TOL_PX, verify.LOOKBACK, verify.SMA_N, verify.STOP_ATR, verify.ATR_N) == (0.01, 40, 200, 2.5, 14)
    assert (verify.PRICE_AGREE, verify.STOP_RATIO_LO, verify.STOP_RATIO_HI, verify.ADV_MIN_USD) == (0.03, 0.67, 1.5, 1e6)
    assert verify.DEFAULT_MODE == "report", "S-666 ❌ ⇒ 默认只记不拦,S-667 过了才改"


def test_hl_bars_normalises_snapshot_rows():
    ms = int(dt.datetime(2026, 10, 21, tzinfo=dt.timezone.utc).timestamp() * 1000)
    rows = [{"t": ms, "o": "1", "h": "2", "l": "0.5", "c": "1.5", "v": "10"},
            {"t": ms - 86_400_000, "o": "1", "h": "1", "l": "1", "c": "1", "v": "0"},
            {"t": ms, "o": "1", "h": "2", "l": "0.5", "c": "1.6", "v": "11"},
            {"t": None, "o": "1"}]
    b = verify.hl_bars(rows)
    assert [x["d"] for x in b] == ["2026-10-20", "2026-10-21"] and b[-1]["c"] == 1.6


def test_a_real_breakout_passes_and_each_check_can_fail_on_its_own():
    b = _bars()
    sf = _stop(b)
    ok = verify.rv2_check(b, ASOF, b[-1]["c"], sf)
    assert ok["ok"] and ok["ok_v1_6"], ok
    assert not verify.rv2_check(_bars(breakout=False), ASOF, 10.26, sf)["ok"]
    assert any(f.startswith("V3") for f in verify.rv2_check(_bars(breakout=False), ASOF, 10.26, sf)["fails"])
    assert verify.rv2_check(b, ASOF, b[-1]["c"] / 1000, sf)["ok"], "币安 1000X / HL kX:倍数 1000 认得"
    assert any(f.startswith("V5") for f in verify.rv2_check(b, ASOF, b[-1]["c"] * 1.05, sf)["fails"])
    assert any(f.startswith("V6") for f in verify.rv2_check(b, ASOF, b[-1]["c"], sf * 3)["fails"])
    assert verify.rv2_check(b[-30:], ASOF, b[-1]["c"], sf)["fails"][0].startswith("V2")
    assert verify.rv2_check(b[:-1], ASOF, b[-1]["c"], sf)["fails"][0].startswith("V1")
    thin = verify.rv2_check(_bars(vol=1.0), ASOF, 12.0, sf)
    assert not thin["ok"] and thin["ok_v1_6"] and thin["fails"][0].startswith("V7"), "只栽 V7 ⇒ V′ 仍算过"
    assert verify.rv2_check(_bars(vol=0.0), ASOF, 12.0, sf)["ok"], "成交量全为零的回填段不查 V7"


def test_short_history_skips_sma200_but_still_needs_the_breakout():
    b = _bars(n=60)
    assert verify.rv2_check(b, ASOF, b[-1]["c"], _stop(b))["ok"]
    assert "sma200" not in verify.rv2_check(b, ASOF, b[-1]["c"], _stop(b))["metrics"]


# ── 签名 ───────────────────────────────────────────────────────────────────────
def _payload(**kw):
    p = {"state": "on", "conviction": 2, "battlefield": ["hype"], "close": [], "days": 14, "note": "第二段",
         "signed_at": "2026-10-21T10:00:00+00:00", "nonce": "ab" * 8}
    p.update(kw)
    return p


def _call(p=None, key=KEY, tamper=None):
    signed, sig = verify.sign(p or _payload(), key)
    if tamper:
        signed = signed.replace(*tamper)
    return {"state": "on", "conviction": 3, "battlefield": ["HYPE", "PUMP"], "signed": signed, "sig": sig}


def test_signature_round_trip_and_every_way_to_break_it():
    c = _call()
    p, why = verify.open_signed(c["signed"], c["sig"], KEY)
    assert p == _payload() and why == ""
    assert verify.open_signed(c["signed"], c["sig"], "22" * 32)[1] == "签名不对"
    t = _call(tamper=('"conviction":2', '"conviction":3'))
    assert verify.open_signed(t["signed"], t["sig"], KEY)[1] == "签名不对", "改一个字就不认"
    assert verify.open_signed(c["signed"], c["sig"], None)[1].startswith("主机没有")
    assert verify.open_signed(None, None, KEY)[1] == "这条判断没有签名"
    assert verify.key_fingerprint(KEY) != verify.key_fingerprint("22" * 32) and KEY not in verify.key_fingerprint(KEY)


def test_the_signed_window_is_the_railway_governing_rule():
    for at in ("2026-10-21T10:00:00+00:00", "2026-10-21T23:59:30+00:00"):
        body = {"state": "on", "conviction": 2, "battlefield": [], "close": [], "days": 3, "note": ""}
        p = {**body, "signed_at": at, "nonce": "cd" * 8}
        signed, sig = verify.sign(p, KEY)
        row, why = rc.validate_call({**body, "signed": signed, "sig": sig}, [], dt.datetime.fromisoformat(at))
        assert not why and row["at"] == dt.datetime.fromisoformat(at).isoformat()
        row["id"] = 1
        for day in ("2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25"):
            assert verify.governs(p, day) == (rc.governing_call([row], day) is not None), (at, day)


def test_tables_shared_with_railway_are_the_same():
    assert verify.RISK_MULT == rc.RISK_MULT and verify.MAX_RISK_MULT == rc.MAX_RISK_MULT
    assert verify.SIGNED_FIELDS == rc.SIGNED_FIELDS and verify.MAX_SIGN_SKEW_S == rc.MAX_SIGN_SKEW_S


def test_railway_checks_the_signed_content_matches_and_is_fresh_but_cannot_verify_it():
    body = {"state": "on", "conviction": 2, "battlefield": [], "close": [], "days": 14, "note": "x"}
    now = dt.datetime(2026, 10, 21, 10, 0, 30, tzinfo=dt.timezone.utc)
    p = {**body, "signed_at": "2026-10-21T10:00:00+00:00", "nonce": "ef" * 8}
    signed, sig = verify.sign(p, KEY)
    row, why = rc.validate_call({**body, "signed": signed, "sig": sig}, [], now)
    assert not why and row["sig"] == sig and row["signed"] == signed
    _, why = rc.validate_call({**body, "conviction": 3, "signed": signed, "sig": sig}, [], now)
    assert any("conviction" in w for w in why), "body 与签名内容不一致 ⇒ 拒"
    _, why = rc.validate_call({**body, "signed": signed, "sig": sig}, [], now + dt.timedelta(minutes=10))
    assert any("签名时间" in w for w in why), "旧签名不能重放"
    row, why = rc.validate_call(body, [], now)
    assert not why and row["signed"] is None and row["sig"] is None, "没签名照收"
    assert {"signed", "sig"} <= set(rc.call_view({**row, "id": 1}))


# ── 一轮的复核 ─────────────────────────────────────────────────────────────────
def _tplan(enter, call=None):
    return {"asof": ASOF, "ready": True, "risk_frac": 0.005, "cap": 10, "enter": enter, "hold": [], "exit": [],
            "regime_call": call or {"source": "system_default"}}


def _rv2(tid, sym="UNI", ref=12.0, sf=None, mult=1.0):
    return {"ticket_id": tid, "symbol": sym, "signal_d": ASOF, "ref_close": ref, "stop_frac": sf, "risk_mult": mult}


def _j(coin="HYPE", mult=1.5):
    return {"ticket_id": f"J:{coin}:{ASOF}", "symbol": coin, "signal_d": ASOF, "ref_close": 30.0, "stop_frac": 0.1,
            "risk_mult": mult, "book": "jazz"}


def test_report_never_blocks_r_v2_but_enforce_blocks_on_v1_to_v6_only():
    good, flat = _bars(), _bars(breakout=False)
    sf = _stop(good)
    tp = _tplan([_rv2("A", "UNI", good[-1]["c"], sf), _rv2("B", "SOL", 10.26, sf), _rv2("C", "ARB", 12.0, sf)])
    bars = {"UNI": good, "SOL": flat, "ARB": _bars(vol=1.0)}
    coin = {"A": "UNI", "B": "SOL", "C": "ARB"}
    rep, s = verify.review(tp, bars, coin, None, "report")
    assert [e["ticket_id"] for e in rep["enter"]] == ["A", "B", "C"] and s["passed"] == 1 and s["blocked"] == 0
    enf, s = verify.review(tp, bars, coin, None, "enforce")
    assert [e["ticket_id"] for e in enf["enter"]] == ["A", "C"], "C 只栽 V7 ⇒ V′ 过"
    assert enf["host_rejected"][0]["ticket_id"] == "B" and "V3" in enf["host_rejected"][0]["why"]


def test_j_tickets_need_a_valid_signature_in_every_mode():
    p = _payload(signed_at="2026-10-21T08:00:00+00:00")
    for mode in ("report", "enforce", "off"):
        out, s = verify.review(_tplan([_j()], _call(p)), {}, {_j()["ticket_id"]: "HYPE"}, None, mode)
        assert not out["enter"] and "签名" in out["host_rejected"][0]["why"], mode
    out, s = verify.review(_tplan([_j()], _call(p)), {}, {_j()["ticket_id"]: "HYPE"}, KEY, "report")
    assert [e["ticket_id"] for e in out["enter"]] == [_j()["ticket_id"]] and s["call_signed"]
    for bad, why in ((_j("PUMP"), "不在签名里的战场"), (_j(mult=2.0), "风险倍数")):
        out, _ = verify.review(_tplan([bad], _call(p)), {}, {bad["ticket_id"]: bad["symbol"]}, KEY, "report")
        assert not out["enter"] and why in out["host_rejected"][0]["why"], why
    off = _payload(state="off", battlefield=[], conviction=1, signed_at="2026-10-21T08:00:00+00:00")
    out, _ = verify.review(_tplan([_j()], _call(off)), {}, {_j()["ticket_id"]: "HYPE"}, KEY, "report")
    assert not out["enter"]
    stale = _payload(signed_at="2026-09-01T08:00:00+00:00")
    out, _ = verify.review(_tplan([_j()], _call(stale)), {}, {_j()["ticket_id"]: "HYPE"}, KEY, "report")
    assert not out["enter"] and "有效期" in out["host_rejected"][0]["why"]


def test_r_v2_risk_mult_needs_a_signed_on_call_behind_it():
    b = _bars()
    e = _rv2("A", "UNI", b[-1]["c"], _stop(b), mult=2.0)
    out, s = verify.review(_tplan([e], {"state": "on", "conviction": 3}), {"UNI": b}, {"A": "UNI"}, KEY, "report")
    assert out["enter"][0]["risk_mult"] == 1.0 and s["call_mult"] == 1.0, "没签名 ⇒ 压回 1 倍"
    p = _payload(signed_at="2026-10-21T08:00:00+00:00")                       # 签名里 conviction 2 ⇒ 1.5
    out, s = verify.review(_tplan([e], _call(p)), {"UNI": b}, {"A": "UNI"}, KEY, "report")
    assert out["enter"][0]["risk_mult"] == 1.5 and "签名支撑 1.5" in out["enter"][0]["risk_mult_note"]


# ── 主机:接进执行器 ───────────────────────────────────────────────────────────
class Venue:
    def __init__(self, bars):
        self.bars, self.asked = bars, []

    def perp_meta(self):
        return {"UNI": 1, "HYPE": 2}

    def perp_mids(self):
        return {"UNI": 12.0, "HYPE": 30.0}

    def perp_state(self):
        return {"ok": True, "equity": 704.0, "positions": {}}

    def daily_bars(self, coin, through):
        self.asked.append((coin, through.isoformat()))
        return self.bars.get(coin, [])

    def exchange(self):
        raise AssertionError("测试里不建交易客户端")


class Rw:
    def plan(self):
        return 200, {}

    def report(self, payload):
        return 200, {}


def _exe(tmp_path, env_extra=None):
    env = {"EXECUTOR_MODE": "dry_run", "EXECUTOR_TICKETS_MODE": "dry_run", "HL_ACCOUNT_ADDRESS": MASTER,
           "EXECUTOR_TOKEN": "t", "EXECUTOR_STATE_DIR": str(tmp_path), **(env_extra or {})}
    return rn.Executor(rn.Config(env), Venue({"UNI": _bars(end=ASOF, base=10.0)}), Rw(), clock=lambda: NOW)


def test_the_host_cycle_verifies_against_hl_and_refuses_unsigned_j_tickets(tmp_path, monkeypatch):
    monkeypatch.delenv("JAZZ_CALL_KEY", raising=False)
    e = _exe(tmp_path)
    b = e.venue.bars["UNI"]
    p = _payload(signed_at="2026-10-21T08:00:00+00:00")
    e.state.set(ticket_plan=_tplan([_rv2("A", "UNI", b[-1]["c"], _stop(b)), _j()], _call(p)))
    r = e.run_ticket_cycle(NOW)
    assert e.venue.asked == [("UNI", ASOF)], "只为 R-v2 票取日线"
    assert [x["ticket_id"] for x in r["entries"]] == ["A"]
    assert any("签名" in n["why"] for n in r["not_executable"]) and r["verify"]["mode"] == "report"
    assert r["verify"]["key_fingerprint"] is None


def test_with_the_key_the_signed_j_ticket_goes_through(tmp_path, monkeypatch):
    monkeypatch.setenv("JAZZ_CALL_KEY", KEY)
    e = _exe(tmp_path)
    p = _payload(signed_at="2026-10-21T08:00:00+00:00")
    e.state.set(ticket_plan=_tplan([_j()], _call(p)))
    r = e.run_ticket_cycle(NOW)
    assert [x["ticket_id"] for x in r["entries"]] == [_j()["ticket_id"]] and r["entries"][0]["risk_mult"] == 1.5
    assert r["verify"]["key_fingerprint"] == verify.key_fingerprint(KEY)
    assert KEY not in json.dumps(r, ensure_ascii=False), "密钥不进回报"


def test_bad_verify_mode_refuses_to_start():
    with pytest.raises(SystemExit):
        rn.Config({"HL_ACCOUNT_ADDRESS": MASTER, "EXECUTOR_TOKEN": "t", "EXECUTOR_VERIFY": "maybe"})


# ── tickets:主机自己的上限与币名 ───────────────────────────────────────────────
def test_binance_1000_names_map_to_hl_k_coins():
    assert tickets.resolve_coin("1000SHIB", {"kSHIB": 0}) == "kSHIB"
    assert tickets.resolve_coin("1000X", {"1000X": 0}) == "1000X", "名字本身在 HL 上就用本名"
    assert tickets.resolve_coin("1000", {"k": 0}) is None


def test_host_caps_risk_frac_from_the_plan(tmp_path, monkeypatch):
    monkeypatch.delenv("JAZZ_CALL_KEY", raising=False)
    e = _exe(tmp_path, {"EXECUTOR_VERIFY": "off"})
    tp = _tplan([{"ticket_id": "A", "symbol": "UNI", "signal_d": ASOF, "ref_close": 12.0, "stop_frac": 0.1}])
    tp["risk_frac"] = 0.5                                                   # 上游被改成每票 50%
    e.state.set(ticket_plan=tp)
    r = e.run_ticket_cycle(NOW)
    assert r["entries"][0]["risk_usd"] == pytest.approx(704.0 * tickets.MAX_RISK_FRAC)
    assert r["verify"]["risk_frac_capped"] == {"plan": 0.5, "host": 0.02}


# ── Mac:CLI 签名 ───────────────────────────────────────────────────────────────
def test_the_cli_signs_what_railway_accepts(tmp_path, monkeypatch):
    kf = tmp_path / "regime_call.key"
    kf.write_text(KEY + "\n")
    monkeypatch.setenv("REGIME_CALL_KEY_FILE", str(kf))
    spec = importlib.util.spec_from_file_location("regime_call_cli", ROOT / "scripts" / "regime_call.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    body = {"state": "on", "conviction": 2, "note": "n", "days": 14, "battlefield": [], "close": []}
    signed = cli.sign_body(body)
    row, why = rc.validate_call(signed, [], dt.datetime.now(dt.timezone.utc))
    assert not why and row["sig"] == signed["sig"]
    p, why = verify.open_signed(row["signed"], row["sig"], KEY)
    assert p and p["conviction"] == 2
    monkeypatch.setenv("REGIME_CALL_KEY_FILE", str(tmp_path / "missing.key"))
    spec.loader.exec_module(cli)
    assert "sig" not in cli.sign_body(body), "没有密钥 ⇒ 不签,照发"
