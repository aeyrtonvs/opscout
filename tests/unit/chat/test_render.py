# SPDX-License-Identifier: Apache-2.0
"""The direct message's form (spec 008, FR-008, FR-009; research R3)."""

import pytest

from opscout.services.chat import LIMIT, render_message

TEXT = """\
# opscout check, 2026-11-05

The scheduled path works: **all** good, with `code` and a [link](https://example.com).

- one
- two
"""


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 008."""
    return pytest.mark.spec("008", requirement)


@spec("FR-008")
def test_the_text_goes_unchanged_as_markdown() -> None:
    message = render_message(
        TEXT, job="check", run_id="20261105T094500Z-a1b2c3", kind="result",
        outbox="/example/outbox/check/x.md",
    )  # fmt: skip
    assert message.markdown == TEXT
    assert message.notification == "opscout check, 2026-11-05"


@spec("FR-008")
def test_a_long_text_is_cut_at_a_line_and_names_the_outbox() -> None:
    line = "x" * 99 + "\n"
    text = line * 200  # 20,000 characters
    message = render_message(
        text, job="check", run_id="20261105T094500Z-a1b2c3", kind="result",
        outbox="/example/outbox/check/x.md",
    )  # fmt: skip
    body, note = message.markdown.rsplit("\n\n", 1)
    assert len(message.markdown) <= LIMIT
    assert text.startswith(body + "\n")
    assert body.endswith("x")
    assert note == "_Shortened; the full text is in /example/outbox/check/x.md._"


@spec("FR-008")
def test_the_notification_is_one_plain_line_of_at_most_150_characters() -> None:
    message = render_message(
        "\n\n## **Big** `news` " + "y" * 300 + "\nmore", job="check",
        run_id="20261105T094500Z-a1b2c3", kind="notice", outbox="/x.md",
    )  # fmt: skip
    assert message.notification.startswith("Big news yyy")
    assert len(message.notification) <= 150
    assert "\n" not in message.notification


@spec("FR-009")
def test_a_result_has_buttons_and_a_context_line_a_notice_has_neither() -> None:
    result = render_message(
        TEXT, job="check", run_id="20261105T094500Z-a1b2c3", kind="result", outbox="/x.md"
    )
    assert result.buttons == "check/20261105T094500Z-a1b2c3"
    assert result.context == "opscout check, run 20261105T094500Z-a1b2c3"
    for kind in ("notice", "failure"):
        notice = render_message(
            TEXT, job="check", run_id="20261105T094500Z-a1b2c3", kind=kind, outbox="/x.md"
        )
        assert (notice.buttons, notice.context) == (None, None)
    chosen = render_message(
        TEXT, job="check", run_id="20261105T094500Z-a1b2c3", kind="result", outbox="/x.md",
        context="Agreed on 2026-11-05 10:02",
    )  # fmt: skip
    assert chosen.context == "Agreed on 2026-11-05 10:02"
