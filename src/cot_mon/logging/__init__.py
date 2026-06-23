"""Experiment tracking — every run logs to Weights & Biases (CLAUDE.md, SPEC_phase2 §1)."""

from cot_mon.logging.wandb_logger import (  # noqa: F401
    COT_TABLE_COLUMNS,
    DEFAULT_PROJECT,
    WandbRun,
    dataset_hash,
    git_info,
    run_config,
)
