"""
Worker abstraction.

A Worker is a swappable executor. It receives a Task (one unit of work plus the
graph snapshot it is allowed to see) and returns a WorkerResult (what to write
back to the board). Workers never talk to each other and never touch the store
directly - they are pure "prompt in, structured findings out" functions. That is
what lets the same engine drive a deterministic mock, a hosted LLM CLI, or (later)
a fully local model, with no change to the dispatcher.

The OODA loop a worker runs is:

    Observe  - read the whole graph it was handed
    Orient   - locate the current state relative to origin and goal
    Decide   - choose the next intents / judge whether the goal is met
    Act       - execute (for an Explore task) and report findings as Facts
"""

from __future__ import annotations

import abc

from pydantic import BaseModel, Field

from ..models import Graph, Intent, TaskType


class Task(BaseModel):
    """One unit of work handed to a worker."""

    task_type: TaskType
    graph: Graph
    intent: Intent | None = None   # set only for EXPLORE tasks

    model_config = {"arbitrary_types_allowed": True}


class WorkerResult(BaseModel):
    """
    Structured output a worker returns. The dispatcher is the only thing that
    writes these back to the store, which keeps a single writer to the protocol.
    """

    new_facts: list[str] = Field(default_factory=list)
    new_intents: list[str] = Field(default_factory=list)
    complete: bool = False
    result: str | None = None     # a human-readable solution when complete is True
    raw: str | None = None        # raw backend output, kept for debugging


class Worker(abc.ABC):
    """Base class every backend implements."""

    #: task types this worker is willing to run
    supported: tuple[TaskType, ...] = (
        TaskType.BOOTSTRAP,
        TaskType.REASON,
        TaskType.EXPLORE,
    )

    def __init__(self, name: str):
        self.name = name

    def handles(self, task_type: TaskType) -> bool:
        return task_type in self.supported

    @abc.abstractmethod
    def run(self, task: Task) -> WorkerResult:
        """Execute one task and return structured findings."""
        raise NotImplementedError
