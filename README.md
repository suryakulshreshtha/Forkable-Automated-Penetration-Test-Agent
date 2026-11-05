# Forkable Auto Penetration Test Agent FAPTA

### Forkable-Auto-Penetration-Test-Agent — a general-purpose state-space search engine

FAPTA is a **general-purpose problem-solving engine**. It defines no fixed roles and
no fixed workflow. You give it an **origin** (where you are) and a **goal** (what
"solved" means); it searches for a **path** through an unknown state space to get
from one to the other.

Autonomous, **authorised** penetration testing is one problem shaped exactly like
this — known starting point, defined success condition, unknown path — and it is the
problem the engine is named for. But the same engine solves CTF challenges, puzzle
searches, and other directed-search problems without changing a line of code. The
domain lives entirely in the mission you hand it and the tools you authorise, never
in the engine.

> **The engine ships with no exploits, payloads, or attack code.** It is an
> orchestration layer. Any security use is enabled by *you*, supplying your own
> authorised tooling and operating only against systems you own or have **explicit
> written permission** to test. See [Scope & responsible use](#scope--responsible-use).

---

## Table of contents

- [The core idea](#the-core-idea)
- [Key concepts (read this first)](#key-concepts-read-this-first)
  - [Blackboard architecture](#blackboard-architecture)
  - [Fact, Intent, Hint](#fact-intent-hint)
  - [The OODA loop](#the-ooda-loop)
  - [Stigmergy](#stigmergy)
  - [The three task types](#the-three-task-types)
- [System architecture](#system-architecture)
- [Worker backends](#worker-backends)
- [Getting started](#getting-started)
- [The offline demo, step by step](#the-offline-demo-step-by-step)
- [Configuration](#configuration)
- [Running your own mission](#running-your-own-mission)
- [Injecting human judgement (Hints)](#injecting-human-judgement-hints)
- [Scope & responsible use](#scope--responsible-use)
- [The air-gapped / offline path](#the-air-gapped--offline-path)
- [Supply-chain policy](#supply-chain-policy)
- [Technology stack](#technology-stack)
- [Project layout](#project-layout)
- [Testing](#testing)
- [Design decisions & FAQ](#design-decisions--faq)
- [License](#license)

---

## The core idea

A huge class of hard problems share one shape:

| | |
|---|---|
| **Origin** | known — a starting state you can describe |
| **Goal** | defined — you can tell when you've succeeded |
| **Path** | unknown — the sequence of steps in between is what you're searching for |

Penetration testing fits: origin = a target you're authorised to assess, goal =
a defined objective (e.g. reach a specific flag in a lab you own), path = the chain
of steps to get there. So does solving a maze, proving a theorem, or cracking a CTF.

FAPTA treats all of them as **directed search through a near-infinite state space**.
It grows a graph outward from `origin`, one confirmed step at a time, until the known
facts prove the `goal` is reachable.

---

## Key concepts (read this first)

### Blackboard architecture

A **blackboard** is a classic AI design pattern. Picture a group of specialists
around a shared chalkboard. Nobody gives orders. Each specialist watches the board,
and whenever they see something they can contribute to, they step up and write their
contribution. The solution emerges on the board from many small, independent
additions.

FAPTA's blackboard is a single shared **graph** per project. Every worker reads the
whole board, decides what it can add, and writes its finding back. There is no
central planner handing out jobs — work is *generated from the current state of the
board*, not from predefined job descriptions.

### Fact, Intent, Hint

The entire board is built from just three primitives:

| Primitive | What it is | Who writes it |
|-----------|------------|---------------|
| **Fact** | A confirmed, objective observation. A stepping stone. | Workers, once they've verified something. |
| **Intent** | A declared direction to explore that **hasn't been executed yet**. A step into the unknown. | Workers (and you) propose them. |
| **Hint** | Human judgement, injected at any time, absorbed by workers on their next read. | You, whenever you want to steer. |

That's the whole vocabulary. A maze search, a CTF solve, and an authorised security
engagement are all described with these same three words — only the *text* inside
them differs.

### The OODA loop

Each worker runs an **OODA loop** — a decision cycle borrowed from fast-moving
tactical settings:

- **Observe** — read the entire board (all facts, open intents, hints).
- **Orient** — work out where you are relative to origin and goal.
- **Decide** — pick the next intent(s), or judge whether the goal is already met.
- **Act** — execute, and write what you found back as new Facts.

Workers hold no state between turns. Everything they know comes from the board they
were just handed, which is what makes them trivially parallel and swappable.

### Stigmergy

**Stigmergy** is coordination *through the environment* rather than through direct
messaging — the way ants coordinate by leaving and following pheromone trails,
never talking to each other. FAPTA's workers never message one another and share no
private memory. They coordinate **only** by reading and writing the board. The one
rule that makes this safe under concurrency: an Intent can be **claimed by exactly
one worker** (an atomic operation in the store), so two workers never execute the
same step.

### The three task types

Every unit of work is one of three kinds, and the **same** worker can run any of
them:

| Task | What it does | Output |
|------|--------------|--------|
| **Bootstrap** | First contact. Attempt the problem directly; record what you see. | Facts + initial Intents |
| **Reason** | Read the whole board. Is the goal met? If not, what's the next frontier? | `complete` / new Intents / no-op |
| **Explore** | Claim one Intent, execute just that, report back. | One or more Facts |

The dispatcher decides which task to schedule next based purely on the board's
current state.

---

## System architecture

```
          +----------------------------------+
          |            FAPTA Server          |
          |     Facts + Intents + Hints      |   <- the blackboard (SQLite)
          +----------------+-----------------+
                           |
                     Read / Write
                           |
          +----------------+-----------------+
          |            Dispatcher            |
          |  Reads the graph, schedules      |   <- scheduler + SOLE writer-back
          |  Bootstrap/Reason/Explore tasks  |
          +--------+----------------+--------+
                   |                |
         +---------+------+   +-----+----------+
         |    Worker      |   |    Worker      |
         |  (OODA loop)   |   |  (OODA loop)   |   <- swappable executors:
         | prompt -> JSON |   | prompt -> JSON |      mock / Claude Code / Codex
         +----------------+   +----------------+
```

- **Server** — a thin REST surface over the board. It's your observation deck and
  the channel through which you inject Hints while a search runs. (`fapta serve`)
- **Dispatcher** — the engine's heart. It reads the graph, schedules tasks, runs
  workers up to a concurrency cap, and is the **only** component that writes results
  back, which keeps the board consistent. (`fapta dispatch`)
- **Workers** — pure "prompt in, structured findings out" executors. They add no
  capability of their own; all behaviour comes from the backend model and the tools
  you've authorised on the host.

In **local mode** (the default) the dispatcher talks to the store directly — one
process, no network, no Docker. A networked deployment can instead point multiple
dispatchers at a shared Server over HTTP.

---

## Worker backends

A worker is a *swappable executor*. Three ship in the box:

| Backend | Vendor | How it runs |
|---------|--------|-------------|
| `mock` | — | Deterministic, offline. Drives the demo and the tests. No network, no keys. |
| `claudecode` | Anthropic (US) | Shells out to the `claude` CLI in headless print mode. |
| `codex` | OpenAI (US) | Shells out to the `codex` CLI in `codex exec` mode. |
| `cli` | — | Escape hatch: bind **any** local agent CLI by giving its argv. |

Both LLM backends reuse the CLI's own host login, so **local mode needs no API keys
in config**. CLI flags drift, so the exact argv is configurable — see
[`dispatch.example.yaml`](dispatch.example.yaml).

---

## Getting started

**Prerequisites**

- macOS or Linux
- Python ≥ 3.12

**Install (from a source checkout)**

```bash
# with uv (recommended)
uv venv && uv pip install -e .

# or with plain pip
python3 -m venv .venv && . .venv/bin/activate && pip install -e .
```

**Prove it works — offline, no keys, no network:**

```bash
fapta demo
```

That runs the full engine against a hidden maze using the `mock` backend.

---

## The offline demo, step by step

The demo sets `origin = START`, `goal = GOAL`, and hands the engine a **hidden**
maze it cannot see. The engine has to *discover* the maze through Facts. Here is a
real run:

```
  bootstrap via mock                     # reveal START's neighbours
  reason via mock                        # no path yet -> keep going
  explore 'explore node A' via mock      # A -> C
  explore 'explore node B' via mock      # B -> C, B -> D
  reason via mock
  explore 'explore node C' via mock      # C -> E
  explore 'explore node D' via mock      # D -> DEADEND
  reason via mock
  explore 'explore node E' via mock      # E -> GOAL   <-- found it
  explore 'explore node DEADEND' via mock
  reason via mock
  COMPLETE: path: START -> A -> C -> E -> GOAL
```

What just happened, in terms of the concepts above:

1. **Bootstrap** revealed the origin's immediate neighbours and wrote them as Facts
   (`edge START->A`, `edge START->B`), then proposed **Intents** to explore each.
2. Each **Explore** claimed one Intent, revealed that node's neighbours, and wrote
   new edge Facts — surfacing fresh Intents for any newly discovered nodes.
3. **Reason** ran a breadth-first search over the **known** edges after each round.
   The moment the known Facts proved a path `START → … → GOAL`, it set `complete`
   and wrote the path as the result.

The engine never knew the maze up front. It built knowledge of it incrementally,
exactly as it would build knowledge of any unknown state space. Swap `mock` for a
real backend pointed at a real problem and **nothing else changes**.

---

## Configuration

Config has two tiers:

1. A **YAML file** (static defaults) — copy an example and edit:
   ```bash
   cp dispatch.local.example.yaml dispatch.yaml
   ```
2. **Live settings** the dispatcher re-reads each cycle (concurrency, interval,
   iteration cap) so you can tune a run without restarting it.

Key knobs (`runtime:`):

| Setting | Meaning |
|---------|---------|
| `execution` | `local` runs workers as host subprocesses (no Docker). |
| `worker_max_running` | Global cap on concurrent Explore tasks per cycle. |
| `interval` | Seconds between dispatcher cycles. |
| `max_iterations` | Safety cap on cycles per project (prevents runaway loops). |

Each worker entry sets its `type`, which `task_types` it will accept, its
concurrency (`max_running`) and scheduling `priority`.

---

## Running your own mission

A "mission" is just an origin and a goal.

```bash
# 1. start the observation server (optional, for inspecting + hinting)
fapta serve --db fapta.db

# 2. create a project
fapta new --db fapta.db --origin "START" --goal "GOAL"
#   -> prints a project id, e.g. proj_ab12cd34

# 3. run the dispatcher against your config
fapta dispatch --config dispatch.yaml

# 4. inspect the resulting graph
fapta graph --db fapta.db proj_ab12cd34
```

Run worker preflight checks (verifies each configured CLI is installed) without
starting a run:

```bash
fapta dispatch --config dispatch.yaml --startup-healthcheck-only
```

---

## Injecting human judgement (Hints)

While a search is running, you can steer it without stopping it. A Hint is picked up
by the next Reason task.

```bash
curl -X POST localhost:8000/projects/<project_id>/hints \
     -H 'content-type: application/json' \
     -d '{"content": "focus on the B branch first"}'
```

Hints are consumed once (so the same hint isn't re-applied every cycle) and are
presented to workers as high-priority guidance.

---

## Scope & responsible use

FAPTA is an **orchestration engine**. It contains no exploit code, no payloads, and
no attack tooling, and this project will not ship any. When applied to security
testing it is a coordinator that drives tools **you** provide and authorise.

- Use it **only** against systems, networks, applications, or data you **own** or
  have **explicit, prior, written authorisation** to test.
- Unauthorised testing, exploitation, or data access may be illegal and may cause
  real harm. Scope, rules of engagement, and legal sign-off are **your**
  responsibility.
- The authors accept no responsibility for misuse. By using this project you agree
  to comply with all applicable laws, contracts, and policies in your jurisdiction.

If your use is offensive security, treat this the way you would any professional
engagement: written authorisation first, scoped targets, and an audit trail.

---

## The air-gapped / offline path

The engine is already built to run with **no outbound network from the engine
itself**: SQLite on disk, local-mode workers as host subprocesses, and the `mock`
backend needs nothing at all. The only component that reaches the network today is a
hosted-LLM worker backend talking to its provider.

True air-gapped operation therefore needs one change: **point a worker at a
locally-hosted model** instead of a hosted CLI. Because workers are swappable behind
the `cli` type, this is a configuration change, not an engine change — bind the local
model's CLI via its argv and the dispatcher, store, protocol and UI are untouched.

A dedicated, fully-offline packaging (vendored dependencies, a bundled local model
runner, zero egress by construction) is a planned follow-up. It is deliberately
**not** part of this first build — the normal version is built and working first, as
intended, with the offline seam left clean for that next step.

---

## Supply-chain policy

Every runtime dependency is from a non-Chinese vendor, by design. The two LLM
backends are US tools (Anthropic, OpenAI). The one unverified-provenance backend
present in comparable upstream projects (a CLI called "Pi") is **deliberately not
included**. See the stack table below for the origin of each dependency. If you add
a backend or dependency, keep provenance in mind — the `cli` worker type lets you add
any executor without the engine taking a new dependency.

---

## Technology stack

| Layer | Choice | Origin | Notes |
|-------|--------|--------|-------|
| Language | Python 3.12+ | PSF (US) | No Java. |
| Data models | Pydantic v2 | S. Colvin / UK | Typed Fact/Intent/Hint. |
| Store | SQLite (stdlib) | D. R. Hipp / US | File-based, WAL, atomic claims. Air-gap friendly. |
| API / server | FastAPI + Uvicorn | S. Ramírez (CO) / Encode (UK) | Observation + hint channel. |
| CLI / config | Click + PyYAML | Pallets (US) | `fapta` command + YAML config. |
| Worker: mock | stdlib only | — | Deterministic offline backend. |
| Worker: claudecode | Anthropic `claude` CLI | Anthropic (US) | Headless print mode. |
| Worker: codex | OpenAI `codex` CLI | OpenAI (US) | `codex exec`. |
| Browser (optional) | Playwright | Microsoft (US) | Only if a worker must drive a browser. Not core. |
| Packaging | hatchling / uv | PyPA / Astral (US) | Installable, lockable, offline-capable. |
| Tests | pytest | Holger Krekel et al. | 23-test offline suite. |

---

## Project layout

```
Forkable-Automated-Penetration-Test-Agent/
├── fapta/
│   ├── models.py            # Fact / Intent / Hint / Graph — the vocabulary
│   ├── store.py             # SQLite blackboard, atomic intent claims
│   ├── protocol.py          # Task -> prompt, and reply -> WorkerResult
│   ├── dispatcher.py        # scheduler + sole writer-back (the engine's heart)
│   ├── server.py            # FastAPI observation + hint API
│   ├── config.py            # YAML + live-settings config model
│   ├── cli.py               # `fapta serve|dispatch|new|graph|demo`
│   ├── demo_runner.py       # the offline maze demo
│   └── workers/
│       ├── base.py          # Worker ABC, Task, WorkerResult
│       ├── mock.py          # deterministic hidden-maze backend
│       ├── subprocess_worker.py  # Claude Code / Codex / generic CLI backends
│       └── __init__.py      # worker factory
├── examples/maze_mission.yaml
├── demo/run_demo.py
├── tests/                   # 23 offline tests
├── dispatch.example.yaml
├── dispatch.local.example.yaml
├── pyproject.toml
└── LICENSE
```

---

## Testing

The suite is fully offline — no Docker, no model endpoints, no keys:

```bash
pytest -q
# 23 passed
```

It covers the store (including a 20-thread atomic-claim race that proves exactly one
worker can ever win an Intent), the protocol's tolerant JSON parsing, the worker
factory and mocked subprocess backends, and full end-to-end searches with the
deterministic maze — including an **unsolvable** maze, which must *stop* rather than
ever falsely claim success.

---

## Design decisions & FAQ

**Why is the shipped demo a maze and not a hacking scenario?**
Because the engine is genuinely domain-neutral, and a maze proves the architecture —
discovery of an unknown state space, concurrent exploration, convergence on a goal —
with zero ambiguity and zero attack content. The security application is enabled by
your configuration and your authorised tools, not baked into the repo.

**Why SQLite and not a "real" database?**
Zero external dependencies, a single file, atomic transactions for the claim race,
and it runs fine air-gapped. Swap in Postgres behind the same `GraphStore` interface
if you need multi-host scale.

**Why does only the dispatcher write results back?**
Single-writer keeps the graph consistent and the protocol simple. Workers stay pure
functions, which is what makes them parallel and swappable.

**Can workers run in parallel?**
Yes — the atomic Intent claim is exactly what makes concurrent exploration safe.
`worker_max_running` caps how many Explore tasks run per cycle.

**How do I add a new backend?**
For a vendor CLI, use the `cli` worker type and give it an argv — no code needed. For
something richer, subclass `Worker` and implement `run(task) -> WorkerResult`.

---

## License

MIT. See [LICENSE](LICENSE). "Forkable" is in the name on purpose — fork it, embed
it, build on it.
