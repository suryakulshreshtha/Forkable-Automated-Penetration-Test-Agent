"""Worker factory and the subprocess adapter (mocked, no real CLI needed)."""

from unittest import mock

from fapta.models import Graph, TaskType
from fapta.workers import MockWorker, build_worker
from fapta.workers.base import Task
from fapta.workers.subprocess_worker import ClaudeCodeWorker, CodexWorker


def test_factory_builds_known_types():
    assert isinstance(build_worker({"name": "m", "type": "mock"}), MockWorker)
    assert isinstance(build_worker({"name": "c", "type": "claudecode"}), ClaudeCodeWorker)
    assert isinstance(build_worker({"name": "x", "type": "codex"}), CodexWorker)


def test_factory_cli_requires_command():
    try:
        build_worker({"name": "bad", "type": "cli"})
    except ValueError as e:
        assert "command" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_factory_restricts_task_types():
    w = build_worker({"name": "e", "type": "mock", "task_types": ["explore"]})
    assert w.handles(TaskType.EXPLORE)
    assert not w.handles(TaskType.REASON)


def test_default_vendor_commands():
    assert ClaudeCodeWorker().command == ["claude", "-p"]
    assert CodexWorker().command == ["codex", "exec"]


def test_cli_worker_parses_subprocess_output():
    worker = ClaudeCodeWorker()
    fake = mock.Mock(returncode=0, stdout='{"new_facts": ["edge A->B"], "complete": false}', stderr="")
    task = Task(task_type=TaskType.REASON, graph=Graph(project_id="p", origin="A", goal="B"))
    with mock.patch("fapta.workers.subprocess_worker.subprocess.run", return_value=fake) as run:
        res = worker.run(task)
        # prompt was sent on stdin, not as an argv element
        _, kwargs = run.call_args
        assert kwargs["input"] is not None
    assert res.new_facts == ["edge A->B"]


def test_cli_worker_error_is_noop():
    worker = ClaudeCodeWorker()
    fake = mock.Mock(returncode=1, stdout="", stderr="not logged in")
    task = Task(task_type=TaskType.REASON, graph=Graph(project_id="p", origin="A", goal="B"))
    with mock.patch("fapta.workers.subprocess_worker.subprocess.run", return_value=fake):
        res = worker.run(task)
    assert res.new_facts == [] and res.complete is False
