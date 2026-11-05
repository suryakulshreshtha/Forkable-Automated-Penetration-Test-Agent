"""Store behaviour, including the atomic-claim race that underpins stigmergy."""

import threading

from fapta.models import Fact, Intent, IntentStatus, ProjectStatus
from fapta.store import GraphStore


def make_store():
    return GraphStore(":memory:")


def test_create_and_read_project():
    s = make_store()
    pid = s.create_project("o", "g")
    g = s.get_graph(pid)
    assert g.origin == "o" and g.goal == "g"
    assert g.status == ProjectStatus.ACTIVE
    assert g.facts == [] and g.intents == []


def test_add_fact_and_intent():
    s = make_store()
    pid = s.create_project("o", "g")
    s.add_fact(pid, Fact(content="edge A->B", created_by="w"))
    s.add_intent(pid, Intent(description="explore node B", created_by="w"))
    g = s.get_graph(pid)
    assert len(g.facts) == 1 and g.facts[0].content == "edge A->B"
    assert len(g.intents) == 1 and g.open_intents()[0].description == "explore node B"


def test_claim_intent_is_exclusive():
    s = make_store()
    pid = s.create_project("o", "g")
    i = s.add_intent(pid, Intent(description="explore node B"))
    assert s.claim_intent(pid, i.id, "w1") is True
    # a second claim on the same intent must fail
    assert s.claim_intent(pid, i.id, "w2") is False
    g = s.get_graph(pid)
    claimed = g.intents[0]
    assert claimed.status == IntentStatus.CLAIMED and claimed.claimed_by == "w1"


def test_concurrent_claims_single_winner():
    s = make_store()
    pid = s.create_project("o", "g")
    i = s.add_intent(pid, Intent(description="explore node B"))

    wins: list[bool] = []
    lock = threading.Lock()

    def worker(name: str):
        ok = s.claim_intent(pid, i.id, name)
        with lock:
            wins.append(ok)

    threads = [threading.Thread(target=worker, args=(f"w{n}",)) for n in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert wins.count(True) == 1  # exactly one worker may win the claim


def test_hints_consumed_once():
    s = make_store()
    pid = s.create_project("o", "g")
    s.add_hint(pid, "look east")
    first = s.consume_hints(pid)
    second = s.consume_hints(pid)
    assert len(first) == 1 and first[0].content == "look east"
    assert second == []


def test_result_marks_complete():
    s = make_store()
    pid = s.create_project("o", "g")
    s.set_result(pid, "path: START -> GOAL")
    g = s.get_graph(pid)
    assert g.status == ProjectStatus.COMPLETE
    assert g.result == "path: START -> GOAL"
