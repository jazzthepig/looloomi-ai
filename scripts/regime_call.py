#!/usr/bin/env python3
"""Jazz ⓪ 开关 —— 在 Mac 上提交 / 查看「何时在场、在哪」的判断(src/data/execution/regime_call.py)。

    python3 scripts/regime_call.py on   --conviction 2 --battlefield HYPE,UNI --note "第二段" [--days 14]
    python3 scripts/regime_call.py off  --note "流动性在转向"
    python3 scripts/regime_call.py flat --note "全平"
    python3 scripts/regime_call.py on   --close HYPE --note "HYPE 先走"
    python3 scripts/regime_call.py status
    python3 scripts/regime_call.py brief [--top 40]     # 战场简报:HL 前 N 永续的趋势 / 第二段形态 / 资金费(筛子,不是信号)

每次提交都是一条**完整**的判断(不是增量),最新一条生效;默认 14 天到期,到期回到系统默认(on、1 档、无战场)。
提交当天的判断管第二天 00:45 UTC 那一轮。要立刻停,用一键停(POST /internal/executor/halt)。
INTERNAL_TOKEN 先读环境变量,没有再读仓库根目录 .env 里那一行;不打印。

## 签名(S-666:主机不信上游)

    python3 scripts/regime_call.py keygen            # 第一次:在本机生成 ~/.cometcloud/regime_call.key(600),打印指纹
    python3 scripts/regime_call.py keygen --show     # 打印密钥本身 —— 只为抄进东京主机的 /etc/cometcloud/executor.env:
                                                     #   JAZZ_CALL_KEY=<那一串>,然后 systemctl restart cometcloud-executor

有密钥时每条判断都在本机签名(HMAC-SHA256),Railway 和库里只存签名、没有密钥;主机自己验。
**没签名的判断照收、照记分,但主机不会为它开 J 票,也不放大 R-v2 票的风险。** 两边指纹一致才算配好(主机日志与发件箱里有指纹)。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.exec_host import verify  # noqa: E402  只用标准库,Mac 上不用装别的

API = "https://web-production-0cdf76.up.railway.app"
KEY_FILE = Path(os.environ.get("REGIME_CALL_KEY_FILE", str(Path.home() / ".cometcloud" / "regime_call.key")))


def _key() -> str | None:
    try:
        k = KEY_FILE.read_text().strip()
        bytes.fromhex(k)
        return k or None
    except (OSError, ValueError):
        return None


def keygen(show: bool) -> None:
    k = _key()
    if k is None:
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        KEY_FILE.write_text(verify.new_key() + "\n")
        os.chmod(KEY_FILE, 0o600)
        k = _key()
        print(f"已生成 {KEY_FILE}(600)")
    print(f"指纹 {verify.key_fingerprint(k)} —— 主机发件箱里 verify.key_fingerprint 应该是同一个")
    if show:
        print(f"JAZZ_CALL_KEY={k}")
    else:
        print("抄到主机:python3 scripts/regime_call.py keygen --show(只在你自己的终端里看)")


def sign_body(body: dict) -> dict:
    k = _key()
    if k is None:
        print(f"⚠️  没有签名密钥({KEY_FILE})—— 这条判断会被记录,但主机不会为它开 J 票、也不放大风险。"
              f"先跑 keygen。", file=sys.stderr)
        return body
    p = {**{f: body.get(f) for f in ("state", "conviction", "battlefield", "close", "days", "note")},
         "signed_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
         "nonce": secrets.token_hex(8)}
    signed, sig = verify.sign(p, k)
    return {**body, "signed": signed, "sig": sig}


def _token() -> str:
    t = os.environ.get("INTERNAL_TOKEN", "").strip()
    if t:
        return t
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("INTERNAL_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("没有 INTERNAL_TOKEN(环境变量或仓库 .env)")


def _call(method: str, path: str, api: str, body: dict | None = None):
    req = urllib.request.Request(api.rstrip("/") + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Internal-Token": _token(), "Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=60).read())
    except urllib.error.HTTPError as e:
        if e.code in (404, 405):
            # 未知路径会落到前端的 GET 兜底路由上 ⇒ POST 得到 405:说明线上还是没有这个接口的旧版本
            sha = "?"
            try:
                sha = json.loads(urllib.request.urlopen(api.rstrip("/") + "/internal/build-state", timeout=20).read()
                                 ).get("git_sha_short", "?")
            except Exception:                                           # noqa: BLE001
                pass
            sys.exit(f"HTTP {e.code}:线上还没有 {path}(在跑的版本 {sha})—— 等 Railway 部署到含 regime_call 的提交"
                     f"(e30ac900 或更新)再试。判断没有提交,不用重发别的。")
        sys.exit(f"HTTP {e.code}: {e.read().decode()[:600]}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Jazz ⓪ 开关")
    ap.add_argument("state", choices=["on", "off", "flat", "status", "brief", "keygen"])
    ap.add_argument("--show", action="store_true", help="keygen:打印密钥本身(抄进主机用)")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--conviction", type=int, default=1, choices=[1, 2, 3])
    ap.add_argument("--battlefield", default="", help="逗号分隔的 HL 永续币名,如 HYPE,UNI")
    ap.add_argument("--close", default="", help="这些币的 J 票下一轮出场")
    ap.add_argument("--note", default="", help="为什么(会进记分卡)")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--api", default=os.environ.get("COMETCLOUD_API", API))
    a = ap.parse_args()
    if a.state == "keygen":
        keygen(a.show)
        return
    if a.state == "brief":
        r = _call("GET", f"/internal/regime-call/brief?top={a.top}", a.api)
        b = r["breadth"]
        pct = lambda x: "—" if x is None else f"{x * 100:+.0f}%"            # noqa: E731
        print(f"{r['at'][:16]}Z · 前 {b['n']} · SMA50 之上 {pct(b['above_sma50'])} · SMA200 之上 {pct(b['above_sma200'])}"
              f" · 破 20 日高 {pct(b['breakout_20d'])} · 第二段形态 {b['second_leg_setups']} 个"
              f" · 30 日中位 {pct(b['median_ret_30d'])} · 资金费中位 {pct(b['funding_apr_median'])}/年")
        print(f"{'币':8s} {'位置':8s} {'7日':>6s} {'30日':>6s} {'90日':>6s} {'离120日高':>8s} {'第一段':>6s} {'回撤':>6s}"
              f" {'止损宽':>6s} {'资金费':>6s} {'未平仓':>8s} {'价值捕获':>8s} {'90日稀释':>8s}")
        for x in r["rows"]:
            leg = f"{x['first_leg_x']:.1f}x" if x.get("first_leg_x") else "—"
            sw, vc = x.get("stop_width"), x.get("value_capture")
            stop = "—" if sw is None else f"{sw * 100:.0f}%"
            vcs = "—" if vc is None else f"{vc * 100:.0f}%"
            dl = x.get("dil90")
            dls = "—" if dl is None else f"{dl * 100:+.1f}%" + (" ⚠" if x.get("diluting") else "")
            print(f"{x['coin']:8s} {x['tag']:8s} {pct(x.get('ret_7d')):>6s} {pct(x.get('ret_30d')):>6s} "
                  f"{pct(x.get('ret_90d')):>6s} {pct(x.get('dd_from_120d_high')):>8s} {leg:>6s} {pct(x.get('pullback')):>6s} "
                  f"{stop:>6s} {pct(x.get('funding_apr')):>6s} {(x.get('oi_usd') or 0) / 1e6:>7.0f}M {vcs:>8s} {dls:>8s}")
        v = r.get("value_capture") or {}
        print(f"价值捕获比(持币人收入 ÷ 协议收入,60 天;描述不是信号 —— S-664:控制规模 / 波动 / 稀释后几乎不剩):接上 {v.get('matched', 0)} 个"
              f"{'' if not v.get('why_missing') else ' · ' + str(v['why_missing'])}")
        print("90 日稀释 = 流通量增长;⚠ = 一个季度 > 2.2%(S-665:R-v2 的票开在这类币上平均 +0.28R,其余 +0.57 / +0.76R)")
        print(r.get("note", ""))
        return
    if a.state == "status":
        r = _call("GET", "/internal/regime-call", a.api)
        nxt, last = r["next_cycle"], r["last_cycle"]
        c = nxt.get("call") or {}
        p, why = verify.open_signed(c.get("signed"), c.get("sig"), _key())
        print("签名:" + ("✓ 本机验过 —— 主机会认" if p else f"✗ {why} —— 主机不开 J 票、风险按 1 倍"))
        nxt = {**nxt, "call": {k: v for k, v in c.items() if k not in ("signed", "sig")}}
        print(f"下一轮(asof {nxt['asof']}):{json.dumps(nxt['call'], ensure_ascii=False)}")
        print(f"上一轮(asof {last['asof']}):{json.dumps(last['call'], ensure_ascii=False)}")
        print(f"在持 J 票:{[(j['ticket_id'], j['status']) for j in r['j_live']]}")
        print(f"记分:{json.dumps(r['scorecard']['totals'], ensure_ascii=False)}")
        return
    body = {"state": a.state, "conviction": a.conviction, "note": a.note, "days": a.days,
            "battlefield": [c.strip() for c in a.battlefield.split(",") if c.strip()],
            "close": [c.strip() for c in a.close.split(",") if c.strip()]}
    r = _call("POST", "/internal/regime-call", a.api, sign_body(body))
    if isinstance(r.get("call"), dict):
        r["call"] = {k: v for k, v in r["call"].items() if k not in ("signed", "sig")} | \
                    {"signed": bool(r["call"].get("sig"))}
    print(json.dumps(r, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
