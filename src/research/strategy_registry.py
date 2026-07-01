"""
Plugin registry for framework-aware strategies.

Each strategy registers itself with `@register_strategy(name, ...)`.
The CLI orchestrator (`scripts/run_research.py`) and walk-forward runner
discover strategies via `iter_strategies()` — never via hard-coded imports.

Convention:
    Strategy files live in `src/research/strategies/` or in the project root
    (e.g., `/tmp/nautilus_ls_v4.py` during experimentation).

    When adding a new strategy, prefer placing it in `src/research/strategies/`
    and importing it from `src/research/__init__.py` so the registry picks it
    up automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Type


@dataclass(frozen=True)
class StrategyMeta:
    """Metadata for one registered strategy."""
    name: str
    cls: type
    description: str = ""
    version: str = "0.1.0"
    required_timeframes: tuple[str, ...] = ("4h",)
    required_history_bars: int = 60
    can_short: bool = True
    paper_trading_ready: bool = False


_REGISTRY: dict[str, StrategyMeta] = {}


def register_strategy(
    name: str,
    description: str = "",
    version: str = "0.1.0",
    required_timeframes: tuple[str, ...] = ("4h",),
    required_history_bars: int = 60,
    can_short: bool = True,
    paper_trading_ready: bool = False,
):
    """Class decorator to register a research strategy.

    Usage:
        @register_strategy(
            name="ls_v4",
            description="LS-V4 port to Nautilus — 4h long-short",
            required_timeframes=("4h",),
            required_history_bars=60,
        )
        class LSv4Strategy(Strategy):
            ...
    """
    def deco(cls: type) -> type:
        if name in _REGISTRY:
            raise ValueError(f"strategy name {name!r} already registered")
        _REGISTRY[name] = StrategyMeta(
            name=name,
            cls=cls,
            description=description,
            version=version,
            required_timeframes=required_timeframes,
            required_history_bars=required_history_bars,
            can_short=can_short,
            paper_trading_ready=paper_trading_ready,
        )
        return cls

    return deco


def get_strategy(name: str) -> StrategyMeta:
    if name not in _REGISTRY:
        raise KeyError(f"unknown strategy {name!r}; known: {list_strategies()}")
    return _REGISTRY[name]


def list_strategies() -> list[str]:
    return sorted(_REGISTRY.keys())


def iter_strategies() -> Iterator[StrategyMeta]:
    for name in sorted(_REGISTRY.keys()):
        yield _REGISTRY[name]


def is_registered(name: str) -> bool:
    return name in _REGISTRY


# ── Smoke ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    @register_strategy("example", description="Demo strategy", version="0.0.1")
    class ExampleStrategy:  # noqa: F841
        pass

    print("Registered strategies:")
    for s in iter_strategies():
        print(f"  {s.name} v{s.version}: {s.description}")
