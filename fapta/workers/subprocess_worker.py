"""
Subprocess-backed workers.

These adapters drive a local coding-agent CLI as a headless subprocess: build the
prompt with the shared protocol, hand it to the CLI, capture stdout, parse the JSON
reply back into a WorkerResult. They add no capability of their own - all behaviour
comes from the backend model and from whatever tools the operator has authorised on
that machine.

Two concrete backends ship here, both from US vendors:
  - ClaudeCodeWorker : Anthropic's `claude` CLI (headless `-p` print mode).
  - CodexWorker      : OpenAI's `codex` CLI (`codex exec` non-interactive mode).

CLI flags drift over time, so the exact argv is configurable (see dispatch.*.yaml);
the defaults here are a sensible starting point, not a hard dependency.
"""

from __future__ import annotations

import shutil
import subprocess

from ..protocol import build_prompt, parse_result
from .base import Task, Worker, WorkerResult

# The token replaced by the prompt text when a command passes the prompt as an
# argument. If no command contains this token, the prompt is sent on stdin.
PROMPT_TOKEN = "{prompt}"


class CliWorker(Worker):
    """
    Generic worker that invokes an external CLI.

    command : argv list. If it contains PROMPT_TOKEN, that element is replaced by the
              prompt; otherwise the prompt is piped to the process's stdin.
    timeout : seconds before the invocation is abandoned.
    """

    def __init__(
        self,
        name: str,
        command: list[str],
        timeout: int = 600,
        cwd: str | None = None,
    ):
        super().__init__(name)
        self.command = command
        self.timeout = timeout
        self.cwd = cwd

    def _invoke(self, prompt: str) -> str:
        if PROMPT_TOKEN in self.command:
            argv = [prompt if tok == PROMPT_TOKEN else tok for tok in self.command]
            stdin_data = None
        else:
            argv = list(self.command)
            stdin_data = prompt

        proc = subprocess.run(
            argv,
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            cwd=self.cwd,
        )
        if proc.returncode != 0:
            # Surface the error as raw text; the dispatcher treats an unparseable
            # result as a no-op, so a failed call simply does not advance the board.
            return f"[cli error rc={proc.returncode}] {proc.stderr.strip()}"
        return proc.stdout

    def run(self, task: Task) -> WorkerResult:
        prompt = build_prompt(task)
        output = self._invoke(prompt)
        return parse_result(output)

    def preflight(self) -> tuple[bool, str]:
        """Check the CLI binary exists on PATH. Used by dispatcher startup checks."""
        binary = self.command[0]
        if shutil.which(binary) is None:
            return False, f"{binary!r} not found on PATH"
        return True, f"{binary!r} found"


class ClaudeCodeWorker(CliWorker):
    """Anthropic Claude Code CLI in headless print mode (prompt via stdin)."""

    def __init__(self, name: str = "claudecode", timeout: int = 600, cwd: str | None = None):
        super().__init__(name, command=["claude", "-p"], timeout=timeout, cwd=cwd)


class CodexWorker(CliWorker):
    """OpenAI Codex CLI in non-interactive exec mode (prompt via stdin)."""

    def __init__(self, name: str = "codex", timeout: int = 600, cwd: str | None = None):
        super().__init__(name, command=["codex", "exec"], timeout=timeout, cwd=cwd)
