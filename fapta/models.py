"""
Core domain models for FAPTA.

The engine is organised around a *blackboard*: a shared, append-mostly graph that
every worker reads from and writes to. Three primitives are enough to describe any
directed search through an unknown state space:

    Fact   - a confirmed, objective observation written to the board.
    Intent - a declared direction of exploration that has not been executed yet.
    Hint   - human judgement injected at any time, consumed by workers on next read.

A project pins the search between two points:

    origin - the known starting state ("where we are").
    goal   - the success condition ("what 'solved' looks like").

The path between origin and goal is unknown; the engine discovers it by letting
workers turn Intents into Facts until the goal is satisfied.

Nothing in this module is domain-specific. The same types describe a maze search,
a CTF challenge, or an authorised security engagement - the domain lives entirely
in the text of the origin, goal, facts and intents, never in the schema.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class IntentStatus(str, enum.Enum):
    """Lifecycle of an Intent as it moves across the board."""

    OPEN = "open"            # declared, not yet claimed by any worker
    CLAIMED = "claimed"      # a worker has taken ownership and is executing it
    DONE = "done"            # execution finished, findings written back as Facts
    ABANDONED = "abandoned"  # execution gave up or was judged a dead end


class TaskType(str, enum.Enum):
    """The three kinds of unit-of-work a worker can be asked to perform."""

    BOOTSTRAP = "bootstrap"  # first contact: attempt the whole problem directly
    REASON = "reason"        # read the whole graph, decide if solved / what's next
    EXPLORE = "explore"      # claim one Intent, execute it, report one Fact


class Fact(BaseModel):
    """A confirmed observation. Facts are the stepping stones from origin to goal."""

    id: str = Field(default_factory=lambda: _new_id("fact"))
    content: str
    source_intent_id: str | None = None   # the Intent whose execution produced this
    created_by: str | None = None         # name of the worker that wrote it
    created_at: datetime = Field(default_factory=_now)
    metadata: dict = Field(default_factory=dict)


class Intent(BaseModel):
    """A declared, not-yet-executed direction of exploration."""

    id: str = Field(default_factory=lambda: _new_id("intent"))
    description: str
    status: IntentStatus = IntentStatus.OPEN
    created_by: str | None = None
    claimed_by: str | None = None
    parent_fact_id: str | None = None     # the Fact that motivated this Intent
    created_at: datetime = Field(default_factory=_now)
    metadata: dict = Field(default_factory=dict)


class Hint(BaseModel):
    """Human judgement injected onto the board; absorbed by the next Reason task."""

    id: str = Field(default_factory=lambda: _new_id("hint"))
    content: str
    created_at: datetime = Field(default_factory=_now)
    consumed: bool = False


class ProjectStatus(str, enum.Enum):
    ACTIVE = "active"
    COMPLETE = "complete"
    STOPPED = "stopped"      # halted by a human or by hitting a run limit


class Graph(BaseModel):
    """
    A consistent snapshot of one project's board.

    This is the single object a worker is handed. It contains everything the worker
    is allowed to know: the mission (origin, goal), everything confirmed so far
    (facts), every open direction (intents) and any unconsumed human hints.
    """

    project_id: str
    origin: str
    goal: str
    status: ProjectStatus = ProjectStatus.ACTIVE
    facts: list[Fact] = Field(default_factory=list)
    intents: list[Intent] = Field(default_factory=list)
    hints: list[Hint] = Field(default_factory=list)
    result: str | None = None            # filled when the goal is reached
    iteration: int = 0                   # how many dispatcher cycles have run

    def open_intents(self) -> list[Intent]:
        return [i for i in self.intents if i.status == IntentStatus.OPEN]

    def unconsumed_hints(self) -> list[Hint]:
        return [h for h in self.hints if not h.consumed]

    def bootstrapped(self) -> bool:
        """True once anything has been written to the board (facts or intents).

        Bootstrap is 'first contact', so it should run only while the board is
        completely empty. A bootstrap that surfaces just intents (and no facts yet)
        still counts as having happened.
        """
        return bool(self.facts) or bool(self.intents)
