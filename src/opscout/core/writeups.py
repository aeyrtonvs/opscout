# SPDX-License-Identifier: Apache-2.0
"""The built-in write-up formats and the rules every write-up follows (spec 003).

The shared rules are the summary skill's contract: they are printed before any configured
rule, whatever the configuration says. The formats follow the shape PLAN.md states
publicly, and hold nothing organization-specific (Constitution Principle I).
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from opscout.core.config import WriteupFormat

SHARED_RULES: Final = (
    "State only facts from the session; invent nothing: no ticket keys, names, times or "
    "figures that the session does not state.",
    "Never list what was evaluated and ruled out, nor how the result was reached.",
    "Never include a secret value; you may say that a secret exists and where it lives.",
    "Write plain text ready to paste: no preamble, and no headings other than the format's "
    "sections.",
)

BUILT_IN_FORMATS: Final[Mapping[str, WriteupFormat]] = MappingProxyType(
    {
        "ticket": WriteupFormat(
            description="A ticket update: the problem, its cause, what was done and what is left.",
            sections=["What happened", "Why", "What was done", "What is pending"],
            max_lines=12,
        ),
        "message": WriteupFormat(
            description="A short chat message for teammates.",
            rules=["Two to four sentences, no sections."],
            max_lines=5,
        ),
        "postmortem": WriteupFormat(
            description="An incident postmortem.",
            sections=["Cause", "Impact", "Fix", "Follow-ups"],
            max_lines=25,
        ),
    }
)
