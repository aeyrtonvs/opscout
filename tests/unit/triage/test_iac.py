# SPDX-License-Identifier: Apache-2.0
"""Infrastructure code, confined to the configured clones (spec 012, FR-012, FR-013; R6)."""

from collections.abc import Callable
from pathlib import Path

import pytest

from opscout.adapters.local_files import LocalFiles
from opscout.core.config import Configuration
from opscout.core.tools import ErrorReason, ToolError
from opscout.services import iac
from opscout.services.config import parse_config
from tests.unit.triage.fakes import MemoryFiles

INFRA = "/srv/example/infra"
SHARED = "/srv/example/shared"
ALARMS = (
    'resource "aws_cloudwatch_metric_alarm" "api_5xx" {\n'
    '  alarm_name = "example-api-5xx"\n'
    "  threshold = 80\n"
    "}\n"
)


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 012."""
    return pytest.mark.spec("012", requirement)


def config(clones: str = "") -> Configuration:
    triage = clones or (
        f"    - {{name: example-infra, path: {INFRA}, environments: [example-prod]}}\n"
        f"    - {{name: example-shared, path: {SHARED}}}\n"
    )
    return parse_config(
        (
            "schema_version: 1\naws:\n  environments:\n"
            "    - {name: example-prod, account_id: '123456789012', profile: p, "
            "regions: [us-east-1]}\n"
            "    - {name: example-dev, account_id: '000000000000', profile: q, "
            f"regions: [us-east-1]}}\ntriage:\n  infrastructure:\n{triage}"
        ).encode(),
        "config.yaml",
    )


def files() -> MemoryFiles:
    return MemoryFiles(
        roots={
            INFRA: {
                "alarms.tf": ALARMS,
                "modules/api/main.tf": 'name = "example-api-5xx-dashboard"\n',
                ".git/config": "example-api-5xx in git config\n",
                ".terraform/cache.tf": "example-api-5xx cached\n",
                "prod.tfstate": "example-api-5xx in state\n",
                "prod.tfstate.backup": "example-api-5xx in state\n",
                ".env": "EXAMPLE_API_5XX=1\n",
                ".env.prod": "EXAMPLE_API_5XX=1\n",
                "deploy.pem": "example-api-5xx key\n",
                "tls.key": "example-api-5xx key\n",
                "logo.png": b"\x89PNG example-api-5xx",
                "escape.tf": "example-api-5xx outside\n",
                ".ENV": "EXAMPLE_API_5XX=1\n",
                ".envrc": "export EXAMPLE_API_5XX=1\n",
                ".GIT/config": "example-api-5xx in git config\n",
                "terraform.TFSTATE": "example-api-5xx in state\n",
                "prod.auto.tfvars": 'example_api_5xx_password = "x"\n',
                "prod.tfvars.json": '{"example-api-5xx": "x"}\n',
                "id_ed25519": "example-api-5xx key\n",
                "README": "example-api-5xx without a suffix\n",
            },
            SHARED: {"shared.tf": "# EXAMPLE-API-5XX is shared\n"},
        },
        links={INFRA: {"escape.tf": "../outside/secrets.tf"}},
    )


@spec("FR-013")
def test_search_finds_a_literal_in_the_environments_clones_first() -> None:
    data = iac.search(config(), files(), "Example-API-5xx", environment="example-prod", clone=None)
    assert [(m["path"], m["line"]) for m in data["matches"]] == [
        ("example-infra/alarms.tf", 2),
        ("example-infra/modules/api/main.tf", 1),
        ("example-shared/shared.tf", 1),
    ]
    assert data["matches"][0]["text"] == 'alarm_name = "example-api-5xx"'
    assert data["searched"] == ["example-infra", "example-shared"]
    assert data["missing"] == []


@spec("FR-013")
def test_a_clone_for_another_environment_is_not_searched() -> None:
    data = iac.search(config(), files(), "example-api-5xx", environment="example-dev", clone=None)
    assert data["searched"] == ["example-shared"]


@spec("FR-013")
def test_one_clone_by_name_and_missing_clones() -> None:
    data = iac.search(config(), files(), "shared", environment=None, clone="example-shared")
    assert data["searched"] == ["example-shared"]
    clones = (
        "    - {name: example-infra, path: /srv/example/absent}\n"
        f"    - {{name: example-shared, path: {SHARED}}}\n"
    )
    data = iac.search(config(clones), files(), "shared", environment=None, clone=None)
    assert data["missing"] == ["example-infra"]
    with pytest.raises(ToolError) as refused:
        iac.search(config(), files(), "x1", environment=None, clone="nowhere")
    assert refused.value.reason is ErrorReason.INVALID_INPUT


@spec("FR-012")
def test_without_clones_the_tools_say_not_configured() -> None:
    bare = parse_config(b"schema_version: 1\n", "config.yaml")
    calls: list[Callable[[], object]] = [
        lambda: iac.search(bare, files(), "example", environment=None, clone=None),
        lambda: iac.read(bare, files(), "example-infra/alarms.tf", 1, 3),
        lambda: iac.search(None, files(), "example", environment=None, clone=None),
    ]
    for call in calls:
        with pytest.raises(ToolError) as refused:
            call()
        assert refused.value.reason is ErrorReason.NOT_CONFIGURED


@spec("FR-013")
def test_matches_are_capped_at_fifty() -> None:
    many = MemoryFiles(roots={INFRA: {"big.tf": "example\n" * 80}, SHARED: {}})
    data = iac.search(config(), many, "example", environment=None, clone=None)
    assert len(data["matches"]) == 50
    assert data["more"] is True


@spec("FR-013")
def test_read_returns_numbered_lines() -> None:
    data = iac.read(config(), files(), "example-infra/alarms.tf", 2, 3)
    assert data["path"] == "example-infra/alarms.tf"
    assert data["lines"] == [
        {"line": 2, "text": '  alarm_name = "example-api-5xx"'},
        {"line": 3, "text": "  threshold = 80"},
    ]
    assert data["total_lines"] == 4


@spec("FR-013")
@pytest.mark.parametrize(
    ("path", "start", "end"),
    [
        ("example-infra/../shared/shared.tf", 1, 2),
        ("/etc/passwd", 1, 2),
        ("example-infra/escape.tf", 1, 2),
        ("example-infra/.git/config", 1, 2),
        ("example-infra/.terraform/cache.tf", 1, 2),
        ("example-infra/prod.tfstate", 1, 2),
        ("example-infra/prod.tfstate.backup", 1, 2),
        ("example-infra/.env", 1, 2),
        ("example-infra/.env.prod", 1, 2),
        ("example-infra/deploy.pem", 1, 2),
        ("example-infra/tls.key", 1, 2),
        ("example-infra/logo.png", 1, 2),
        ("example-infra/.ENV", 1, 2),
        ("example-infra/.envrc", 1, 2),
        ("example-infra/.GIT/config", 1, 2),
        ("example-infra/terraform.TFSTATE", 1, 2),
        ("example-infra/prod.auto.tfvars", 1, 2),
        ("example-infra/prod.tfvars.json", 1, 2),
        ("example-infra/id_ed25519", 1, 2),
        ("example-infra/README", 1, 2),
        ("nowhere/alarms.tf", 1, 2),
        ("example-infra", 1, 2),
        ("example-infra/alarms.tf", 3, 2),
        ("example-infra/alarms.tf", 1, 201),
        ("example-infra/absent.tf", 1, 2),
    ],
)
def test_read_refuses(path: str, start: int, end: int) -> None:
    with pytest.raises(ToolError) as refused:
        iac.read(config(), files(), path, start, end)
    assert refused.value.reason is ErrorReason.INVALID_INPUT


@spec("FR-013")
def test_search_never_returns_skipped_or_escaping_files() -> None:
    data = iac.search(config(), files(), "example-api-5xx", environment=None, clone=None)
    paths = {m["path"] for m in data["matches"]}
    assert not paths & {
        "example-infra/.git/config",
        "example-infra/.terraform/cache.tf",
        "example-infra/prod.tfstate",
        "example-infra/prod.tfstate.backup",
        "example-infra/.env",
        "example-infra/.env.prod",
        "example-infra/deploy.pem",
        "example-infra/tls.key",
        "example-infra/logo.png",
        "example-infra/escape.tf",
        "example-infra/.ENV",
        "example-infra/.envrc",
        "example-infra/.GIT/config",
        "example-infra/terraform.TFSTATE",
        "example-infra/prod.auto.tfvars",
        "example-infra/prod.tfvars.json",
        "example-infra/id_ed25519",
        "example-infra/README",
    }


@spec("FR-013")
def test_the_local_adapter_confines_reads_to_the_clone(tmp_path: Path) -> None:
    clone, outside = tmp_path / "clone", tmp_path / "outside"
    (clone / ".git").mkdir(parents=True)
    outside.mkdir()
    (clone / "alarms.tf").write_text(ALARMS, encoding="utf-8")
    (clone / ".git" / "HEAD").write_text("ref", encoding="utf-8")
    (clone / "bin.dat").write_bytes(b"\x00\x01example")
    (outside / "secret.tf").write_text("outside", encoding="utf-8")
    (clone / "link.tf").symlink_to(outside / "secret.tf")
    reader = LocalFiles()
    root = str(clone)

    assert reader.exists(root)
    assert not reader.exists(str(tmp_path / "absent"))
    assert set(reader.files(root)) == {"alarms.tf", "bin.dat", "link.tf"}
    assert reader.resolve(root, "alarms.tf") == "alarms.tf"
    assert reader.resolve(root, "link.tf") is None
    assert reader.resolve(root, "../outside/secret.tf") is None
    assert reader.read_text(root, "alarms.tf") == ALARMS
    assert reader.read_text(root, "bin.dat") is None
    configured = config(f"    - {{name: example-infra, path: {clone}}}\n")
    data = iac.search(configured, reader, "threshold", environment=None, clone=None)
    assert [(m["path"], m["line"]) for m in data["matches"]] == [("example-infra/alarms.tf", 3)]


@spec("FR-013")
def test_infrastructure_results_are_redacted_like_every_result() -> None:
    import dataclasses

    from opscout.services.tools.runtime import run_tool
    from tests.unit.mcp.fakes import FakeGateway, tool_context

    leaky = MemoryFiles(
        roots={
            INFRA: {"db.tf": 'password = "hunter2-example-value"\nengine = "postgres"\n'},
            SHARED: {},
        }
    )
    configured = config()
    context = dataclasses.replace(
        tool_context(FakeGateway()), config_loader=lambda: configured, files=leaky
    )
    failed, result = run_tool(
        "read_iac", {"path": "example-infra/db.tf", "start": 1, "end": 2}, context
    )
    assert not failed, result
    assert "hunter2" not in str(result)
    assert result["redacted"] == {"credential": 1}
    failed, result = run_tool("search_iac", {"pattern": "password"}, context)
    assert not failed
    assert "hunter2" not in str(result)


@spec("FR-013")
def test_the_local_adapter_ignores_case_like_the_file_system(tmp_path: Path) -> None:
    clone = tmp_path / "clone"
    (clone / ".GIT").mkdir(parents=True)
    (clone / "MOD").mkdir()
    (clone / ".GIT" / "config").write_text("threshold in git\n", encoding="utf-8")
    (clone / ".ENV").write_text("threshold=1\n", encoding="utf-8")
    (clone / "Prod.TFSTATE").write_text("threshold in state\n", encoding="utf-8")
    (clone / "prod.auto.tfvars").write_text('threshold_secret = "x"\n', encoding="utf-8")
    (clone / "alarms.TF").write_text("threshold = 80\n", encoding="utf-8")
    configured = config(f"    - {{name: example-infra, path: {clone}}}\n")
    reader = LocalFiles()
    data = iac.search(configured, reader, "threshold", environment=None, clone=None)
    assert [m["path"] for m in data["matches"]] == ["example-infra/alarms.TF"]
    for path in (
        "example-infra/.ENV",
        "example-infra/MOD/../.ENV",
        "example-infra/.GIT/config",
        "example-infra/Prod.TFSTATE",
        "example-infra/prod.auto.tfvars",
    ):
        with pytest.raises(ToolError):
            iac.read(configured, reader, path, 1, 1)
