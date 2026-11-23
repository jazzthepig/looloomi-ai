"""研究读库,不直接打 CoinGecko —— 只减不增的门(S-908,2026-11-23)。

Jazz 11-23:「我们研究时候是否直接走了 api 而不是走我们数据库」。

量出来的(同一天):仓库里研究 / 脚本区 993 个 .py,**24 个**写着 CoinGecko 的 API 主机名 —— 它们不过闸门
(`cg_guard`:预算、熔断、记账都罩不到),花的额度 `/internal/cg-quota` 看不见。`tests/test_cg_call_sites.py`
管的是 `src/`,而且**明说排除研究区**;这里补上那一块。

规则只有一条:**名单只许变短。**
- 新脚本要数 ⇒ 读库(`ohlcv_daily_canonical` / `asset_mcap_daily` / `coin_supply_daily` / `market_snapshot` …)。
  库里没有 ⇒ 在 MINIMAX_SYNC 里说,由采集那一条 lane 取了落表(CLAUDE.md 规则 3b:采集只有一条路)。
- 真要现取(探一个新端点)⇒ 走 `src.data.market.data_layer` 的函数,那条路过闸门、记账。
- 名单里的文件改好了或删了 ⇒ 把它从名单里拿掉(下面第二个测试会要求你这么做)。

移动硬盘上的研究目录(Minimax 的 lane)不在仓库里,这个测试够不着 —— 那边 54 个,走 MINIMAX_SYNC。
"""
import asyncio
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: 扫哪儿:仓库里所有「不是线上取数路径」的代码。
SCAN = ("scripts", "docs/research", "src/research", "paper_trading")
#: 命中 = 文件里写着 CoinGecko 的 API 主机名(`pro-api.coingecko.com` 也含这一段)。
MARK = "api.coingecko.com"

#: 2026-11-23 的存量。**只许删,不许加。**
KNOWN = frozenset({
    "docs/research/T-376_probe.py",
    "docs/research/t107_cg_fetch.py",
    "docs/research/t162_source_probe.py",
    "docs/research/t188_venues.py",
    "docs/research/t210_depth.py",
    "docs/research/t210_depth2.py",
    "docs/research/t210_recon.py",
    "docs/research/t210_recon2.py",
    "docs/research/t210_tracking.py",
    "docs/research/t214_cites.py",
    "docs/research/t214_cites_gap2.py",
    "docs/research/t214_cites_gap3.py",
    "docs/research/t214_venues.py",
    "docs/research/t214_verify.py",
    "docs/research/t218_build.py",
    "docs/research/t220/probe_sources.py",
    "docs/research/t220/probe_sources2.py",
    "docs/research/t220/probe_sources3.py",
    "docs/research/t422_probe4.py",
    "scripts/compute_regime_fitness.py",
    "scripts/fetch_ohlcv_to_local.py",
    "scripts/probe_entity_sources.py",
    "scripts/reconstruct_cis_history.py",
    "scripts/trending_collector.py",
})


def direct_callers(root: Path = ROOT) -> set[str]:
    out = set()
    for d in SCAN:
        base = root / d
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            try:
                if MARK in p.read_text(encoding="utf-8", errors="ignore"):
                    out.add(p.relative_to(root).as_posix())
            except OSError:
                continue
    return out


def test_no_new_script_calls_coingecko_directly():
    new = sorted(direct_callers() - KNOWN)
    assert not new, (
        f"{len(new)} 个新文件直接打 CoinGecko(不过闸门、不记账):{new}\n"
        "读库:ohlcv_daily_canonical / asset_mcap_daily / coin_supply_daily / market_snapshot。\n"
        "库里没有 ⇒ MINIMAX_SYNC 里提,由采集 lane 取了落表;真要现取 ⇒ 走 src.data.market.data_layer(过闸门)。")


def test_the_list_only_shrinks():
    gone = sorted(KNOWN - direct_callers())
    assert not gone, f"这些文件已经不打 CoinGecko / 已删除 —— 把它们从 KNOWN 里拿掉(名单只许变短):{gone}"


def test_the_detector_sees_a_planted_file(tmp_path):
    """门自己得是通的:种一个新文件,它必须被看见;不带主机名的不算。"""
    (tmp_path / "docs/research").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "docs/research/t999_new.py").write_text(
        'import httpx\nr = httpx.get("https://pro-api.coingecko.com/api/v3/coins/markets")\n', encoding="utf-8")
    (tmp_path / "scripts/reads_db.py").write_text('URL = SUPABASE_URL + "/rest/v1/ohlcv_daily_canonical"\n', encoding="utf-8")
    assert direct_callers(tmp_path) == {"docs/research/t999_new.py"}


# ── 线上的同一条规矩:信号结算先读库 ──────────────────────────────────────────
# 11-23 我在审计里写过「信号结算每次都从 CoinGecko 重取 365 天历史」。读了代码、量了库,这句话是错的:
# 结算先读 `ohlcv_daily_canonical`,库里 ±4 天内没有才回落 —— 最近 30 天结算的 40 条,出场价 40 条都来自库,
# 最后一次回落到 CoinGecko 是 09-14。没改代码;下面把这个顺序钉住,免得哪天被「顺手」换回去。

def test_settlement_reads_our_table_first(monkeypatch):
    import src.data.signals.outcome_tracker as ot
    target = dt.datetime(2026, 10, 20, tzinfo=dt.timezone.utc)
    n = {"db": 0, "cg": 0}

    async def db(client, sym, t, window_days=4):
        n["db"] += 1
        return 100.0

    async def cg(sym, t, age_days):
        n["cg"] += 1
        return 99.0

    monkeypatch.setattr(ot, "_ohlcv_close_at", db)
    monkeypatch.setattr(ot, "_crypto_price_at", cg)
    assert asyncio.run(ot._bench_price(None, "BTC", target, 34.0, {})) == 100.0
    assert n == {"db": 1, "cg": 0}, "库里有,就不该碰 CoinGecko"


def test_settlement_falls_back_only_when_the_table_has_nothing(monkeypatch):
    import src.data.signals.outcome_tracker as ot
    target = dt.datetime(2026, 10, 20, tzinfo=dt.timezone.utc)
    n = {"cg": 0}

    async def db(client, sym, t, window_days=4):
        return None

    async def cg(sym, t, age_days):
        n["cg"] += 1
        return 99.0

    monkeypatch.setattr(ot, "_ohlcv_close_at", db)
    monkeypatch.setattr(ot, "_crypto_price_at", cg)
    cache: dict = {}
    assert asyncio.run(ot._bench_price(None, "BTC", target, 34.0, cache)) == 99.0
    assert asyncio.run(ot._bench_price(None, "BTC", target, 34.0, cache)) == 99.0
    assert n["cg"] == 1, "同一轮同一天只回落一次"


def test_exit_leg_asks_the_table_before_any_vendor():
    src = (ROOT / "src/data/signals/outcome_tracker.py").read_text(encoding="utf-8")
    run = src[src.index("async def run_outcome_tracker"):]
    assert run.index("_ohlcv_close_at(client, sym, target)") < run.index("_crypto_price_at(sym, target, age_days)")
    res = (ROOT / "src/data/signals/prediction_resolver.py").read_text(encoding="utf-8")
    assert res.index("_ohlcv_close_at(client, sym, dt)") < res.index("_crypto_price_at(sym, dt, age_days)")
