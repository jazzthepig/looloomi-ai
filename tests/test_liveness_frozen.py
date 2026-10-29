"""冻结账本不进 liveness 的 dead / stale(src/data/accounting/frozen.py 的第五处生效点)。

10-29 实测:六本 ④ 冻结账本按裁决停写,liveness 把它们判 dead(marker)⇒ overall 永久 critical,
真正的 critical(执行主机 watch)淹在里面。登记表 docstring 写着「判活器判不适用」,这里一直没接。
"""
from src.api.liveness import compute_liveness_summary
from src.data.accounting.frozen import frozen_loops


def _row(loop, last_ok_at, last_run_at, age_s, verdict):
    return {"loop": loop, "last_ok_at": last_ok_at, "last_run_at": last_run_at, "age_s": age_s, "verdict": verdict}


def test_frozen_books_are_not_dead_and_do_not_make_overall_critical():
    frozen = sorted(frozen_loops())
    assert frozen, "registry is empty — this test would prove nothing"
    rows = [_row(l, 1_000, 1_000, 200 * 3600, "refusing") for l in frozen]
    rows.append(_row("_beta_core_loop", 100, 100, 3600, "ok"))
    s = compute_liveness_summary(rows)
    assert s["overall"] == "healthy", s
    assert s["n_dead"] == 0 and s["n_stale"] == 0
    assert s["frozen_loops"] == frozen and s["n_frozen"] == len(frozen)
    assert all(s["per_loop"][l]["verdict"] == "frozen" for l in frozen)
    assert s["n_live"] + s["n_stale"] + s["n_dead"] == s["n_total"]


def test_a_real_marker_failure_still_reads_critical_next_to_frozen_books():
    frozen = sorted(frozen_loops())
    rows = [_row(l, 1_000, 1_000, 200 * 3600, "refusing") for l in frozen]
    rows.append(_row("_executor_host_watch_loop", None, 100, 600, "failing"))
    s = compute_liveness_summary(rows)
    assert s["overall"] == "critical"
    assert s["marker_loops_problem"] == ["_executor_host_watch_loop"]
