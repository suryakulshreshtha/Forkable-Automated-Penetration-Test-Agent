"""
FASTAPI read/write surface over the board.

The server exposes the graph for inspection and lets a human (or a networked
dispatcher on another host) create projects, read the graph, and - importantly -
inject Hints while a search is running. In local mode the dispatcher talks to the
store directly; the server is the observation deck and the hint channel.

Run with:  fapta serve   (see cli.py)
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .models import Fact, Intent
from .store import GraphStore


class NewProject(BaseModel):
    origin: str
    goal: str


class NewFact(BaseModel):
    content: str


class NewIntent(BaseModel):
    description: str


class NewHint(BaseModel):
    content: str


def create_app(db_path: str = "fapta.db") -> FastAPI:
    app = FastAPI(title="FAPTA", version="0.1.0")
    store = GraphStore(db_path)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/projects")
    def create_project(body: NewProject) -> dict:
        pid = store.create_project(body.origin, body.goal)
        return {"project_id": pid}

    @app.get("/projects")
    def list_projects() -> dict:
        return {"projects": store.list_projects()}

    @app.get("/projects/{project_id}/graph")
    def get_graph(project_id: str) -> dict:
        try:
            return store.get_graph(project_id).model_dump(mode="json")
        except KeyError:
            raise HTTPException(status_code=404, detail="unknown project")

    @app.post("/projects/{project_id}/facts")
    def add_fact(project_id: str, body: NewFact) -> dict:
        fact = store.add_fact(project_id, Fact(content=body.content, created_by="api"))
        return {"fact_id": fact.id}

    @app.post("/projects/{project_id}/intents")
    def add_intent(project_id: str, body: NewIntent) -> dict:
        intent = store.add_intent(
            project_id, Intent(description=body.description, created_by="api")
        )
        return {"intent_id": intent.id}

    @app.post("/projects/{project_id}/hints")
    def add_hint(project_id: str, body: NewHint) -> dict:
        """Inject human judgement; the next Reason task will absorb it."""
        hint = store.add_hint(project_id, body.content)
        return {"hint_id": hint.id}

    return app
