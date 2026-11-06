# SPDX-License-Identifier: Apache-2.0
"""The packaged reference keeps secret reads and writes out (spec 010, FR-002, FR-012, FR-014)."""

import socket
import time
from typing import Any

import pytest

from opscout.adapters.identity_files import load_records
from opscout.core.identity import Analysis, Records, proves_denied, with_allow_all
from opscout.services.identity import hosts_identity, prove, readonly_identity

DENY_KINDS = {"secret-allowed", "write-allowed", "data-allowed", "exception-too-wide"}


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 010."""
    return pytest.mark.spec("010", requirement)


@pytest.fixture(scope="module")
def records() -> Records:
    return load_records()


@spec("FR-002")
def test_every_guardrail_entry_is_denied_for_both_identities_even_with_allow_all(
    records: Records,
) -> None:
    identities = [readonly_identity(records.reference, records)]
    hosts = hosts_identity(records.reference, records)
    if hosts is not None:
        identities.append(hosts)
    for identity in identities:
        robust = with_allow_all(identity)
        analysis = Analysis(robust, records.catalog)
        for entry in records.guardrail:
            if entry.resource != "*":
                resource = entry.resource.replace("*", "us-east-1", 1)
                assert proves_denied(robust, entry.action, resource)[0], entry
                continue
            keys = records.catalog.expand(entry.action)
            assert keys, f"{entry.action} is not in the catalog"
            for key in keys:
                assert analysis.denied_everywhere(key) is not None, (identity.name, key)


@spec("FR-002")
def test_every_write_in_the_catalog_is_denied_for_the_read_only_identity(
    records: Records,
) -> None:
    robust = with_allow_all(readonly_identity(records.reference, records))
    analysis = Analysis(robust, records.catalog)
    allowed = [
        key
        for key in records.catalog
        if records.catalog.is_write(key) and analysis.denied_everywhere(key) is None
    ]
    assert allowed == []


@spec("FR-012")
def test_the_reference_has_no_deny_finding_and_reports_its_counts(records: Records) -> None:
    report = prove(records.reference, records)

    assert [f for f in report.findings if f.kind in DENY_KINDS] == []
    summary = "\n".join(report.summary)
    assert f"fetched {records.catalog.fetched}" in summary
    assert f"ViewOnlyAccess {records.view_only.version}" in summary
    writes = sum(1 for key in records.catalog if records.catalog.is_write(key))
    assert f"writes {writes:,}/{writes:,} denied" in summary


@spec("FR-012")
def test_no_data_plane_action_is_allowed_unless_a_capability_declares_it(
    records: Records,
) -> None:
    declared = {
        action.lower()
        for capability in records.capabilities
        for action in (*capability.actions, *capability.reads)
    }
    analysis = Analysis(readonly_identity(records.reference, records), records.catalog)
    undeclared = sorted(
        key
        for key in analysis.allowed_somewhere()
        if records.catalog.is_data_plane(key) and key not in declared
    )
    assert undeclared == []


@spec("FR-014")
def test_the_proof_needs_no_network_and_runs_in_under_two_seconds(
    records: Records, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the check opened a network connection")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    started = time.perf_counter()
    prove(records.reference, records)
    assert time.perf_counter() - started < 2.0
