"""
The offline demo, wired up end to end.

It builds an in-memory board, points a MockWorker at a hidden maze, and lets the
dispatcher drive the search from origin ("START") to goal ("GOAL"). Everything runs
locally with no network and no API keys. The printed trace shows the blackboard
filling up with Facts and the Reason task declaring victory once a path is proven.
"""

from __future__ import annotations

from .config import RuntimeSettings
from .dispatcher import Dispatcher
from .models import ProjectStatus
from .store import GraphStore
from .workers.mock import MockWorker


def run_demo() -> str:
    print("=" * 64)
    print("FAPTA offline demo - directed search through an unknown maze")
    print("=" * 64)

    store = GraphStore(":memory:")
    pid = store.create_project(origin="START", goal="GOAL")
    print(f"project: {pid}")
    print("origin=START  goal=GOAL  (the engine does NOT know the maze)\n")

    workers = [MockWorker(name="mock")]
    settings = RuntimeSettings(worker_max_running=2, interval=0.0, max_iterations=50)
    disp = Dispatcher(store, workers, settings, logger=lambda m: print("  " + m))

    disp.run_project(pid)

    g = store.get_graph(pid)
    print("\n" + "-" * 64)
    print(f"final status : {g.status.value}")
    print(f"result       : {g.result}")
    print(f"facts learned: {len(g.facts)}")
    for f in g.facts:
        print(f"   - {f.content}")
    print("-" * 64)

    assert g.status == ProjectStatus.COMPLETE, "demo did not complete"
    assert g.result and "GOAL" in g.result, "demo did not reach GOAL"
    print("OK - goal reached.\n")
    return g.result or ""


if __name__ == "__main__":
    run_demo()
