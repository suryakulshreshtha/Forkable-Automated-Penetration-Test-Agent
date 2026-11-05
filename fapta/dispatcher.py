"""
The dispatcher: the engine's scheduler and sole writer to the board.

Each cycle (`step`) for one project does:

    1. If the project has never been touched -> run a BOOTSTRAP task.
    2. Otherwise:
         a. run a REASON task over the whole graph. If it declares the goal met,
            record the result and stop the project.
         b. otherwise claim up to `worker_max_running` OPEN intents and run an
            EXPLORE task for each, writing their findings back as Facts (and any
            follow-on Intents they surface).

Workers coordinate only through the board (stigmergy): the dispatcher claims each
Intent atomically in the store, so two workers never execute the same one. The
dispatcher is the only component that writes results back, which keeps the protocol
single-writer and the graph consistent.

This file contains no domain logic. It would schedule a maze search, a CTF solve, or
an authorised security engagement identically - the difference lives entirely in the
project's origin/goal and in which worker backend is configured.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from .config import RuntimeSettings
from .models import Fact, Intent, IntentStatus, ProjectStatus, TaskType
from .store import GraphStore
from .workers.base import Task, Worker

# A progress callback receives short human-readable event strings.
Logger = Callable[[str], None]


def _noop_logger(_: str) -> None:
    pass


class Dispatcher:
    def __init__(
        self,
        store: GraphStore,
        workers: list[Worker],
        settings: RuntimeSettings | None = None,
        logger: Logger | None = None,
    ):
        self.store = store
        self.workers = sorted(workers, key=lambda w: getattr(w, "priority", 0))
        self.settings = settings or RuntimeSettings()
        self.log = logger or _noop_logger

    # -- worker selection ----------------------------------------------------

    def _worker_for(self, task_type: TaskType) -> Worker | None:
        for w in self.workers:
            if w.handles(task_type):
                return w
        return None

    # -- writing results back ------------------------------------------------

    def _existing_intent_descriptions(self, project_id: str) -> set[str]:
        g = self.store.get_graph(project_id)
        return {" ".join(i.description.split()) for i in g.intents}

    def _write_result(
        self,
        project_id: str,
        result,
        worker_name: str,
        source_intent_id: str | None = None,
    ) -> None:
        for content in result.new_facts:
            self.store.add_fact(
                project_id,
                Fact(
                    content=content,
                    source_intent_id=source_intent_id,
                    created_by=worker_name,
                ),
            )
        # Dedup intents against everything already on the board so the search
        # cannot loop on a direction it has already taken.
        existing = self._existing_intent_descriptions(project_id)
        for desc in result.new_intents:
            norm = " ".join(desc.split())
            if norm in existing:
                continue
            existing.add(norm)
            self.store.add_intent(
                project_id,
                Intent(description=desc, created_by=worker_name),
            )

    # -- one cycle for one project ------------------------------------------

    def step(self, project_id: str) -> dict:
        g = self.store.get_graph(project_id)
        if g.status != ProjectStatus.ACTIVE:
            return {"status": g.status.value, "did": "nothing"}

        iteration = self.store.bump_iteration(project_id)
        if iteration > self.settings.max_iterations:
            self.store.set_status(project_id, ProjectStatus.STOPPED)
            self.log(f"[{project_id}] stopped: hit max_iterations")
            return {"status": "stopped", "did": "max_iterations"}

        # 1. Bootstrap on first contact.
        if not g.bootstrapped():
            worker = self._worker_for(TaskType.BOOTSTRAP)
            if worker is None:
                self.log(f"[{project_id}] no bootstrap-capable worker")
                return {"did": "skip-bootstrap"}
            self.log(f"[{project_id}] bootstrap via {worker.name}")
            res = worker.run(Task(task_type=TaskType.BOOTSTRAP, graph=g))
            self._write_result(project_id, res, worker.name)
            if res.complete and res.result:
                self.store.set_result(project_id, res.result)
                self.log(f"[{project_id}] COMPLETE: {res.result}")
                return {"did": "bootstrap", "complete": True}
            return {"did": "bootstrap", "complete": False}

        # 2a. Reason over the whole graph.
        reasoner = self._worker_for(TaskType.REASON)
        if reasoner is not None:
            self.store.consume_hints(project_id)      # fold human hints in
            g = self.store.get_graph(project_id)
            self.log(f"[{project_id}] reason via {reasoner.name}")
            res = reasoner.run(Task(task_type=TaskType.REASON, graph=g))
            if res.complete and res.result:
                self.store.set_result(project_id, res.result)
                self.log(f"[{project_id}] COMPLETE: {res.result}")
                return {"did": "reason", "complete": True}
            self._write_result(project_id, res, reasoner.name)

        # 2b. Explore open intents up to the concurrency cap.
        explorer = self._worker_for(TaskType.EXPLORE)
        if explorer is None:
            return {"did": "reason-only", "complete": False}

        g = self.store.get_graph(project_id)
        open_intents = g.open_intents()
        explored = 0
        for intent in open_intents:
            if explored >= self.settings.worker_max_running:
                break
            if not self.store.claim_intent(project_id, intent.id, explorer.name):
                continue  # someone else took it
            self.log(f"[{project_id}] explore '{intent.description}' via {explorer.name}")
            g_now = self.store.get_graph(project_id)
            res = explorer.run(
                Task(task_type=TaskType.EXPLORE, graph=g_now, intent=intent)
            )
            self._write_result(project_id, res, explorer.name, source_intent_id=intent.id)
            self.store.finish_intent(intent.id, IntentStatus.DONE)
            explored += 1
            if res.complete and res.result:
                self.store.set_result(project_id, res.result)
                self.log(f"[{project_id}] COMPLETE: {res.result}")
                return {"did": "explore", "complete": True, "explored": explored}

        return {"did": "explore", "complete": False, "explored": explored}

    # -- driving to completion ----------------------------------------------

    def run_project(self, project_id: str) -> str:
        """Run cycles until the project completes or stops. Returns final status."""
        while True:
            g = self.store.get_graph(project_id)
            if g.status != ProjectStatus.ACTIVE:
                return g.status.value
            self.step(project_id)
            if self.settings.interval:
                time.sleep(self.settings.interval)

    def run(self, project_ids: list[str] | None = None) -> None:
        """Run all active projects to completion (single pass over the set)."""
        if project_ids is None:
            project_ids = self.store.list_projects(ProjectStatus.ACTIVE)
        for pid in project_ids:
            status = self.run_project(pid)
            self.log(f"[{pid}] finished with status={status}")

    # -- startup checks ------------------------------------------------------

    def preflight(self) -> list[tuple[str, bool, str]]:
        """Verify each worker is runnable. CLI workers check their binary is on PATH."""
        results: list[tuple[str, bool, str]] = []
        for w in self.workers:
            check = getattr(w, "preflight", None)
            if callable(check):
                ok, msg = check()
            else:
                ok, msg = True, "ready"
            results.append((w.name, ok, msg))
        return results
