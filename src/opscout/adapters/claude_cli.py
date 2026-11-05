# SPDX-License-Identifier: Apache-2.0
"""ClaudeCliRunner: the user's own ``claude -p``, restricted and checked (spec 007, ADR-0012).

Every restriction is passed as a flag (research R1); nothing is left to Claude Code's
defaults or to the user's settings. The run's start-up report (the ``system/init`` event)
is read first and compared with the profile; on any difference the child is stopped and
its output discarded (FR-015). The output is validated against the job's model, with one
retry that carries the validator's message (FR-016). The child gets an environment built
from an allow-list, plus the secrets the job declares (FR-017).
"""

import contextlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Final

from pydantic import BaseModel, ValidationError

from opscout.core.daemon import RunnerFacts, RunProfile, RunResult, StartupReport

ALLOWED_VARIABLES: Final = frozenset(
    {
        "HOME",
        "USER",
        "LOGNAME",
        "PATH",
        "TMPDIR",
        "SHELL",
        "LANG",
        "CLAUDE_CONFIG_DIR",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "NODE_EXTRA_CA_CERTS",
    }
)
"""What the child may inherit (research R1); every ``LC_*`` variable passes too."""

REPORT_FIELDS: Final = (
    "tools",
    "mcp_servers",
    "model",
    "permissionMode",
    "plugins",
    "apiKeySource",
    "claude_code_version",
)

RETRY: Final = (
    "\n\nYour previous output did not match the required schema: {message}\n"
    "Return the output again through the structured output, matching the schema exactly."
)

STOP_SECONDS: Final = 5


class ReportError(Exception):
    """The start-up report cannot be read; the run is refused."""


def child_environment(environ: Mapping[str, str], secrets: Mapping[str, str]) -> dict[str, str]:
    """Return the child's environment: the allow-list, then the declared secrets."""
    kept = {
        name: value
        for name, value in environ.items()
        if name in ALLOWED_VARIABLES or name.startswith("LC_")
    }
    return {**kept, **secrets}


def arguments(profile: RunProfile) -> list[str]:
    """Return every flag of research R1, in order; the prompt goes on standard input."""
    servers = (
        ["--mcp-config", json.dumps({"mcpServers": dict(profile.mcp_servers)}, sort_keys=True)]
        if profile.mcp_servers
        else []
    )
    schema = json.dumps(profile.schema, separators=(",", ":"), sort_keys=True)
    return [
        "-p",
        "--output-format", "stream-json",
        "--verbose",
        "--safe-mode",
        "--restricted",
        "--tools", ",".join(profile.tools),
        "--strict-mcp-config",
        *servers,
        "--permission-mode", "dontAsk",
        "--permission-prompts", "none",
        "--no-session-persistence",
        "--model", profile.model,
        "--max-budget-usd", f"{profile.budget_usd:g}",
        "--max-turns", str(profile.max_turns),
        "--json-schema", schema,
    ]  # fmt: skip


def read_report(event: Mapping[str, Any]) -> StartupReport:
    """Return the start-up report of a ``system/init`` event. Raises ``ReportError``."""
    for name in REPORT_FIELDS:
        if name not in event:
            raise ReportError(f"the start-up report has no {name}")
    try:
        return StartupReport(
            tools=tuple(str(tool) for tool in event["tools"]),
            mcp_servers=tuple(
                str(server["name"] if isinstance(server, dict) else server)
                for server in event["mcp_servers"]
            ),
            model=str(event["model"]),
            permission_mode=str(event["permissionMode"]),
            plugins=tuple((str(p["name"]), str(p["path"])) for p in event["plugins"]),
            api_key_source=str(event["apiKeySource"]),
            claude_code_version=str(event["claude_code_version"]),
        )
    except (KeyError, TypeError) as error:
        raise ReportError(f"the start-up report cannot be read ({type(error).__name__})") from None


def _validation_message(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc']) or 'output'}: {item['msg']}"
        for item in error.errors(include_url=False, include_input=False)
    )


@dataclass
class _Attempt:
    """What one start of Claude Code produced."""

    report: StartupReport | None = None
    refused: tuple[str, ...] = ()
    result: dict[str, Any] | None = None
    tools_called: list[str] = field(default_factory=list)
    error: str | None = None


