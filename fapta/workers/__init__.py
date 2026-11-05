"""Worker registry and factory."""

from __future__ import annotations

from ..models import TaskType
from .base import Task, Worker, WorkerResult
from .mock import MockWorker
from .subprocess_worker import CliWorker, ClaudeCodeWorker, CodexWorker

__all__ = [
    "Task",
    "Worker",
    "WorkerResult",
    "MockWorker",
    "CliWorker",
    "ClaudeCodeWorker",
    "CodexWorker",
    "build_worker",
]

_TASK_TYPE_LOOKUP = {t.value: t for t in TaskType}


def build_worker(spec: dict) -> Worker:
    """
    Construct a worker from a config dict.

    Recognised types: 'mock', 'claudecode', 'codex', 'cli'.
    'cli' is the escape hatch for any other local agent CLI; it requires a
    'command' argv list and never assumes a vendor.
    """
    wtype = spec.get("type", "mock")
    name = spec.get("name", wtype)
    timeout = int(spec.get("timeout", 600))
    cwd = spec.get("cwd")

    if wtype == "mock":
        worker: Worker = MockWorker(name=name)
    elif wtype == "claudecode":
        worker = ClaudeCodeWorker(name=name, timeout=timeout, cwd=cwd)
    elif wtype == "codex":
        worker = CodexWorker(name=name, timeout=timeout, cwd=cwd)
    elif wtype == "cli":
        command = spec.get("command")
        if not command:
            raise ValueError(f"worker {name!r} of type 'cli' requires a 'command' list")
        worker = CliWorker(name=name, command=list(command), timeout=timeout, cwd=cwd)
    else:
        raise ValueError(f"unknown worker type {wtype!r} for worker {name!r}")

    # Optionally narrow which task types this worker will accept.
    task_types = spec.get("task_types")
    if task_types:
        worker.supported = tuple(_TASK_TYPE_LOOKUP[t] for t in task_types)
    return worker
