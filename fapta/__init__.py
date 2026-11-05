"""
FAPTA - Forkable-Auto-Penetration-Test-Agent.

A general-purpose, blackboard-architecture state-space search engine. Given an
origin and a goal, cooperative workers search for a path through an unknown state
space, coordinating only through a shared graph of Facts, Intents and Hints.

The engine is domain-neutral. Autonomous, *authorised* penetration testing is one
problem it fits - but so are CTF solving, puzzle search and general problem solving.
Nothing in this package contains exploit code; the domain is supplied by the
operator at runtime through the project's origin, goal and configured tools.
"""

from .config import Config
from .dispatcher import Dispatcher
from .models import Fact, Graph, Hint, Intent, IntentStatus, ProjectStatus, TaskType
from .store import GraphStore

__version__ = "0.1.0"

__all__ = [
    "Config",
    "Dispatcher",
    "GraphStore",
    "Graph",
    "Fact",
    "Intent",
    "Hint",
    "IntentStatus",
    "ProjectStatus",
    "TaskType",
    "__version__",
]
