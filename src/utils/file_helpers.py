"""Small filesystem helpers: output dir creation, config loading."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG: dict[str, Any] = {
    "fuzzy_match_threshold": 0.72,
    "sparse_row_threshold": 0.9,   # a row with >=90% empty cells is treated as a separator
    "duplicate_key_fields": ["email", "id", "full_name"],  # first available field is used
    "enable_local_llm": False,
    "llm_model": "llama3.1",
}


def make_run_output_dir(base_output_dir: Path) -> Path:
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_dir = base_output_dir / f"{stamp}_run"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def load_config(config_path: Path | None) -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    if config_path and config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
        config.update(user_config)
    return config
