"""Repair engine — fixers that correct identified dataset issues (ADR-004).

Each fixer implements the Fixer Protocol (repair/protocol.py): dry_run()
returns a Diff describing what would change; apply() performs a copy-on-write
repair to an explicit output path.
"""

from miraxis.repair.episode_reindex import EpisodeReindexFixer
from miraxis.repair.orchestrator import FixerOutcome, FixPlan, run_apply, run_dry_run
from miraxis.repair.protocol import (
    BoundaryChange,
    Diff,
    Fixer,
    FrameChange,
    RepairSummary,
    StatChange,
)
from miraxis.repair.stats_recompute import StatsRecomputeFixer
from miraxis.repair.timestamp_dedrift import TimestampDedriftFixer

__all__ = [
    "BoundaryChange",
    "Diff",
    "EpisodeReindexFixer",
    "FixPlan",
    "Fixer",
    "FixerOutcome",
    "FrameChange",
    "RepairSummary",
    "StatChange",
    "StatsRecomputeFixer",
    "TimestampDedriftFixer",
    "run_apply",
    "run_dry_run",
]
