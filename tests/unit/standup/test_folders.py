# SPDX-License-Identifier: Apache-2.0
"""Projects found in folders (spec 009, FR-023; research R12)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from opscout.adapters.git_log import GitLog
from opscout.core.config import Standup, StandupProject
from opscout.core.standup import Project, Repository
from opscout.services.standup import effective_projects

GIT = shutil.which("git")


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 009."""
    return pytest.mark.spec("009", requirement)


def clean() -> dict[str, str]:
    """The environment without git's own variables, which a git hook sets."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def clone(path: Path, remote: str | None) -> None:
    path.mkdir(parents=True)
    assert GIT is not None
    subprocess.run([GIT, "init", "-q", str(path)], check=True, env=clean())  # noqa: S603
    if remote:
        subprocess.run(  # noqa: S603
            [GIT, "-C", str(path), "remote", "add", "origin", remote], check=True, env=clean()
        )


@pytest.mark.skipif(GIT is None, reason="needs git")
@spec("FR-023")
def test_repositories_in_a_folder_are_found_with_their_bitbucket_remote(tmp_path: Path) -> None:
    root = tmp_path / "work"
    clone(root / "example-api", "git@bitbucket.org:example-workspace/example-api.git")
    clone(
        root / "group" / "Example_Web",
        "https://dev@bitbucket.org/example-workspace/example-web.git",
    )
    clone(root / "group" / "tool", "git@github.com:example/tool.git")
    clone(root / "a" / "b" / "c" / "too-deep", None)
    clone(root / ".hidden" / "secret-repo", None)
    clone(root / "node_modules" / "dep", None)
    clone(root / "example-api" / "nested", None)  # inside a repository: not descended
    found = sorted(GitLog().repositories(root), key=lambda r: r.path)
    assert [(Path(r.path).relative_to(root).as_posix(), r.bitbucket) for r in found] == [
        ("example-api", "example-workspace/example-api"),
        ("group/Example_Web", "example-workspace/example-web"),
        ("group/tool", None),
    ]


@spec("FR-023")
def test_effective_projects_merge_names_and_let_explicit_ones_win() -> None:
    standup = Standup(
        identities=["dev@example.com"],
        folders=["/opt/example/src"],
        projects={"example-web": StandupProject(paths=["/opt/elsewhere/web"])},
    )
    found = [
        Repository("/opt/example/src/example-api", "example-workspace/example-api"),
        Repository("/opt/example/old/example-api", "example-workspace/example-api"),
        Repository("/opt/example/src/Example_Web", "example-workspace/example-web"),
        Repository("/opt/example/src/2fa-tool", None),
    ]
    projects = effective_projects(standup, found)
    assert projects["example-api"] == Project(
        ("/opt/example/old/example-api", "/opt/example/src/example-api"),
        ("example-workspace/example-api",),
    )
    assert projects["example-web"] == Project(("/opt/elsewhere/web",))
    assert projects["repo-2fa-tool"] == Project(("/opt/example/src/2fa-tool",))


@pytest.mark.skipif(GIT is None, reason="needs git")
@spec("FR-023")
def test_a_worktree_joins_its_main_repository(tmp_path: Path) -> None:
    root = tmp_path / "work"
    main = root / "example-api"
    clone(main, "git@bitbucket.org:example-workspace/example-api.git")
    assert GIT is not None
    env_commit = [GIT, "-C", str(main), "-c", "user.email=dev@example.com", "-c", "user.name=Dev"]
    subprocess.run(  # noqa: S603
        [*env_commit, "commit", "-q", "--allow-empty", "-m", "init"], check=True, env=clean()
    )
    worktree = root / "example-api-hotfix"
    subprocess.run(  # noqa: S603
        [GIT, "-C", str(main), "worktree", "add", "-q", str(worktree)], check=True, env=clean()
    )
    found = GitLog().repositories(root)
    by_path = {Path(r.path).name: r for r in found}
    assert set(by_path) == {"example-api", "example-api-hotfix"}
    assert Path(by_path["example-api-hotfix"].main or "").resolve() == main.resolve()
    projects = effective_projects(
        Standup(identities=["dev@example.com"], folders=[str(root)]), found
    )
    assert list(projects) == ["example-api"]
    assert len(projects["example-api"].paths) == 2


@spec("FR-023")
def test_a_repository_with_many_worktrees_is_one_project() -> None:
    main = "/opt/example/src/example-api"
    found = [Repository(main, "example-workspace/example-api")] + [
        Repository(f"/opt/example/src/example-api-wt{n}", "example-workspace/example-api", main)
        for n in range(17)
    ]
    projects = effective_projects(
        Standup(identities=["dev@example.com"], folders=["/opt/example/src"]), found
    )
    assert list(projects) == ["example-api"]
    assert len(projects["example-api"].paths) == 18
    assert projects["example-api"].repositories == ("example-workspace/example-api",)


@spec("FR-023")
def test_a_listed_project_claims_its_paths_and_repositories_from_the_found_ones() -> None:
    standup = Standup(
        identities=["dev@example.com"],
        folders=["/opt/example/src"],
        projects={
            "platform": StandupProject(
                paths=["/opt/example/src/example-api"],
                repositories=["example-workspace/example-web"],
            )
        },
    )
    found = [
        Repository("/opt/example/src/example-api", "example-workspace/example-api"),
        Repository("/opt/example/src/example-web", "example-workspace/example-web"),
        Repository("/opt/example/src/example-ops", None),
    ]
    projects = effective_projects(standup, found)
    assert sorted(projects) == ["example-ops", "platform"]


@pytest.mark.skipif(GIT is None, reason="needs git")
@spec("FR-023")
def test_discovery_ignores_git_variables_set_by_a_git_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clone(tmp_path / "work" / "example-api", "git@bitbucket.org:example-workspace/example-api.git")
    elsewhere = tmp_path / "elsewhere"
    monkeypatch.setenv("GIT_DIR", str(elsewhere / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", ".git/index")
    [found] = GitLog().repositories(tmp_path / "work")
    assert found.bitbucket == "example-workspace/example-api"
