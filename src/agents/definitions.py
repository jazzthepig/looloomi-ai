"""
CometCloud Agent Definitions

HARNESS Architecture — Phase D
5 subagents migrated from .md files to AgentDefinition Python objects.
"""

# ── Compliance Auditor ─────────────────────────────────────────────────────────

COMPLIANCE_AUDITOR = {
    "name": "compliance-auditor",
    "description": "HK SFC compliance enforcement — scans for prohibited buy/sell language",
    "tools": ["Read", "Grep", "Glob"],
    "model": "sonnet",
    "skills": ["compliance-language"],
    "prompt": "Compliance auditor — scan for BUY, SELL, ACCUMULATE, AVOID in src/api/routers/, dashboard/src/",
}

# ── CIS Validator ──────────────────────────────────────────────────────────────

CIS_VALIDATOR = {
    "name": "cis-validator",
    "description": "CIS v4.1 scoring validation — recompute scores from raw data",
    "tools": ["Read", "Bash"],
    "model": "sonnet",
    "skills": ["cis-methodology"],
    "prompt": "CIS validator — recompute CIS from raw data and compare with given values",
}

# ── Deploy Verifier ────────────────────────────────────────────────────────────

DEPLOY_VERIFIER = {
    "name": "deploy-verifier",
    "description": "Post-deploy health checks — verify Railway endpoints after deployment",
    "tools": ["Read", "Bash", "WebFetch"],
    "model": "sonnet",
    "skills": ["deploy-workflow"],
    "prompt": "Deploy verifier — check /api/v1/cis/universe, /api/v1/market/macro-pulse, /api/v1/signals after deploy",
}

# ── Minimax Coordinator ────────────────────────────────────────────────────────

MINIMAX_COORDINATOR = {
    "name": "minimax-coordinator",
    "description": "Mac Mini ↔ Railway data pipeline — contract negotiator",
    "tools": ["Read", "Grep"],
    "model": "haiku",
    "skills": ["mac-mini-coordination"],
    "prompt": "Minimax coordinator — manage Mac Mini ↔ Railway interface contract, only edit MINIMAX_SYNC.md",
}

# ── Research Agent ─────────────────────────────────────────────────────────────

RESEARCH_AGENT = {
    "name": "research-agent",
    "description": "GP/RWA 深度研究 — structured research reports, no code changes",
    "tools": ["WebSearch", "WebFetch", "Read", "Write"],
    "model": "sonnet",
    "skills": ["cis-methodology"],
    "prompt": "Research agent — GP/RWA deep research, output structured reports, no code changes",
}

# ── Registry ───────────────────────────────────────────────────────────────────

AGENTS = {
    "compliance-auditor": COMPLIANCE_AUDITOR,
    "cis-validator": CIS_VALIDATOR,
    "deploy-verifier": DEPLOY_VERIFIER,
    "minimax-coordinator": MINIMAX_COORDINATOR,
    "research-agent": RESEARCH_AGENT,
}

def get_agent(name):
    return AGENTS.get(name)

def list_agents():
    return list(AGENTS.keys())