class ClaudeCliRunner:
    """The ``Runner`` port on the user's own Claude Code CLI."""

    def __init__(
        self,
        claude_path: str | None,
        run_dir: Path,
        environ: Mapping[str, str],
        compare: Callable[[RunProfile, StartupReport], tuple[str, ...]],
        timeout: float = 900,
    ) -> None:
        self._claude_path = claude_path
        self._run_dir = run_dir
        self._environ = environ
        self._compare = compare
        self._timeout = timeout

    def run(self, profile: RunProfile, prompt: str, env: Mapping[str, str]) -> RunResult:
        """Run the model with the profile, at most twice (FR-014 to FR-018)."""
        try:
            program = self._locate()
        except LookupError as error:
            return RunResult("error", reason=str(error))
        command = [str(program), *arguments(profile)]
        child = child_environment(self._environ, env)
        attempts: list[_Attempt] = []
        text = prompt
        while True:
            attempt = self._attempt(command, text, child, profile)
            attempts.append(attempt)
            facts = _facts(attempts)
            if attempt.refused:
                return RunResult("refused", differences=attempt.refused, facts=facts)
            if attempt.error is not None or attempt.result is None:
                return RunResult("error", reason=attempt.error, facts=facts)
            try:
                output = _validate(profile.output, attempt.result)
            except ValidationError as error:
                message = _validation_message(error)
            except ValueError as error:
                message = str(error)
            else:
                return RunResult("ok", output=output, facts=facts)
            if len(attempts) == 2:
                return RunResult("invalid_output", reason=message, facts=facts)
            text = prompt + RETRY.format(message=message)

    def _locate(self) -> Path:
        if self._claude_path is not None:
            path = Path(self._claude_path)
            if not path.is_file():
                raise LookupError(f"Claude Code not found at {path} (daemon.claude_path)")
            return path
        search = self._environ.get("PATH", "")
        found = shutil.which("claude", path=search)
        if found is None:
            raise LookupError(
                "Claude Code not found: daemon.claude_path is not set and claude is not on "
                f"PATH ({search})"
            )
        return Path(found)

    def _attempt(
        self, command: list[str], prompt: str, env: dict[str, str], profile: RunProfile
    ) -> _Attempt:
        self._run_dir.mkdir(parents=True, exist_ok=True)
        attempt = _Attempt()
        with tempfile.TemporaryFile() as errors:
            try:
                child = subprocess.Popen(  # noqa: S603  (the user's own claude, no shell)
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=errors,
                    cwd=self._run_dir,
                    env=env,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    start_new_session=True,  # so a stop reaches every process it started
                )
            except OSError as error:
                attempt.error = f"Claude Code could not be started ({type(error).__name__})"
                return attempt
            stopped = threading.Event()

            def stop() -> None:
                stopped.set()
                _signal(child, signal.SIGKILL)

            timer = threading.Timer(self._timeout, stop)
            timer.start()
            try:
                self._converse(child, prompt, profile, attempt)
            finally:
                timer.cancel()
                _end(child)
            if stopped.is_set():
                attempt.error = f"Claude Code took longer than {self._timeout:g} s and was stopped"
            elif attempt.error is None and attempt.result is None and not attempt.refused:
                errors.seek(0)
                attempt.error = _no_result(child.returncode, attempt.report, errors)
        return attempt

    def _converse(
        self, child: "subprocess.Popen[str]", prompt: str, profile: RunProfile, attempt: _Attempt
    ) -> None:
        stdin, stdout = child.stdin, child.stdout
        if stdin is None or stdout is None:  # never: both are pipes
            return
        try:
            stdin.write(prompt)
            stdin.close()
        except BrokenPipeError:
            pass
        first = stdout.readline()
        if not first:
            return
        event = _event(first)
        if event is None or (event.get("type"), event.get("subtype")) != ("system", "init"):
            attempt.refused = ("the first event was not the start-up report",)
            return
        try:
            attempt.report = read_report(event)
        except ReportError as error:
            attempt.refused = (str(error),)
            return
        attempt.refused = self._compare(profile, attempt.report)
        if attempt.refused:
            return
        for line in stdout:
            event = _event(line)
            if event is None:
                continue
            if event.get("type") == "assistant":
                attempt.tools_called.extend(_tool_uses(event))
            elif event.get("type") == "result":
                attempt.result = event
        if attempt.result is not None and attempt.result.get("is_error"):
            attempt.error = _error_reason(attempt.result)


def _end(child: "subprocess.Popen[str]") -> None:
    """Stop the child if it still runs, and reap it."""
    if child.poll() is None:
        _signal(child, signal.SIGTERM)
        try:
            child.wait(STOP_SECONDS)
        except subprocess.TimeoutExpired:
            _signal(child, signal.SIGKILL)
            child.wait()
    if child.stdout is not None:
        child.stdout.close()


def _signal(child: "subprocess.Popen[str]", number: int) -> None:
    """Signal the child's whole process group; it leads its own session."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(child.pid, number)


def _number(value: object) -> float:
    """Return a report's number, or 0 for anything that is not one."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0
    return value


def _event(line: str) -> dict[str, Any] | None:
    try:
        event = json.loads(line)
    except ValueError:
        return None
    return event if isinstance(event, dict) else None


def _tool_uses(event: Mapping[str, Any]) -> Iterable[str]:
    message = event.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    for block in content if isinstance(content, list) else []:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            yield str(block.get("name"))


def _error_reason(result: Mapping[str, Any]) -> str:
    subtype = str(result.get("subtype", "error"))
    errors = result.get("errors")
    if isinstance(errors, list) and errors:
        return f"{subtype}: {'; '.join(str(error) for error in errors)}"
    return f"{subtype} ({result.get('terminal_reason', 'no reason given')})"


def _no_result(status: int | None, report: StartupReport | None, errors: IO[bytes]) -> str:
    if report is not None:
        return f"Claude Code exited with status {status} without a result"
    first = next(
        (line.strip() for line in errors.read(4096).decode("utf-8", "replace").splitlines()
         if line.strip()),
        "",
    )  # fmt: skip
    detail = f": {first[:200]}" if first else ""
    return f"Claude Code exited with status {status} before its start-up report{detail}"


def _validate(model: type[BaseModel], result: Mapping[str, Any]) -> BaseModel:
    if "structured_output" not in result:
        raise ValueError("no structured output was returned")
    return model.model_validate(result["structured_output"])


def _facts(attempts: list[_Attempt]) -> RunnerFacts:
    report = next((a.report for a in reversed(attempts) if a.report is not None), None)
    results = [a.result for a in attempts if a.result is not None]
    tools: list[str] = []
    for attempt in attempts:
        tools.extend(name for name in attempt.tools_called if name not in tools)
    return RunnerFacts(
        claude_code_version=report.claude_code_version if report else None,
        model=report.model if report else None,
        api_key_source=report.api_key_source if report else None,
        cost_usd=round(sum(_number(r.get("total_cost_usd")) for r in results), 6),
        turns=sum(int(_number(r.get("num_turns"))) for r in results),
        duration_ms=sum(int(_number(r.get("duration_ms"))) for r in results),
        tools_called=tuple(tools),
        attempts=len(attempts),
    )
