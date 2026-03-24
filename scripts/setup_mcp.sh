#!/usr/bin/env bash
# CometCloud MCP Server — one-shot setup
# Usage: bash scripts/setup_mcp.sh
set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$REPO_DIR/src/mcp/.venv"
MCP_SCRIPT="$REPO_DIR/src/mcp/cometcloud_mcp.py"
PYTHON="$(which python3)"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  CometCloud MCP Server — Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 1. Create venv
echo "▸ Creating venv at src/mcp/.venv ..."
"$PYTHON" -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

# 2. Install deps
echo "▸ Installing dependencies ..."
pip install --quiet --upgrade pip
pip install --quiet "mcp[cli]>=1.6.0" "httpx>=0.27.0" "pydantic>=2.0.0"

VENV_PYTHON="$VENV_DIR/bin/python"

# 3. Syntax check
echo "▸ Verifying MCP server ..."
"$VENV_PYTHON" -m py_compile "$MCP_SCRIPT" && echo "  ✓ Syntax OK"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Setup complete."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Add this to your Claude Desktop config:"
echo "  ~/Library/Application Support/Claude/claude_desktop_config.json"
echo ""
cat <<JSON
{
  "mcpServers": {
    "cometcloud": {
      "command": "$VENV_PYTHON",
      "args": ["$MCP_SCRIPT"],
      "env": {
        "COMETCLOUD_API_BASE": "https://web-production-0cdf76.up.railway.app"
      }
    }
  }
}
JSON
echo ""
echo "Then restart Claude Desktop — CometCloud tools will appear automatically."
echo ""
echo "Test manually:"
echo "  source $VENV_DIR/bin/activate"
echo "  python $MCP_SCRIPT"
echo ""
