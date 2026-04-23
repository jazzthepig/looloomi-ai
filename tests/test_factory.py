"""Tests for factory router — fund operations."""

import pytest


class TestFactoryHealth:
    """Factory health and data source checks."""

    def test_factory_health(self, client):
        """Factory health endpoint returns expected fields."""
        r = client.get("/api/v1/factory/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert "data_source" in data
        assert data["data_source"] == "mock"

    def test_factory_list_funds(self, client):
        """List funds returns mock data with data_source field."""
        r = client.get("/api/v1/factory/funds")
        assert r.status_code == 200
        funds = r.json()
        assert isinstance(funds, list)
        if funds:
            assert "data_source" in funds[0]
            assert funds[0]["data_source"] == "mock"

    def test_factory_get_fund(self, client):
        """Get fund returns mock fund with data_source field."""
        r = client.get("/api/v1/factory/fund/1")
        assert r.status_code == 200
        fund = r.json()
        assert fund["fund_id"] == 1
        assert "data_source" in fund
        assert fund["data_source"] == "mock"

    def test_factory_get_fund_not_found(self, client):
        """Get non-existent fund returns 404."""
        r = client.get("/api/v1/factory/fund/999")
        assert r.status_code == 404

    def test_factory_deploy_returns_mock(self, client):
        """Deploy endpoint returns pending status with data_source=mock."""
        r = client.post(
            "/api/v1/factory/deploy",
            json={
                "fund_id": 99,
                "name": "Test Fund",
                "symbol": "TF",
                "management_fee_bps": 200,
                "performance_fee_bps": 2000,
                "min_investment": 10000,
                "max_investment": 1000000,
                "gp_authority": "GpAuthority1111111111111111111111111111111111111",
                "treasury": "Treasury1111111111111111111111111111111111111",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "pending"
        assert "data_source" in data
        assert data["data_source"] == "mock"

    def test_factory_deposit_returns_mock(self, client):
        """Deposit endpoint returns pending status with data_source=mock."""
        r = client.post(
            "/api/v1/factory/deposit",
            json={
                "fund_id": 1,
                "investor_wallet": "Wallet1111111111111111111111111111111111",
                "base_currency_amount": 50_000,
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "pending"
        assert "data_source" in data
        assert data["data_source"] == "mock"

    def test_factory_deposit_below_minimum(self, client):
        """Deposit below minimum returns 400."""
        r = client.post(
            "/api/v1/factory/deposit",
            json={
                "fund_id": 1,
                "investor_wallet": "Wallet1111111111111111111111111111111111",
                "base_currency_amount": 100,  # min is 10_000
            },
        )
        assert r.status_code == 400

    def test_factory_deposit_fund_not_found(self, client):
        """Deposit to non-existent fund returns 404."""
        r = client.post(
            "/api/v1/factory/deposit",
            json={
                "fund_id": 999,
                "investor_wallet": "Wallet1111111111111111111111111111111111",
                "base_currency_amount": 50_000,
            },
        )
        assert r.status_code == 404

    def test_factory_redeem_returns_mock(self, client):
        """Redeem endpoint returns pending status with data_source=mock."""
        r = client.post(
            "/api/v1/factory/redeem",
            json={
                "fund_id": 1,
                "investor_wallet": "Wallet1111111111111111111111111111111111",
                "share_amount": 1000,
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "pending"
        assert "data_source" in data
        assert data["data_source"] == "mock"

    def test_factory_position_mock(self, client):
        """Position endpoint returns mock data_source."""
        r = client.get("/api/v1/factory/position/1/Wallet1111111111111111111111111111111111")
        assert r.status_code == 200
        data = r.json()
        assert "data_source" in data
        assert data["data_source"] == "mock"
