# SPDX-License-Identifier: Apache-2.0
"""Every document fits AWS's size limits (spec 010, FR-005; research R8)."""

import copy
import json
import re
from typing import Any

import pytest

from opscout.adapters.identity_files import load_records
from opscout.core.identity import Records, Tree
from opscout.services.identity import MAX_ATTACHMENTS, MAX_INLINE, MAX_POLICY, prove


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 010."""
    return pytest.mark.spec("010", requirement)


@pytest.fixture(scope="module")
def records() -> Records:
    return load_records()


def _size(document: Any) -> int:
    return len(re.sub(r"\s", "", json.dumps(document)))


@spec("FR-005")
def test_each_aws_document_fits_a_customer_managed_policy(records: Records) -> None:
    sizes = {
        path: _size(document)
        for path, document in records.reference.files.items()
        if path.startswith("aws/")
    }
    assert sizes
    assert max(sizes.values()) <= MAX_POLICY


@spec("FR-005")
def test_the_guardrail_and_capabilities_fit_one_inline_policy(records: Records) -> None:
    inline = sum(
        _size(document)
        for path, document in records.reference.files.items()
        if path == "aws/guardrail.json" or path.startswith("aws/readonly/")
    )
    assert inline <= MAX_INLINE


@spec("FR-005")
def test_the_identity_stays_within_the_attachment_limit(records: Records) -> None:
    capabilities = [p for p in records.reference.files if p.startswith("aws/readonly/")]
    assert 2 + len(capabilities) <= MAX_ATTACHMENTS


@spec("FR-005")
def test_an_oversized_document_fails_naming_its_file_and_size(records: Records) -> None:
    files = copy.deepcopy(dict(records.reference.files))
    files["aws/guardrail.json"]["Statement"].append(
        {"Effect": "Deny", "Action": "ec2:DescribeVpcs", "Resource": ["x" * 6_000]}
    )

    report = prove(Tree(files), records)

    messages = [f.message for f in report.findings if f.kind == "too-large"]
    assert any(m.startswith("aws/guardrail.json has ") and "(limit 6,144)" in m for m in messages)
    assert any("for one inline policy" in m for m in messages)
