"""simharness: game-agnostic Monte Carlo simulation harness.

Owns the trial loop, seeding, event-loop wiring, result collection, statistics,
reporting, and parameter sweeps for any turn-based Monte Carlo game simulation.
Knows nothing about D&D or any other specific game system — see plugin.py for
the GameSystem protocol a game system implements to plug in.
"""

from __future__ import annotations

from .config import closed_vocab, deep_merge, get_path, load_toml, require_keys, set_path
from .ledger import Ledger
from .plugin import GameSystem, TrialContext
from .report import print_report, register_chart, register_section, save_charts
from .runner import TrialRunner
from .stats import ColumnComparison, CompareReport, Summary, bootstrap_ci, compare, summarize, summarize_all
from .sweep import comparison_chart, comparison_table, expand as sweep_expand, run as sweep_run

__all__ = [
    "closed_vocab",
    "deep_merge",
    "get_path",
    "load_toml",
    "require_keys",
    "set_path",
    "Ledger",
    "GameSystem",
    "TrialContext",
    "TrialRunner",
    "print_report",
    "register_chart",
    "register_section",
    "save_charts",
    "comparison_chart",
    "comparison_table",
    "sweep_expand",
    "sweep_run",
    "ColumnComparison",
    "CompareReport",
    "Summary",
    "bootstrap_ci",
    "compare",
    "summarize",
    "summarize_all",
]
