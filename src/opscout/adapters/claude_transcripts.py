# SPDX-License-Identifier: Apache-2.0
"""TranscriptFiles: the user's own prompts from Claude Code's session transcripts.

Claude Code keeps one JSON Lines file per session under ``<config>/projects/``. Only the
user's typed prompts are taken, never the model's replies, tool calls or tool output;
system-generated lines, pasted text, tagged blocks and interruption markers are dropped
(spec 009, research R1).
A session whose working directory is outside every project is not read past its first
line that names one.
"""

import json
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from opscout.core.standup import SessionPrompts, SourceError, TranscriptScan, Window

NOT_PROMPTS: Final = (
    "<task-notification",
    "<local-command-",
    "<command-name",
    "<command-message",
    "<command-args",
    "<bash-input",
    "<bash-stdout",
    "<bash-stderr",
    "<system-reminder",
    "<user-memory-input",
)
# A tagged block, pasted text among them. Claude Code may repeat the attributes on the
# closing tag (``</pasted_content id="1">``); a paste left open drops the rest of the prompt.
_TAGGED = re.compile(r"<([a-z][a-z_-]*)\b[^>]*>.*?</\1\b[^>]*>", re.DOTALL)
_UNCLOSED_PASTE = re.compile(r"<pasted_content\b.*", re.DOTALL)
_INTERRUPTED = re.compile(r"\[Request interrupted by user[^\]]*\]")
_SPACES = re.compile(r"\s+")


def _prompt(line: dict[str, Any]) -> str | None:
    """Return the user's own text in a transcript line, or None when it is not a prompt."""
    if line.get("type") != "user" or line.get("isMeta") or line.get("isCompactSummary"):
        return None
    if line.get("isSidechain"):  # a subagent's brief, written by the model
        return None
    if "toolUseResult" in line or line.get("promptSource") == "system":
        return None
    content = (line.get("message") or {}).get("content")
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") != "text" for b in content):
            return None
        content = " ".join(str(b.get("text", "")) for b in content if isinstance(b, dict))
    if not isinstance(content, str) or content.lstrip().startswith(NOT_PROMPTS):
        return None
    text = _UNCLOSED_PASTE.sub(" ", _TAGGED.sub(" ", content))
    text = _SPACES.sub(" ", _INTERRUPTED.sub(" ", text)).strip()
    return text or None


def _time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


class TranscriptFiles:
    """The ``Transcripts`` port on Claude Code's local session files."""

    def __init__(self, projects: Path) -> None:
        self._projects = projects

    def scan(self, window: Window, roots: Sequence[Path]) -> TranscriptScan:
        """Return the prompts of sessions under ``roots`` in the window."""
        if not self._projects.is_dir():
            raise SourceError(f"no Claude Code transcripts at {self._projects}")
        sessions: list[SessionPrompts] = []
        unreadable = 0
        since = window.start.timestamp()
        for path in sorted(self._projects.glob("*/*.jsonl")):
            try:
                if path.stat().st_mtime < since:
                    continue
                found, bad = self._session(path, window, roots)
            except OSError:
                unreadable += 1
                continue
            unreadable += bad
            if found is not None:
                sessions.append(found)
        return TranscriptScan(tuple(sessions), unreadable)

    def _session(
        self, path: Path, window: Window, roots: Sequence[Path]
    ) -> tuple[SessionPrompts | None, int]:
        cwd: str | None = None
        prompts: list[tuple[datetime, str]] = []
        bad = 0
        with path.open(encoding="utf-8", errors="replace") as file:
            for raw in file:
                try:
                    line = json.loads(raw)
                except ValueError:
                    bad += 1
                    continue
                if not isinstance(line, dict):
                    bad += 1
                    continue
                if cwd is None and isinstance(line.get("cwd"), str):
                    cwd = line["cwd"]
                    if not any(Path(cwd).is_relative_to(root) for root in roots):
                        return None, bad  # outside every project: read no further
                moment = _time(line.get("timestamp"))
                if moment is None or not window.start <= moment < window.end:
                    continue
                text = _prompt(line)
                if text is not None:
                    prompts.append((moment, text))
        if cwd is None or not prompts:
            return None, bad
        return SessionPrompts(session=path.stem, cwd=cwd, prompts=tuple(prompts)), bad
