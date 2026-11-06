# SPDX-License-Identifier: Apache-2.0
"""Refresh the read-only identity's recorded AWS data (spec 010, FR-011, FR-015; research R1).

Downloads AWS's Service Authorization Reference in its JSON form, and the two managed
policies the identity relies on (``ViewOnlyAccess``, the configuration grant, and
``ReadOnlyAccess``, the cap) from the AWS Managed Policy Reference. It then rewrites the
records in ``src/opscout/data/identity/``. The maintainer reviews the printed summary and
the diff, runs ``opscout identity check``, and commits. Nothing is shipped from here.

    uv run python -m tools.identity_refresh [--dry-run]
"""

import argparse
import html
import json
import re
import ssl
import sys
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import truststore

INDEX_URL = "https://servicereference.us-east-1.amazonaws.com/"
MANAGED_PAGES = {
    "ViewOnlyAccess": (
        "arn:aws:iam::aws:policy/job-function/ViewOnlyAccess",
        "https://docs.aws.amazon.com/aws-managed-policy/latest/reference/ViewOnlyAccess.html",
    ),
    "ReadOnlyAccess": (
        "arn:aws:iam::aws:policy/ReadOnlyAccess",
        "https://docs.aws.amazon.com/aws-managed-policy/latest/reference/ReadOnlyAccess.html",
    ),
}
DATA = Path(__file__).resolve().parents[1] / "src" / "opscout" / "data" / "identity"

# Annotation property → flag letter (data-model.md). All false means a read.
_FLAGS = {
    "IsDataPlane": "d",
    "IsList": "l",
    "IsPermissionManagement": "p",
    "IsTaggingOnly": "t",
    "IsWrite": "w",
}
_VERSION = re.compile(r"Policy version:</b>\s*(v\d+)")
_DOCUMENT = re.compile(r"<pre[^>]*>(.*?)</pre>", re.S)
_TAG = re.compile(r"<[^>]+>")

Fetch = Callable[[str], Any]


def flags(properties: Mapping[str, bool]) -> str:
    """Return an action's access-level flags as sorted letters; ``""`` is a read."""
    return "".join(sorted(letter for name, letter in _FLAGS.items() if properties.get(name)))


def build_catalog(fetch: Fetch, fetched: date) -> dict[str, Any]:
    """Build the catalog from the index and each service file that ``fetch`` returns."""
    services: dict[str, Any] = {}
    for entry in sorted(fetch(INDEX_URL), key=lambda item: item["service"]):
        document = fetch(entry["url"])
        actions = {
            action["Name"]: flags(action.get("Annotations", {}).get("Properties", {}))
            for action in document.get("Actions", [])
        }
        services[entry["service"]] = {
            "version": document.get("Version", ""),
            "actions": dict(sorted(actions.items())),
        }
    return {"source": INDEX_URL, "fetched": fetched.isoformat(), "services": services}


def _actions(catalog: Mapping[str, Any]) -> dict[str, str]:
    return {
        f"{prefix}:{name}": level
        for prefix, service in catalog["services"].items()
        for name, level in service["actions"].items()
    }


def diff_summary(old: Mapping[str, Any] | None, new: Mapping[str, Any]) -> list[str]:
    """Return the actions added, removed or reclassified between two catalogs."""
    after = _actions(new)
    if old is None:
        return [f"new catalog: {len(new['services'])} services, {len(after)} actions"]
    before = _actions(old)
    lines = [f"added {name} ({after[name] or 'read'})" for name in sorted(after.keys() - before)]
    lines += [f"removed {name}" for name in sorted(before.keys() - after)]
    lines += [
        f"reclassified {name}: {before[name] or 'read'} -> {after[name] or 'read'}"
        for name in sorted(before.keys() & after.keys())
        if before[name] != after[name]
    ]
    return lines


def parse_managed_page(page: str, arn: str, fetched: date) -> dict[str, Any]:
    """Return a managed policy's record from its AWS Managed Policy Reference page."""
    version = _VERSION.search(page)
    if version is None:
        raise ValueError(f"{arn}: no policy version on the page")
    document = _DOCUMENT.search(page)
    if document is None:
        raise ValueError(f"{arn}: no policy document on the page")
    text = html.unescape(_TAG.sub("", document.group(1)))
    return {
        "arn": arn,
        "version": version.group(1),
        "fetched": fetched.isoformat(),
        "document": json.loads(text),
    }


def _get(url: str) -> bytes:
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if not url.startswith("https://"):
        raise ValueError(f"refusing a non-HTTPS URL: {url}")
    with urllib.request.urlopen(url, timeout=60, context=context) as response:  # noqa: S310
        body: bytes = response.read()
    return body


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """Download, compare and write the records; print what changed."""
    parser = argparse.ArgumentParser(prog="python -m tools.identity_refresh")
    parser.add_argument("--dry-run", action="store_true", help="print the changes only")
    args = parser.parse_args(argv)
    today = date.today()
    catalog = build_catalog(lambda url: json.loads(_get(url)), today)
    catalog_path = DATA / "catalog.json"
    old = json.loads(catalog_path.read_text(encoding="utf-8")) if catalog_path.exists() else None
    for line in diff_summary(old, catalog):
        sys.stdout.write(f"{line}\n")
    records = {
        name: parse_managed_page(_get(url).decode("utf-8"), arn, today)
        for name, (arn, url) in MANAGED_PAGES.items()
    }
    for name, record in records.items():
        sys.stdout.write(f"{name} {record['version']}\n")
    if not args.dry_run:
        _write(catalog_path, catalog)
        for name, record in records.items():
            _write(DATA / "managed" / f"{name}.json", record)
    return 0


if __name__ == "__main__":
    sys.exit(main())
