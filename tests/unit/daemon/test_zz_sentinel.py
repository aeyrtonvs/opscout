# SPDX-License-Identifier: Apache-2.0
"""SC-004: no secret value in any file the daemon tests wrote (spec 007, FR-024).

Named to run after every other daemon test module, so the files it searches exist: the
records, outbox files, logs and property lists, and the fake ``claude``'s log of the
environment each child got, which must not hold the sentinel either: the runner's
allow-list drops it.
"""

import pytest

from tests.unit.chat.fakes import REASON_SENTINEL, TOKEN_SENTINEL
from tests.unit.daemon.fakes import SENTINEL


@pytest.mark.spec("007", "FR-024")
def test_the_sentinel_is_in_no_file_the_suite_wrote(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    root = tmp_path_factory.getbasetemp()
    searched = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix in (".json", ".jsonl", ".md", ".log", ".plist")
    ]
    if not any(path.suffix == ".jsonl" for path in searched):
        pytest.skip("nothing to search: run it after the daemon tests, as the whole suite does")
    leaks = [p for p in searched if SENTINEL in p.read_text(encoding="utf-8", errors="replace")]
    assert leaks == []


@pytest.mark.spec("008", "FR-011")
def test_no_chat_token_anywhere_and_a_reason_only_in_a_run_record(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    root = tmp_path_factory.getbasetemp()
    files = [path for path in root.rglob("*") if path.is_file()]
    texts = {path: path.read_text(encoding="utf-8", errors="replace") for path in files}
    if not any(REASON_SENTINEL in text for text in texts.values()):
        pytest.skip("nothing to search: run it after tests/unit/chat, as the whole suite does")
    assert [path for path, text in texts.items() if TOKEN_SENTINEL in text] == []
    assert [
        path
        for path, text in texts.items()
        if REASON_SENTINEL in text
        and not (path.parent.parent.name == "runs" and path.suffix == ".json")
    ] == []
