"""
CometCloud Agent Definitions

HARNESS Architecture — Phase D
5 subagents migrated from .md files to AgentDefinition Python objects.
"""

# ── Market Signal Agent ───────────────────────────────────────────────────────

MARKET_SIGNAL_AGENT = {
    "name": "market-signal",
    "description": "On-chain market signals — whale flows, stablecoin supply, orderbook depth",
    "tools": ["Read", "Bash", "Grep"],
    "model": "haiku",
    "skills": ["cis-methodology"],
    "schedule": "0 * * * *",  # hourly at :00
    "prompt": "Market signal — collect whale flows, CEX orderbook depth, stablecoin supply changes",
}

# ── CIS Scorer Agent ──────────────────────────────────────────────────────────

CIS_SCORER_AGENT = {
    "name": "cis-scorer",
    "description": "CIS v4.1 scoring — push scores to Railway /internal/cis-scores",
    "tools": ["Read", "Bash"],
    "model": "haiku",
    "skills": ["cis-methodology"],
    "schedule": "5 * * * *",  # hourly at :05
    "prompt": "CIS scorer — compute CIS scores for universe, push to Railway via /internal/cis-scores",
}

# ── Macro Pulse Agent ─────────────────────────────────────────────────────────

MACRO_PULSE_AGENT = {
    "name": "macro-pulse",
    "description": "Macro regime detection — BTC/FNG/VIX, regime classification, brief generation",
    "tools": ["Read", "Bash", "WebFetch"],
    "model": "haiku",
    "skills": ["cis-methodology"],
    "schedule": "10 * * * *",  # hourly at :10
    "prompt": "Macro pulse — update macro regime, BTC/FNG/VIX signals, push brief to Railway",
}

# ── GP Monitor Agent ──────────────────────────────────────────────────────────

GP_MONITOR_AGENT = {
    "name": "gp-monitor",
    "description": "GP performance tracking — TVL, yield, risk metrics for monitored GPs",
    "tools": ["Read", "Bash", "Grep"],
    "model": "haiku",
    "skills": ["cis-methodology"],
    "schedule": "0 6 * * *",  # daily at 06:00
    "prompt": "GP monitor — fetch GP TVL/yield data, update performance metrics",
}

# ── Report Generator Agent ─────────────────────────────────────────────────────

REPORT_GENERATOR_AGENT = {
    "name": "report-generator",
    "description": "Daily intelligence reports — Macro Brief, GP summary, signal digest",
    "tools": ["Read", "Bash", "Write"],
    "model": "sonnet",
    "skills": ["cis-methodology", "compliance-language"],
    "schedule": "0 7 * * *",  # daily at 07:00
    "prompt": "Report generator — compile daily intelligence digest, push to Railway",
}

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

# ── Registry ───────────────────────────────────────────────────────────────────

AGENTS = {
    # Scheduled data agents (Phase G)
    "market-signal": MARKET_SIGNAL_AGENT,
    "cis-scorer": CIS_SCORER_AGENT,
    "macro-pulse": MACRO_PULSE_AGENT,
    "gp-monitor": GP_MONITOR_AGENT,
    "report-generator": REPORT_GENERATOR_AGENT,
    # HARNESS orchestration agents (Phase D)
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
