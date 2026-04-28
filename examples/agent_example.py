"""
CometCloud AI — Python Agent Example
REST API integration (no MCP client required)

Demonstrates: macro context → CIS universe → exclusion check → portfolio signal

pip install httpx rich
python agent_example.py
"""

import httpx
import json
from rich.console import Console
from rich.table import Table
from rich import print as rprint

BASE = "https://looloomi.ai/api/v1"
console = Console()


def get_macro_pulse() -> dict:
    """Step 1: Establish macro regime before any asset decisions."""
    r = httpx.get(f"{BASE}/market/macro-pulse", timeout=15)
    r.raise_for_status()
    return r.json()


def get_cis_universe(min_score: float = 0, limit: int = 20) -> list:
    """Step 2: Pull full CIS universe, filter by score threshold."""
    r = httpx.get(f"{BASE}/cis/universe", timeout=30)
    r.raise_for_status()
    data = r.json()
    assets = data.get("universe") or data.get("assets") or []
    scored = [a for a in assets if (a.get("cis_score") or a.get("score") or 0) >= min_score]
    scored.sort(key=lambda a: a.get("cis_score") or a.get("score") or 0, reverse=True)
    return scored[:limit]


def get_signal_feed() -> list:
    """Step 3: Compliance-safe positioning signals from 7 sources."""
    r = httpx.get(f"{BASE}/market/signals", timeout=15)
    r.raise_for_status()
    data = r.json()
    return data.get("signals") or []


def run_portfolio_task(min_cis: float = 52, limit: int = 10) -> dict:
    """Step 4: Delegate async portfolio analysis to A2A task queue."""
    r = httpx.post(
        f"{BASE}/agent/tasks",
        json={"type": "portfolio_analysis", "params": {"min_cis": min_cis, "limit": limit}},
        timeout=10,
    )
    r.raise_for_status()
    task = r.json()
    task_id = task["task_id"]

    import time
    for _ in range(10):
        time.sleep(1.5)
        poll = httpx.get(f"{BASE}/agent/tasks/{task_id}", timeout=10).json()
        if poll["status"] in ("completed", "failed"):
            return poll
    return {"status": "timeout", "task_id": task_id}


def main():
    console.rule("[bold cyan]CometCloud AI — Agent Session")

    # ── 1. Macro context ────────────────────────────────────────────────────────
    console.print("\n[bold]Step 1: Macro Pulse[/bold]")
    try:
        macro = get_macro_pulse()
        regime = macro.get("regime") or macro.get("macro_regime") or "Unknown"
        btc = macro.get("btc_price") or macro.get("btc_usd") or "—"
        fng = macro.get("fear_greed_value") or macro.get("fear_greed") or "—"
        dom = macro.get("btc_dominance") or "—"
        console.print(f"  Regime    : [bold yellow]{regime}[/bold yellow]")
        console.print(f"  BTC Price : ${btc:,.0f}" if isinstance(btc, (int, float)) else f"  BTC Price : {btc}")
        console.print(f"  Fear&Greed: {fng}")
        console.print(f"  BTC Dom   : {dom}%")
    except Exception as e:
        console.print(f"  [red]macro-pulse error: {e}[/red]")
        regime = "Unknown"

    # Regime-aware CIS threshold: Tightening = 52, Goldilocks = 65, else 58
    thresholds = {"TIGHTENING": 52, "GOLDILOCKS": 65, "RISK_ON": 60}
    threshold = thresholds.get(regime.upper(), 58)
    console.print(f"  → CIS threshold for [cyan]{regime}[/cyan] regime: [bold]{threshold}[/bold]")

    # ── 2. CIS Universe ─────────────────────────────────────────────────────────
    console.print("\n[bold]Step 2: CIS Universe (passing threshold)[/bold]")
    try:
        assets = get_cis_universe(min_score=threshold, limit=15)
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Symbol", style="cyan", width=8)
        table.add_column("CIS", justify="right", width=6)
        table.add_column("Grade", width=6)
        table.add_column("Signal", width=18)
        table.add_column("Class", width=10)
        table.add_column("Tier", width=5)

        for a in assets:
            score = a.get("cis_score") or a.get("score") or 0
            grade = a.get("grade") or "—"
            signal = a.get("signal") or "—"
            cls = a.get("asset_class") or "—"
            tier = a.get("data_tier") or ("T1" if a.get("source") == "local_engine" else "T2")
            color = "green" if score >= 65 else "yellow" if score >= 52 else "red"
            table.add_row(
                a.get("symbol") or a.get("asset_id") or "—",
                f"[{color}]{score:.1f}[/{color}]",
                grade,
                signal,
                cls,
                tier,
            )
        console.print(table)
        console.print(f"  {len(assets)} assets pass CIS ≥ {threshold} in {regime} regime")
    except Exception as e:
        console.print(f"  [red]universe error: {e}[/red]")
        assets = []

    # ── 3. Signal Feed ──────────────────────────────────────────────────────────
    console.print("\n[bold]Step 3: Signal Feed (top 3)[/bold]")
    try:
        signals = get_signal_feed()
        for s in signals[:3]:
            title = s.get("title") or s.get("signal_type") or "Signal"
            signal = s.get("signal") or s.get("positioning") or "—"
            assets_affected = ", ".join(s.get("affected_assets") or []) or "—"
            console.print(f"  [{signal}] {title} → {assets_affected}")
    except Exception as e:
        console.print(f"  [red]signal-feed error: {e}[/red]")

    # ── 4. A2A Task delegation ──────────────────────────────────────────────────
    console.print(f"\n[bold]Step 4: A2A Portfolio Analysis (CIS ≥ {threshold})[/bold]")
    try:
        result = run_portfolio_task(min_cis=threshold, limit=10)
        status = result.get("status")
        if status == "completed":
            out = result.get("result", {})
            holdings = out.get("portfolio") or out.get("assets") or []
            console.print(f"  Task status : [green]completed[/green]")
            console.print(f"  Holdings    : {len(holdings)} assets selected")
            if holdings:
                top = holdings[:3]
                console.print("  Top picks   : " + ", ".join(
                    f"{h.get('symbol','?')} ({h.get('weight',0):.1%})" for h in top
                ))
        else:
            console.print(f"  Task status : [yellow]{status}[/yellow]")
            if result.get("error"):
                console.print(f"  Error : {result['error']}")
    except Exception as e:
        console.print(f"  [red]A2A task error: {e}[/red]")

    console.rule("[bold cyan]Session Complete")
    console.print("\n[dim]Data is informational only. Not investment advice.")
    console.print("[dim]Signals use HK SFC-compliant positioning language: OUTPERFORM/NEUTRAL/UNDERPERFORM.\n")


if __name__ == "__main__":
    main()
