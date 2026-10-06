"""T-004:持币集中度的源从 Moralis 换到 CoinGecko Analyst 的 onchain top_holders(S-499)。

Moralis 的 key 08-31 起没了,`holder_concentration_history` 停写 36 天;付费的 CG 档早已包含
`/onchain/.../top_holders`(S-268,09-01 登记)。这里钉住:CG 的响应形状能算出集中度,读不到不冒充「没有持有人」。
"""
import asyncio

from src.data.cis import holder_provider as hp

CG_HOLDERS = [{"rank": 1, "percentage": "31.0041"}, {"rank": 2, "percentage": "8.7543"},
              {"rank": 3, "percentage": "5.0"}] + [{"rank": i, "percentage": "1.0"} for i in range(4, 21)]


def test_concentration_from_cg_percentages():
    c = hp._concentration(CG_HOLDERS)
    assert c["n_top"] == 20
    assert abs(c["top10_share"] - (0.310041 + 0.087543 + 0.05 + 7 * 0.01)) < 1e-4
    assert hp._stage_from(c["top10_share"]) < 0.5


def test_fetch_one_uses_cg_and_labels_the_source(monkeypatch):
    async def fake(address, network="eth", holders=50):
        assert network == "arbitrum" and holders == 50
        return {"holders": CG_HOLDERS, "last_updated_at": "2026-10-06T00:00:00Z"}
    monkeypatch.setattr(hp, "get_cg_top_holders", fake)
    row = asyncio.run(hp._fetch_one("ARB", "arbitrum", "0xabc"))
    assert row["source"] == "cg_onchain_top_holders" and row["as_of"] == "2026-10-06T00:00:00Z"


def test_unreadable_is_none_not_an_empty_holder_set(monkeypatch):
    async def fake(address, network="eth", holders=50):
        return {"error": "HTTP 429"}
    monkeypatch.setattr(hp, "get_cg_top_holders", fake)
    assert asyncio.run(hp._fetch_one("UNI", "eth", "0xabc")) is None


def test_no_moralis_left_in_the_holder_path():
    import inspect
    src = inspect.getsource(hp)
    assert "get_token_holders" not in src and "MORALIS_KEY" not in src
