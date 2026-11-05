"""
Command-line entrypoint: `fapta <command>`.

Commands:
    serve       Run the FastAPI server (observation + hint channel).
    dispatch    Run the dispatcher against a config file.
    demo        Run the offline maze demo end-to-end with the MockWorker.
    new         Create a project (origin + goal) in the store.
    graph       Print a project's current graph.
"""

from __future__ import annotations

import sys

import click

from .config import Config
from .dispatcher import Dispatcher
from .models import ProjectStatus
from .store import GraphStore
from .workers import build_worker


@click.group()
def main() -> None:
    """FAPTA - a forkable state-space search engine."""


@main.command()
@click.option("--db", default="fapta.db", help="SQLite database path.")
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8000, type=int)
def serve(db: str, host: str, port: int) -> None:
    """Run the HTTP server."""
    import uvicorn

    from .server import create_app

    uvicorn.run(create_app(db), host=host, port=port)


@main.command()
@click.option("--config", "config_path", required=True, help="dispatch.yaml path.")
@click.option("--startup-healthcheck-only", is_flag=True,
              help="Run worker preflight checks and exit.")
def dispatch(config_path: str, startup_healthcheck_only: bool) -> None:
    """Run the dispatcher loop over all active projects."""
    cfg = Config.load(config_path)
    store = GraphStore(cfg.db_path)
    workers = [build_worker(ws.model_dump()) for ws in cfg.workers]
    disp = Dispatcher(store, workers, cfg.runtime, logger=click.echo)

    click.echo(f"runtime: execution={cfg.runtime.execution} "
               f"worker_max_running={cfg.runtime.worker_max_running}")
    all_ok = True
    for name, ok, msg in disp.preflight():
        click.echo(f"  preflight {name}: {'OK' if ok else 'FAIL'} - {msg}")
        all_ok = all_ok and ok
    if startup_healthcheck_only:
        sys.exit(0 if all_ok else 1)
    if not all_ok:
        click.echo("preflight failed; aborting.", err=True)
        sys.exit(1)

    disp.run()


@main.command()
@click.option("--db", default="fapta.db")
@click.option("--origin", required=True)
@click.option("--goal", required=True)
def new(db: str, origin: str, goal: str) -> None:
    """Create a new project."""
    store = GraphStore(db)
    pid = store.create_project(origin, goal)
    click.echo(pid)


@main.command()
@click.option("--db", default="fapta.db")
@click.argument("project_id")
def graph(db: str, project_id: str) -> None:
    """Print a project's graph."""
    store = GraphStore(db)
    g = store.get_graph(project_id)
    click.echo(f"project {g.project_id}  status={g.status.value}  iteration={g.iteration}")
    click.echo(f"origin: {g.origin}")
    click.echo(f"goal:   {g.goal}")
    if g.result:
        click.echo(f"result: {g.result}")
    click.echo(f"facts ({len(g.facts)}):")
    for f in g.facts:
        click.echo(f"  - {f.content}")
    click.echo(f"intents ({len(g.intents)}):")
    for i in g.intents:
        click.echo(f"  - [{i.status.value}] {i.description}")


@main.command()
def demo() -> None:
    """Run the offline maze demo (no network, no API keys)."""
    from .demo_runner import run_demo

    run_demo()


if __name__ == "__main__":
    main()
