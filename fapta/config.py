"""
Configuration loading.

Config is intentionally small and has two tiers:
  - a YAML file (static defaults, committed per-engagement), and
  - live settings the dispatcher can hot-read each cycle (concurrency, interval,
    iteration cap) so you can tune a run without restarting it.

No secrets are required here for local mode: each CLI backend uses its own host
login. Networked/container deployments add endpoints and keys, which belong in the
YAML and never in source.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class WorkerSpec(BaseModel):
    name: str
    type: str = "mock"                       # mock | claudecode | codex | cli
    task_types: list[str] | None = None      # restrict which tasks it accepts
    max_running: int = 1                     # per-worker concurrency cap
    priority: int = 0                        # lower is scheduled first
    command: list[str] | None = None         # required for type 'cli'
    timeout: int = 600
    cwd: str | None = None


class RuntimeSettings(BaseModel):
    execution: str = "local"                 # 'local' now; 'docker' is a later seam
    worker_max_running: int = 2              # global concurrent-task cap
    interval: float = 1.0                    # seconds between dispatcher cycles
    max_iterations: int = 100                # safety cap on cycles per project


class LocalSettings(BaseModel):
    workspace_root: str = "."                # per-project working dirs live here
    completed_action: str = "keep"           # keep | remove


class Config(BaseModel):
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    local: LocalSettings = Field(default_factory=LocalSettings)
    workers: list[WorkerSpec] = Field(default_factory=list)
    db_path: str = "fapta.db"

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        data = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(data)

    @classmethod
    def default_mock(cls) -> "Config":
        """A zero-dependency, fully offline config used by `fapta demo` and tests."""
        return cls(
            runtime=RuntimeSettings(worker_max_running=2, interval=0.0, max_iterations=50),
            workers=[
                WorkerSpec(
                    name="mock",
                    type="mock",
                    task_types=["bootstrap", "reason", "explore"],
                    max_running=2,
                )
            ],
            db_path=":memory:",
        )
