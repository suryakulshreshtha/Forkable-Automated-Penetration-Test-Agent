"""Prompt construction and (tolerant) output parsing."""

from fapta.models import Graph, Intent, TaskType
from fapta.protocol import build_prompt, parse_result
from fapta.workers.base import Task


def _graph():
    return Graph(project_id="p", origin="START", goal="GOAL")


def test_prompt_contains_mission_and_contract():
    task = Task(task_type=TaskType.REASON, graph=_graph())
    prompt = build_prompt(task)
    assert "ORIGIN: START" in prompt
    assert "GOAL:   GOAL" in prompt
    assert "new_facts" in prompt and "new_intents" in prompt
    assert "REASON" in prompt


def test_explore_prompt_names_the_intent():
    g = _graph()
    intent = Intent(description="explore node B")
    task = Task(task_type=TaskType.EXPLORE, graph=g, intent=intent)
    prompt = build_prompt(task)
    assert "INTENT TO EXECUTE: explore node B" in prompt


def test_parse_plain_json():
    out = '{"new_facts": ["edge A->B"], "new_intents": ["explore node B"], "complete": false, "result": null}'
    res = parse_result(out)
    assert res.new_facts == ["edge A->B"]
    assert res.new_intents == ["explore node B"]
    assert res.complete is False and res.result is None


def test_parse_json_in_code_fence_with_prose():
    out = 'Sure! Here is my answer:\n```json\n{"new_facts": ["x"], "complete": true, "result": "done"}\n```\nHope that helps.'
    res = parse_result(out)
    assert res.new_facts == ["x"]
    assert res.complete is True and res.result == "done"


def test_parse_garbage_is_noop():
    res = parse_result("I could not do that.")
    assert res.new_facts == [] and res.new_intents == []
    assert res.complete is False
    assert res.raw == "I could not do that."
