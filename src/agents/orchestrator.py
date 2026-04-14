"""
CometCloud Agent Orchestrator

HARNESS Architecture — Phase D
Three-layer routing: Planning Agent → Selector Agent → Execution Agent

Usage:
  python3 src/agents/orchestrator.py --agent compliance-auditor
  python3 src/agents/orchestrator.py --agent cis-validator --input '{"asset": "BTC"}'
  python3 src/agents/orchestrator.py --list
"""

import argparse
import json
import os
import sys
from typing import Any, Optional

# Add project root to path
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.dirname(__file__))  # for definitions.py in same dir

from definitions import AGENTS, get_agent


class HARNESSOrchestrator:
    """
    Three-layer HARNESS architecture:

    Planning Agent (opus)      — Analyzes task, decides routing
    Selector Agent (sonnet)     — Routes to specific subagent
    Execution Agent (haiku)     — Actually executes the task

    For now, we implement a simplified version that routes
    directly to the appropriate subagent based on task type.
    """

    def __init__(self):
        self.agents = AGENTS
        self.planning_prompt = """你是 CometCloud HARNESS 编排 agent。你的职责是将任务路由到正确的 subagent。

可用 subagents:
- market-signal: 链上市场信号（每小时 :00）
- cis-scorer: CIS v4.1 评分推送（每小时 :05）
- macro-pulse: 宏观脉搏检测（每小时 :10）
- gp-monitor: GP 表现追踪（每日 06:00）
- report-generator: 每日情报报告（每日 07:00）
- compliance-auditor: 扫描违规买入/卖出语言
- cis-validator: 验证 CIS 评分计算
- deploy-verifier: 部署后健康检查
- minimax-coordinator: Mac Mini ↔ Railway 协调
- research-agent: GP/RWA 深度研究

输入任务后：
1. 分析任务类型
2. 选择最合适的 subagent
3. 输出路由决定（不执行）
"""

    def route(self, task: str) -> str:
        """Route task to appropriate agent."""
        task_lower = task.lower()

        # Scheduled data agents (Phase G) — highest priority for data tasks
        if "market" in task_lower or "whale" in task_lower or "orderbook" in task_lower or "stablecoin" in task_lower:
            return "market-signal"
        elif "cis" in task_lower or "score" in task_lower:
            return "cis-scorer"
        elif "macro" in task_lower or "regime" in task_lower or "fng" in task_lower or "vix" in task_lower:
            return "macro-pulse"
        elif "gp" in task_lower or "fund" in task_lower or "monitor" in task_lower:
            return "gp-monitor"
        elif "report" in task_lower or "brief" in task_lower:
            return "report-generator"
        # HARNESS orchestration agents
        elif "compliance" in task_lower or "audit" in task_lower or "buy" in task_lower or "sell" in task_lower:
            return "compliance-auditor"
        elif "validate" in task_lower or "validation" in task_lower:
            return "cis-validator"
        elif "deploy" in task_lower or "railway" in task_lower or "verify" in task_lower:
            return "deploy-verifier"
        elif "minimax" in task_lower or "mac mini" in task_lower or "sync" in task_lower:
            return "minimax-coordinator"
        elif "research" in task_lower or "rwa" in task_lower:
            return "research-agent"
        else:
            return "research-agent"  # default

    def list_agents(self) -> list[str]:
        """List all available agents."""
        return list(self.agents.keys())

    def get_agent_info(self, name: str) -> Optional[dict]:
        """Get agent definition."""
        return get_agent(name)

    def execute(self, agent_name: str, input_data: Optional[dict] = None) -> dict:
        """
        Execute a task via the specified agent.

        Returns execution metadata (actual execution deferred to agent runtime).
        """
        agent = get_agent(agent_name)
        if not agent:
            return {"error": f"Unknown agent: {agent_name}", "available": self.list_agents()}

        return {
            "status": "routed",
            "agent": agent_name,
            "description": agent["description"],
            "tools": agent["tools"],
            "model": agent["model"],
            "input": input_data or {},
        }


def main():
    parser = argparse.ArgumentParser(description="CometCloud HARNESS Orchestrator")
    parser.add_argument("--list", action="store_true", help="List all available agents")
    parser.add_argument("--schedules", action="store_true", help="List all scheduled agents with cron times")
    parser.add_argument("--agent", type=str, help="Run specific agent")
    parser.add_argument("--input", type=str, help="JSON input for agent")
    parser.add_argument("--route", type=str, help="Route a task to appropriate agent")
    parser.add_argument("--test", action="store_true", help="Test orchestrator")
    args = parser.parse_args()

    orchestrator = HARNESSOrchestrator()

    if args.test:
        # Test routing
        test_tasks = [
            "scan for compliance violations in src/",
            "validate CIS scores for BTC",
            "verify Railway deployment",
            "research RWA tokenization",
            "collect whale flows",
            "update CIS scores",
            "macro regime check",
        ]
        print("HARNESS Orchestrator Test")
        print("=" * 50)
        for task in test_tasks:
            routed = orchestrator.route(task)
            print(f"  Task: {task}")
            print(f"  → Routed to: {routed}")
            print()
        print(f"Total agents: {len(orchestrator.list_agents())}")
        print(f"Agents: {', '.join(orchestrator.list_agents())}")
        return

    if args.list:
        print("Available Agents:")
        print("=" * 50)
        for name in orchestrator.list_agents():
            agent = orchestrator.get_agent_info(name)
            schedule = agent.get("schedule", "on-demand")
            sched_note = f" [{schedule}]" if schedule != "on-demand" else ""
            print(f"\n  {name} ({agent['model']}){sched_note}")
            print(f"    {agent['description']}")
            print(f"    tools: {', '.join(agent['tools'])}")
        return

    if args.schedules:
        print("Scheduled Agents (Phase G):")
        print("=" * 50)
        scheduled = [
            (name, agent)
            for name, agent in orchestrator.agents.items()
            if "schedule" in agent
        ]
        for name, agent in sorted(scheduled, key=lambda x: x[1]["schedule"]):
            print(f"  {agent['schedule']}  {name}")
            print(f"           {agent['description']}")
            print()
        return

    if args.route:
        routed = orchestrator.route(args.route)
        print(f"Task: {args.route}")
        print(f"→ Routed to: {routed}")
        return

    if args.agent:
        input_data = json.loads(args.input) if args.input else {}
        result = orchestrator.execute(args.agent, input_data)
        print(json.dumps(result, indent=2))
        return

    # Default: show help
    parser.print_help()
    print("\nExamples:")
    print("  python3 orchestrator.py --list")
    print("  python3 orchestrator.py --route 'scan for compliance violations'")
    print("  python3 orchestrator.py --agent compliance-auditor")
    print("  python3 orchestrator.py --test")


if __name__ == "__main__":
    main()