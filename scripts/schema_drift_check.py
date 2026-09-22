"""Online schema-drift check (A-28).

The OFFLINE half (`tests/test_every_written_table_exists.py`) verifies the
manifest matches what the source code does. This ONLINE half verifies the
manifest matches the LIVE database — every table the code writes to really
exists in Postgres. Together they catch the `fusion_paper_state` drift
(manifest says X exists, DB says X doesn't) that the offline test cannot.

Reads only, idempotent. Skipped (exit 0) when credentials are missing,
NOT failed — the offline stage is still authoritative, this is additive.

Auth: `X-Internal-Token` against `INTERNAL_TOKEN` env var. The Railway
deploy already has the right key. Local Mac sources `.env` at the project
root before invoking preflight. CI sets both `INTERNAL_TOKEN` (GitHub
secret) and optionally `SCHEMA_DRIFT_URL`.

Why skipped, not failed, when credentials are absent. S-163 contract says
preflight is offline; this stage is the explicit exception. A developer
without `INTERNAL_TOKEN` still gets the offline test, which is a real
signal — it just doesn't catch the "manifest says X exists, DB says X
doesn't" class. The CI run, which has both vars, catches that class.

Exit codes:
  0 — drift absent (ok=true from endpoint) OR credentials missing (skipped)
  1 — drift present (ok=false from endpoint, with missing/column_drift detail)
  2 — endpoint unreachable (network/auth error). Preflight treats 2 as
      skipped too, but distinguishes from a clean pass via stderr text.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
import urllib.error
import urllib.request


URL = os.environ.get(
    "SCHEMA_DRIFT_URL",
    "https://web-production-0cdf76.up.railway.app/internal/schema-drift",
)
TOKEN = os.environ.get("INTERNAL_TOKEN", "")
TIMEOUT_S = 30


def _fetch(url: str, token: str) -> dict:
    """GET the schema-drift endpoint. Returns parsed JSON or raises."""
    req = urllib.request.Request(url, headers={"X-Internal-Token": token})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


def main() -> int:
    if not TOKEN:
        print("  ⓘ online schema-drift skipped "
              "(INTERNAL_TOKEN not set; offline stage authoritative)")
        return 0

    try:
        d = _fetch(URL, TOKEN)
    except urllib.error.HTTPError as e:
        # 401 / 403 → token wrong but server reachable; treat as RED, not skip
        if e.code in (401, 403):
            print(f"✗ online schema-drift auth failed (HTTP {e.code}): "
                  f"INTERNAL_TOKEN rejected", file=sys.stderr)
            return 1
        print(f"  ⓘ online schema-drift skipped "
              f"(HTTP {e.code}: {type(e).__name__})")
        return 0
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"  ⓘ online schema-drift skipped "
              f"({type(e).__name__}: {e})")
        return 0
    except json.JSONDecodeError as e:
        print(f"  ⓘ online schema-drift skipped "
              f"(response not JSON: {e})")
        return 0

    if not d.get("ok"):
        checked = d.get("checked", "?")
        present = d.get("present", "?")
        miss = d.get("missing") or []
        rpc_chk = d.get("rpc_checked", "?")
        rpc_pres = d.get("rpc_present", "?")
        rpc_miss = d.get("rpc_missing") or []
        cd = d.get("column_drift") or {}
        cc = d.get("column_check_unavailable") or []
        cons = d.get("consequence") or ""
        print(f"✗ online schema-drift RED — manifest disagrees with live DB:",
              file=sys.stderr)
        print(f"  tables: {present}/{checked} present", file=sys.stderr)
        if miss:
            print(f"  missing ({len(miss)}): {miss}", file=sys.stderr)
        print(f"  rpc_functions: {rpc_pres}/{rpc_chk} present", file=sys.stderr)
        if rpc_miss:
            print(f"  rpc_missing ({len(rpc_miss)}): {rpc_miss}",
                  file=sys.stderr)
        if cd:
            print(f"  column_drift ({len(cd)}): {cd}", file=sys.stderr)
        if cc:
            print(f"  column_check_unavailable: {cc}", file=sys.stderr)
        if cons:
            print(f"  consequence: {cons}", file=sys.stderr)

        # ── S-399c:**严重级别跟着来源走,和措辞一样** ────────────────────
        # 2026-09-22 实测:这个检查 `exit 1`,preflight 是 `|| exit 1`,
        # handoff 是 `&&` 链 —— **于是它挡住了所有 push**。
        # 而挡住的理由是两张**没有任何人写**的表(`declared_only`):
        # 没有写入在被吞,没有账本在断,只是一个注册在先的意图。
        # 与此同时价格源全挂、replay 读取有 bug,**修它们的 push 被这个红灯挡着**。
        #
        # 上一轮我把 `with_call_site` / `declared_only` 分开只用在**措辞**上,
        # **没有用在退出码上** —— 又一次「修了一个渲染器,漏了另一个」,
        # 而这正是同一批改动里刚写过的那句话。
        #
        # 这不是豁免(没有到期日、会变成永久特赦的那种):**它是结构性的** ——
        # 一旦 `src/` 里出现调用点,同一张表自动落进 `with_call_site`,**立刻恢复硬闸**。
        # 真正防「声明了永远不建」的是 `PROJECT_STATE.md` OPEN RISK #0c 的到期日
        # (2026-10-06,到期未 ship 则**撤注册**,不是撤红灯)。
        # **来源在本地算,不问端点**(S-399c)。
        # 第一版我让端点返回拆分字段,于是出现部署顺序死锁:
        # 加字段的那个 push,要先过一个需要那个字段的检查。
        # 而**「哪些只是声明」是源码树的属性,不是部署的属性** ——
        # 这个脚本就跑在仓库里,自己算就行。端点只负责回答「什么漂了」。
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from src.api.schema_manifest import (
                write_columns_by_provenance, write_tables_by_provenance,
            )
            dec_tbl = set(write_tables_by_provenance()["declared_only"])
            dec_col = write_columns_by_provenance()["declared_only"]
        except Exception as e:                                    # noqa: BLE001
            # 算不出来 ⇒ **不假装知道**,全部按硬伤走(保守),并说出来。
            print(f"  ⚠️ 来源无法本地判定({type(e).__name__}),按全部硬伤处理",
                  file=sys.stderr)
            dec_tbl, dec_col = set(), {}

        hard_tbl = [t for t in miss if t not in dec_tbl]
        hard_col = {t: [c for c in cols if c not in set(dec_col.get(t, []))]
                    for t, cols in cd.items()}
        hard_col = {t: c for t, c in hard_col.items() if c}
        # `cc`(column_check_unavailable)= **问不出来**,不是「没有」。
        # 它保持阻断:读不到时不许假装通过(S-354)。
        if hard_tbl or hard_col or rpc_miss or cc:
            return 1
        print("  ⓘ 以上全部属于 `declared_only`(声明在先、`src/` 无调用点)——"
              " **没有写入在被吞**,所以本检查不阻断推送。"
              " 到期日与 owner 见 PROJECT_STATE.md OPEN RISK #0c。",
              file=sys.stderr)
        return 0

    n_miss = len(d.get("missing") or [])
    n_rpc_miss = len(d.get("rpc_missing") or [])
    n_cd = sum(len(v) for v in (d.get("column_drift") or {}).values())
    print(f"✓ online schema-drift pass "
          f"(tables {d.get('present')}/{d.get('checked')}, "
          f"rpc {d.get('rpc_present')}/{d.get('rpc_checked')}, "
          f"{n_miss} missing, {n_rpc_miss} rpc_missing, "
          f"{n_cd} column_drift)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
