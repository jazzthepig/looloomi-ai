"""S-94(2026-07-30)/ 2026-10-22:anon 不许读到 cis_scores 的行。

10-20 的 lane_read 迁移把 cis_scores 放进了 anon 可读名单,而旧版 anon JWT 还活着、写在公开仓库里 ——
10-21 外部探针报 CRITICAL。这里在迁移文件层面守住:按文件名顺序,最后一个碰 cis_scores 的 anon 读策略的迁移
必须是撤掉它的那个;以后谁再把 cis_scores 放进 lane_read,这条就红(运行时还有 scripts/external_probe.sh)。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_last_migration_touching_cis_scores_anon_read_removes_it():
    touching = []
    for p in sorted((ROOT / "migrations").glob("*.sql")):
        sql = p.read_text(encoding="utf-8")
        if "cis_scores" not in sql:
            continue
        grants_policy = ("create policy lane_read" in sql and "'cis_scores'" in sql) or \
            ("create policy" in sql and "on public.cis_scores" in sql and "to anon" in sql)
        drops_policy = "drop policy if exists lane_read on public.cis_scores" in sql
        if grants_policy or drops_policy:
            touching.append((p.name, grants_policy, drops_policy))
    assert touching, "迁移里找不到任何 cis_scores 的 anon 策略记录 —— 检查是不是改名了"
    name, grants, drops = touching[-1]
    assert drops and not grants, f"{name} 是最后一个碰 cis_scores anon 读的迁移,它又打开了(S-94 必须保持撤销)"
