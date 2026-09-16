"""Tests for factory router — fund operations.

⚠️ S-358 —— 这些测试原来断言 `data_source == "mock"`。

**硬规则 9:「No mock data in production paths. Prefer empty + flagged over
fabricated.」** 所以那 9 条在**强制一个规则明令禁止的契约** —— 一条被废掉的约定,
由测试守着,而守卫比约定活得更久。

现在断言的是真实契约:vault 未部署 ⇒ **503 + `status=coming_soon` +
`data_source="none"`**。没有数据就说没有数据。

门叫 `_VAULT_READY`,不叫 `_SOLANA_READY`(S-358):Jazz 2026-09-16 ——
**Solana 将来是其中一个渠道和公链,不是唯一;vault 现在优先 ETH L2**。
用链名当闸门名,会让「vault 没上线」和「Solana 没上线」长成同一件事。

vault 真上线那天,`_VAULT_READY` 和这些断言**一起改** —— 契约变了,
守它的测试也必须变,那才是这个文件存在的意义。
"""

import pytest


def _refuses(r) -> None:
    """未部署时的真实契约:503 + 说清楚为什么 + 不假装有数据。"""
    assert r.status_code == 503, f"expected a refusal, got {r.status_code}"
    d = r.json()
    assert d.get("status") == "coming_soon"
    assert d.get("data_source") == "none", (
        "a refusal must not be labelled 'mock' — rule 9 prefers empty+flagged "
        "over fabricated, and 'mock' reads as 'we served you something'")
    assert d.get("vault_ready") is False
    assert "ETH L2" in (d.get("message") or ""), (
        "the message must name the current build order, not a chain we retired "
        "as the sole gate")


class TestFactoryHealth:
    """Factory refuses honestly until a vault is live."""

    def test_factory_health(self, client):
        """Health is the one endpoint that answers while the vault is down."""
        r = client.get("/api/v1/factory/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert "vault_ready" in data, (
            "health must say whether a vault is live — otherwise 'healthy' "
            "reads as 'funds are available'")

    def test_factory_list_funds(self, client):
        _refuses(client.get("/api/v1/factory/funds"))

    def test_factory_get_fund(self, client):
        _refuses(client.get("/api/v1/factory/fund/1"))

    def test_factory_get_fund_not_found(self, client):
        _refuses(client.get("/api/v1/factory/fund/99999"))

    def test_factory_deploy_refuses(self, client):
        _refuses(client.post("/api/v1/factory/deploy", json={
            "fund_id": 1, "name": "T", "symbol": "T",
            "management_fee_bps": 100, "performance_fee_bps": 1000,
            "min_investment": 1000, "max_investment": 1000000,
            "gp_authority": "gp", "treasury": "tr"}))

    def test_factory_deposit_refuses(self, client):
        _refuses(client.post("/api/v1/factory/deposit", json={
            "fund_id": 1, "base_currency_amount": 5000, "investor_wallet": "w"}))

    def test_factory_redeem_refuses(self, client):
        _refuses(client.post("/api/v1/factory/redeem", json={
            "fund_id": 1, "share_amount": 10, "investor_wallet": "w"}))

    def test_factory_nav_refuses(self, client):
        """S-358:这个端点在此之前无门 —— 它能在没有 vault 的情况下「更新 NAV」。"""
        _refuses(client.post("/api/v1/factory/nav", json={
            "fund_id": 1, "new_nav": 100, "gp_authority": "gp"}))

    def test_factory_whitelist_refuses(self, client):
        _refuses(client.post("/api/v1/factory/whitelist", json={
            "fund_id": 1, "investor": "w", "kyc_level": 1, "add": True}))

    def test_factory_position_refuses(self, client):
        _refuses(client.get("/api/v1/factory/position/1/x"))

    def test_a_malformed_request_is_not_a_refusal(self, client):
        """反向控制:422 ≠ 503。**「你的请求不合法」和「vault 没上线」是两回事**,
        而 FastAPI 在进函数体前就校验,所以门永远看不到畸形 payload ——
        第一版我用错 payload 测门,量到的是校验器不是门。"""
        r = client.post("/api/v1/factory/deposit", json={"fund_id": "not_an_int"})
        assert r.status_code == 422, f"expected validation error, got {r.status_code}"
