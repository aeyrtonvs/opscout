# SPDX-License-Identifier: Apache-2.0
"""The refresh of the recorded catalog and managed-policy copies (spec 010, FR-011, FR-015)."""

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from tools.identity_refresh import (
    INDEX_URL,
    build_catalog,
    diff_summary,
    flags,
    parse_managed_page,
)

SAMPLES = Path(__file__).parent / "samples" / "service-reference"
FETCHED = date(2026, 11, 5)


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 010."""
    return pytest.mark.spec("010", requirement)


def _sample(name: str) -> Any:
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))


def _fetch(url: str) -> Any:
    if url == INDEX_URL:
        return _sample("index.json")
    return _sample(url.rsplit("/", 1)[1])


@spec("FR-011")
@pytest.mark.parametrize(
    ("properties", "expected"),
    [
        ({"IsWrite": False, "IsList": False, "IsPermissionManagement": False}, ""),
        ({"IsWrite": True}, "w"),
        ({"IsPermissionManagement": True, "IsWrite": True}, "pw"),
        ({"IsTaggingOnly": True, "IsWrite": True}, "tw"),
        ({"IsList": True}, "l"),
        ({"IsDataPlane": True}, "d"),
        ({}, ""),
    ],
)
def test_access_level_properties_become_flag_letters(
    properties: dict[str, bool], expected: str
) -> None:
    assert flags(properties) == expected


@spec("FR-011")
def test_the_catalog_records_source_date_versions_and_sorted_actions() -> None:
    catalog = build_catalog(_fetch, FETCHED)

    assert catalog["source"] == INDEX_URL
    assert catalog["fetched"] == "2026-11-05"
    assert list(catalog["services"]) == ["ce", "ssm"]
    assert catalog["services"]["ce"] == {
        "version": "v1.5",
        "actions": {"CreateAnomalyMonitor": "w", "GetCostAndUsage": "", "TagResource": "tw"},
    }
    ssm = catalog["services"]["ssm"]["actions"]
    assert list(ssm) == sorted(ssm)
    assert ssm["SendCommand"] == "w"
    assert ssm["GetParameter"] == "d"
    assert ssm["AddTagsToResource"] == "t"
    assert ssm["PutResourcePolicy"] == "pw"


@spec("FR-015")
def test_the_diff_summary_lists_added_removed_and_reclassified_actions() -> None:
    old = build_catalog(_fetch, FETCHED)
    new = json.loads(json.dumps(old))
    del new["services"]["ce"]["actions"]["TagResource"]
    new["services"]["ce"]["actions"]["GetAnomalies"] = ""
    new["services"]["ssm"]["actions"]["GetParameter"] = "dw"
    new["services"]["ec2"] = {"version": "v1.5", "actions": {"CreateTags": "tw"}}

    assert diff_summary(old, new) == [
        "added ce:GetAnomalies (read)",
        "added ec2:CreateTags (tw)",
        "removed ce:TagResource",
        "reclassified ssm:GetParameter: d -> dw",
    ]
    assert diff_summary(None, new)[0] == "new catalog: 3 services, 9 actions"


@spec("FR-015")
def test_a_managed_policy_page_parses_into_its_record() -> None:
    page = (SAMPLES / "managed-page.html").read_text(encoding="utf-8")
    arn = "arn:aws:iam::aws:policy/job-function/ViewOnlyAccess"

    record = parse_managed_page(page, arn, FETCHED)

    assert record["arn"] == arn
    assert record["version"] == "v48"
    assert record["fetched"] == "2026-11-05"
    assert record["document"]["Statement"][0]["Action"] == ["ce:GetCostAndUsage", "ssm:Describe*"]


@spec("FR-015")
def test_a_page_without_a_version_or_document_is_refused() -> None:
    with pytest.raises(ValueError, match="version"):
        parse_managed_page("<html></html>", "arn:aws:iam::aws:policy/X", FETCHED)
    with pytest.raises(ValueError, match="document"):
        parse_managed_page(
            "<b>Policy version:</b> v1 (default)", "arn:aws:iam::aws:policy/X", FETCHED
        )
