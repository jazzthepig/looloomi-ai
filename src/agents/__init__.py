"""
CometCloud Agents Package

HARNESS Architecture Phase D:
- definitions.py: AgentDefinition objects for 5+ agents
- orchestrator.py: Planning/Selector/Execution router

Usage:
  from src.agents import AGENTS, get_agent, HARNESSOrchestrator

  orchestrator = HARNESSOrchestrator()
  routed = orchestrator.route("scan for compliance")
  agent_info = get_agent("compliance-auditor")
"""

import os
import sys

# Ensure src/agents/ is in path for sibling imports
_agent_dir = os.path.dirname(os.path.abspath(__file__))
_root_dir = os.path.dirname(_agent_dir)
if _root_dir not in sys.path:
    sys.path.insert(0, _root_dir)

from src.agents.definitions import AGENTS, get_agent, list_agents
from src.agents.orchestrator import HARNESSOrchestrator

__all__ = ["AGENTS", "get_agent", "list_agents", "HARNESSOrchestrator"]