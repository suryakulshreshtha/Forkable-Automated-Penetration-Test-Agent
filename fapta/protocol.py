"""
The protocol: how a Task becomes a prompt, and how a backend's reply becomes a
WorkerResult.

This is deliberately the *only* place that knows the wire format between the engine
and a language-model backend. Keeping it in one module means a new backend only has
to shell out to its CLI - prompt construction and parsing are shared.

The prompt is domain-neutral. It describes the blackboard, the mission (origin and
goal), the current graph, and asks for a strict JSON reply. The engine never embeds
domain tactics; the domain is carried entirely by the project's origin, goal, facts
and hints, which the operator supplies at runtime.
"""

from __future__ import annotations

import json
import re

from .models import IntentStatus, TaskType
from .workers.base import Task, WorkerResult

SYSTEM_PREAMBLE = """\
You are a worker in a cooperative search engine. Several workers share one board
(a graph of Facts, Intents and Hints) and coordinate only by reading and writing it.

Definitions:
- Fact:   a confirmed, objective observation. Only write facts you have verified.
- Intent: a concrete, not-yet-executed next direction to explore.
- Hint:   guidance from a human operator. Treat hints as high priority.
- Goal:   the success condition. The search is done when the goal is satisfied.

You run an OODA loop: Observe the whole board, Orient to where you are relative to
the goal, Decide the next step(s), and Act. Report only through the JSON contract.
"""

# What each task type asks the worker to do.
_TASK_INSTRUCTIONS = {
    TaskType.BOOTSTRAP: (
        "This is the first contact with the problem. Attempt to reach the goal "
        "directly in one shot if it is trivially possible. Whatever happens, write "
        "down what you observed as facts, and propose concrete intents for the most "
        "promising next directions."
    ),
    TaskType.REASON: (
        "Read the entire board. First decide: is the goal already satisfied by the "
        "known facts? If yes, set \"complete\": true and put the solution/path in "
        "\"result\". If no, propose new intents for the unexplored frontier. Do not "
        "repeat intents that are already open. Returning no new intents is allowed."
    ),
    TaskType.EXPLORE: (
        "Execute the single intent named below. Do only what that intent describes. "
        "Report what you found as one or more facts. If execution reveals new "
        "promising directions, you may also propose intents for them."
    ),
}

_JSON_CONTRACT = """\
Reply with ONE JSON object and nothing else, using exactly this shape:

{
  "new_facts":   ["<each confirmed observation as a short string>"],
  "new_intents": ["<each next direction as a short imperative string>"],
  "complete":    false,
  "result":      null
}

Rules:
- "complete" is true ONLY when the goal is satisfied; then "result" must describe
  the solution (for a path search, the full path).
- Use [] for empty lists. Do not add commentary outside the JSON object.
"""


def _render_graph(task: Task) -> str:
    g = task.graph
    lines: list[str] = []
    lines.append(f"ORIGIN: {g.origin}")
    lines.append(f"GOAL:   {g.goal}")
    lines.append("")
    lines.append(f"FACTS ({len(g.facts)}):")
    if g.facts:
        for f in g.facts:
            lines.append(f"  - {f.content}")
    else:
        lines.append("  (none yet)")
    lines.append("")
    open_intents = [i for i in g.intents if i.status == IntentStatus.OPEN]
    lines.append(f"OPEN INTENTS ({len(open_intents)}):")
    if open_intents:
        for i in open_intents:
            lines.append(f"  - {i.description}")
    else:
        lines.append("  (none)")
    hints = g.unconsumed_hints()
    if hints:
        lines.append("")
        lines.append(f"HUMAN HINTS ({len(hints)}):")
        for h in hints:
            lines.append(f"  * {h.content}")
    return "\n".join(lines)


def build_prompt(task: Task) -> str:
    """Render a task into a full prompt string for a language-model backend."""
    parts = [SYSTEM_PREAMBLE, "", "CURRENT BOARD:", _render_graph(task), ""]
    parts.append(f"TASK: {task.task_type.value.upper()}")
    parts.append(_TASK_INSTRUCTIONS[task.task_type])
    if task.task_type == TaskType.EXPLORE and task.intent is not None:
        parts.append("")
        parts.append(f"INTENT TO EXECUTE: {task.intent.description}")
    parts.append("")
    parts.append(_JSON_CONTRACT)
    return "\n".join(parts)


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def parse_result(text: str) -> WorkerResult:
    """
    Extract the JSON object from a backend reply and coerce it into a WorkerResult.

    Backends are chatty and may wrap JSON in prose or code fences, so we locate the
    outermost brace span rather than trusting the whole string to be clean JSON.
    """
    raw = text
    candidate = text.strip()

    # strip a ```json ... ``` fence if present
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.DOTALL)
    if fence:
        candidate = fence.group(1)
    else:
        m = _JSON_BLOCK.search(candidate)
        if m:
            candidate = m.group(0)

    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        # Unparseable reply: surface nothing rather than guessing. The dispatcher
        # will treat this as a no-op and the task can be retried.
        return WorkerResult(raw=raw)

    def _as_str_list(value) -> list[str]:
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    return WorkerResult(
        new_facts=_as_str_list(data.get("new_facts")),
        new_intents=_as_str_list(data.get("new_intents")),
        complete=bool(data.get("complete", False)),
        result=(str(data["result"]) if data.get("result") not in (None, "") else None),
        raw=raw,
    )
