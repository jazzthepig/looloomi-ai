"""Pytest fixtures and configuration for looloomi-ai tests."""

import sys
import os
from pathlib import Path

# Add project root to path (parent of src/)
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
# ⚠️ `src/` 必须排在仓库根**前面**(11-16):仓库根下有一个运行时产物目录 `data/`
# (cash_sleeve 的 csv),它是 namespace package —— `import data` 一旦先撞上它,`data` 就被
# 解析成 `<repo>/data`,路由里那种 `from data.market.data_layer import ...` 再也找不到
# `data.market`(namespace package 先到先得,之后改 sys.path 也救不回来)。
# 单独跑一份测试是绿的、全量收集时炸,就是顺序问题:某个测试直接 import 了路由,那时
# `src/` 还不在 sys.path 上。
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# S-903(11-23):带着 GIT_DIR / GIT_WORK_TREE 跑测试 ⇒ 测试里在临时目录起的 git 全打在真仓库上
# (那天在本地 main 上落了一个 99 个文件的提交)。进程一开始就删掉这些变量,并说出来。
from tests._git_env import scrub_git_env  # noqa: E402

_scrubbed = scrub_git_env()
if _scrubbed:
    print(f"⚠ tests/conftest.py:删掉了会把 git 指到别处的环境变量 {_scrubbed}(S-903)", file=sys.stderr)

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
