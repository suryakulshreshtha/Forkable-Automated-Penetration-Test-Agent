"""End-to-end search behaviour with the deterministic MockWorker."""

from fapta.config import RuntimeSettings
from fapta.dispatcher import Dispatcher
from fapta.models import ProjectStatus
from fapta.store import GraphStore
from fapta.workers.base import Task, Worker, WorkerResult
from fapta.workers.mock import MockWorker


def _engine(maze=None):
    store = GraphStore(":memory:")
    worker = MockWorker(name="mock", environment=maze) if maze else MockWorker(name="mock")
    settings = RuntimeSettings(worker_max_running=2, interval=0.0, max_iterations=50)
    disp = Dispatcher(store, [worker], settings)
    return store, disp


def test_demo_maze_reaches_goal():
    store, disp = _engine()
    pid = store.create_project("START", "GOAL")
    disp.run_project(pid)
    g = store.get_graph(pid)
    assert g.status == ProjectStatus.COMPLETE
    assert g.result is not None
    assert g.result.startswith("path: START")
    assert g.result.endswith("GOAL")


def test_custom_maze():
    maze = {"START": ["X"], "X": ["Y"], "Y": ["GOAL"], "GOAL": []}
    store, disp = _engine(maze)
    pid = store.create_project("START", "GOAL")
    disp.run_project(pid)
    g = store.get_graph(pid)
    assert g.status == ProjectStatus.COMPLETE
    assert "X -> Y -> GOAL" in g.result


def test_unsolvable_maze_stops_without_false_completion():
    # GOAL is unreachable from START: the search must stop, never claim success.
    maze = {"START": ["A"], "A": ["B"], "B": [], "GOAL": []}
    store, disp = _engine(maze)
    pid = store.create_project("START", "GOAL")
    disp.run_project(pid)
    g = store.get_graph(pid)
    assert g.status == ProjectStatus.STOPPED
    assert g.result is None


def test_bootstrap_only_once():
    store, disp = _engine()
    pid = store.create_project("START", "GOAL")
    first = disp.step(pid)
    assert first["did"] == "bootstrap"
    second = disp.step(pid)
    assert second["did"] != "bootstrap"  # never bootstraps twice


def test_hint_is_consumed_during_run():
    store, disp = _engine()
    pid = store.create_project("START", "GOAL")
    disp.step(pid)                      # bootstrap
    store.add_hint(pid, "prefer the B branch")
    disp.step(pid)                      # reason consumes the hint
    g = store.get_graph(pid)
    assert all(h.consumed for h in g.hints)


class _CountingWorker(Worker):
    """Verifies the dispatcher honours the per-cycle explore cap."""

    def __init__(self):
        super().__init__("counter")
        self.explores = 0

    def run(self, task: Task) -> WorkerResult:
        from fapta.models import TaskType
        if task.task_type == TaskType.BOOTSTRAP:
            return WorkerResult(new_intents=[f"explore node N{i}" for i in range(10)])
        if task.task_type == TaskType.EXPLORE:
            self.explores += 1
        return WorkerResult()


def test_explore_cap_per_cycle():
    store = GraphStore(":memory:")
    worker = _CountingWorker()
    settings = RuntimeSettings(worker_max_running=3, interval=0.0, max_iterations=50)
    disp = Dispatcher(store, [worker], settings)
    pid = store.create_project("START", "GOAL")
    disp.step(pid)                      # bootstrap -> 10 open intents
    before = worker.explores
    disp.step(pid)                      # one cycle: reason + up to 3 explores
    assert worker.explores - before == 3
