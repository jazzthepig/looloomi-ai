"""Pytest fixtures and configuration for looloomi-ai tests."""

import sys
import os
from pathlib import Path

# Add project root to path (parent of src/)
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    # Import main after path setup
    from src.api.main import app
    return TestClient(app)


@pytest.fixture
def internal_token():
    """Internal token for protected endpoints."""
    return os.environ.get("INTERNAL_TOKEN", "test-internal-token")
