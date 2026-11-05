"""
MockWorker - a deterministic, fully offline backend.

It exists for two reasons:
  1. It lets the entire engine be tested and demonstrated with no language-model
     backend, no API keys and no network.
  2. It is a faithful illustration of the engine's thesis: a *directed search
     through an unknown state space*.

The "unknown state space" here is a hidden directed graph (a maze). The engine does
NOT know the maze. The MockWorker does - it plays the role of "the environment" and
answers exploration honestly, one node at a time. The engine discovers the maze only
through the Facts the worker writes, and the goal is reached when the known facts
prove a path from origin to goal exists.

Swap this maze for an LLM backend pointed at a real problem and nothing else in the
engine changes - that is the entire point of the Worker abstraction.
"""

from __future__ import annotations

from ..models import TaskType
from .base import Task, Worker, WorkerResult

# A small hidden maze used by `fapta demo` and the test-suite. Directed edges.
# The engine never sees this dict; it only ever sees facts the worker emits.
SAMPLE_MAZE: dict[str, list[str]] = {
    "START": ["A", "B"],
    "A": ["C"],
    "B": ["C", "D"],
    "C": ["E"],
    "D": ["DEADEND"],
    "E": ["GOAL"],
    "DEADEND": [],
    "GOAL": [],
}


def _edge_fact(a: str, b: str) -> str:
    return f"edge {a}->{b}"


def _parse_edges(fact_contents: list[str]) -> dict[str, list[str]]:
    """Rebuild the discovered adjacency from edge facts the board holds."""
    adj: dict[str, list[str]] = {}
    for content in fact_contents:
        c = content.strip()
        if not c.startswith("edge "):
            continue
        body = c[len("edge "):]
        if "->" not in body:
            continue
        a, b = (part.strip() for part in body.split("->", 1))
        adj.setdefault(a, [])
        if b not in adj[a]:
            adj[a].append(b)
    return adj


def _explored_nodes(fact_contents: list[str]) -> set[str]:
    """A node is 'explored' once it has produced an edge fact or a deadend fact."""
    explored: set[str] = set()
    for content in fact_contents:
        c = content.strip()
        if c.startswith("edge "):
            body = c[len("edge "):]
            if "->" in body:
                explored.add(body.split("->", 1)[0].strip())
        elif c.startswith("deadend "):
            explored.add(c[len("deadend "):].strip())
    return explored


def _node_from_intent(description: str) -> str | None:
    """Extract a node name from an 'explore node X' style intent."""
    tokens = description.strip().split()
    if "node" in tokens:
        idx = tokens.index("node")
        if idx + 1 < len(tokens):
            return tokens[idx + 1]
    # fall back to the last token
    return tokens[-1] if tokens else None


def _bfs(adj: dict[str, list[str]], start: str, goal: str) -> list[str] | None:
    """Shortest path over the *known* adjacency, or None if goal not yet reachable."""
    from collections import deque

    queue: deque[list[str]] = deque([[start]])
    seen = {start}
    while queue:
        path = queue.popleft()
        node = path[-1]
        if node == goal:
            return path
        for nxt in adj.get(node, []):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(path + [nxt])
    return None


class MockWorker(Worker):
    """Deterministic worker backed by a hidden maze."""

    def __init__(self, name: str = "mock", environment: dict[str, list[str]] | None = None):
        super().__init__(name)
        self.env = environment if environment is not None else dict(SAMPLE_MAZE)

    # -- the environment oracle (what a real worker's tools would do) --------

    def _reveal(self, node: str) -> list[str]:
        return list(self.env.get(node, []))

    # -- Worker API ----------------------------------------------------------

    def run(self, task: Task) -> WorkerResult:
        if task.task_type == TaskType.BOOTSTRAP:
            return self._bootstrap(task)
        if task.task_type == TaskType.EXPLORE:
            return self._explore(task)
        if task.task_type == TaskType.REASON:
            return self._reason(task)
        return WorkerResult()

    def _bootstrap(self, task: Task) -> WorkerResult:
        origin = task.graph.origin.strip()
        goal = task.graph.goal.strip()
        neighbors = self._reveal(origin)
        facts = [_edge_fact(origin, n) for n in neighbors]
        if not neighbors:
            facts.append(f"deadend {origin}")
        intents = [f"explore node {n}" for n in neighbors if n != goal]
        return WorkerResult(new_facts=facts, new_intents=intents)

    def _explore(self, task: Task) -> WorkerResult:
        goal = task.graph.goal.strip()
        node = _node_from_intent(task.intent.description) if task.intent else None
        if not node:
            return WorkerResult()
        neighbors = self._reveal(node)
        if not neighbors:
            return WorkerResult(new_facts=[f"deadend {node}"])

        facts = [_edge_fact(node, n) for n in neighbors]

        known_explored = _explored_nodes([f.content for f in task.graph.facts])
        open_targets = {
            _node_from_intent(i.description)
            for i in task.graph.open_intents()
        }
        intents = [
            f"explore node {n}"
            for n in neighbors
            if n != goal and n not in known_explored and n not in open_targets
        ]
        return WorkerResult(new_facts=facts, new_intents=intents)

    def _reason(self, task: Task) -> WorkerResult:
        origin = task.graph.origin.strip()
        goal = task.graph.goal.strip()
        contents = [f.content for f in task.graph.facts]
        adj = _parse_edges(contents)

        path = _bfs(adj, origin, goal)
        if path is not None:
            return WorkerResult(
                complete=True,
                result="path: " + " -> ".join(path),
            )

        # Not solved yet: propose exploration of any known-but-unexplored frontier
        # node that has no open intent. This is what keeps the search moving.
        explored = _explored_nodes(contents)
        known_nodes: set[str] = set(adj.keys())
        for targets in adj.values():
            known_nodes.update(targets)
        open_targets = {
            _node_from_intent(i.description) for i in task.graph.open_intents()
        }
        frontier = [
            n
            for n in sorted(known_nodes)
            if n not in explored and n != goal and n not in open_targets
        ]
        intents = [f"explore node {n}" for n in frontier]
        return WorkerResult(new_intents=intents)
