# SPDX-License-Identifier: Apache-2.0
"""Gathering the window's facts from the three sources (spec 009, FR-007, FR-008, FR-021)."""

from datetime import timedelta
from pathlib import Path

import pytest

from opscout.core.config import StandupLimits
from opscout.core.standup import Commit, Participant, PullRequest, SessionPrompts
from opscout.services.standup import Sources, gather, is_blocker, window_for
from tests.unit.standup.fakes import (
    API,
    STANDUP,
    WEB,
    FakeCodeHost,
    FakeCommits,
    FakeTranscripts,
    at,
)

WEEK = ["mon", "tue", "wed", "thu", "fri"]
WINDOW = window_for(at(5, 9, 45), WEEK)  # Thursday: covers Wednesday 4
REPO = "example-workspace/example-api"


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 009."""
    return pytest.mark.spec("009", requirement)


def pull(number: int, title: str, created: int, *participants: Participant, state: str = "OPEN",
         activity: tuple[int, ...] = ()) -> PullRequest:  # fmt: skip
    return PullRequest(
        repository=REPO, number=number, title=title, state=state, created=at(created, 10),
        updated=at(4, 12), branch="feature/x", participants=participants,
        user_activity=tuple(at(day, 15) for day in activity),
    )  # fmt: skip


def reviewer(approved: bool = False, state: str | None = None, day: int = 3) -> Participant:
    return Participant("{reviewer}", "REVIEWER", approved, state, at(day, 18))


def sources(**kwargs: object) -> Sources:
    return Sources(
        transcripts=kwargs.get("transcripts", FakeTranscripts()),  # type: ignore[arg-type]
        commits=kwargs.get("commits", FakeCommits()),  # type: ignore[arg-type]
        code_host=kwargs.get("code_host", FakeCodeHost()),  # type: ignore[arg-type]
    )


@spec("FR-007")
def test_facts_by_project_then_time_with_ids_by_source() -> None:
    transcripts = FakeTranscripts(
        [
            SessionPrompts("s-web", f"{WEB}/app", ((at(4, 9), "Style the login form"),)),
            SessionPrompts(
                "s-api", API, ((at(4, 8), "Fix the export retry"), (at(4, 9), "Push it"))
            ),
        ]
    )
    commits = FakeCommits(
        {API: [Commit("a" * 40, at(4, 11), "refs/heads/feature/retry", "Retry export job")]}
    )
    host = FakeCodeHost(
        closed_prs={REPO: [pull(41, "Add export endpoint", 2, state="MERGED")]},
        open_prs={REPO: [pull(42, "Retry export job", 4, reviewer())]},
        reviews={REPO: [pull(55, "Teammate change", 4)]},
    )
    gathered = gather(
        STANDUP, WINDOW, sources(transcripts=transcripts, commits=commits, code_host=host), WEEK
    )
    lines = [(f.id, f.project, f.source, f.kind, f.text) for f in gathered.facts]
    assert lines == [
        ("s1", "example-api", "sessions", "done", "until 09:00: Fix the export retry / Push it"),
        ("c1", "example-api", "git", "done", "Retry export job (feature/retry)"),
        ("p1", "example-api", "bitbucket", "done", '"Add export endpoint" merged (example-api#41)'),
        ("p2", "example-api", "bitbucket", "open",
         '"Retry export job" open, no approval yet (example-api#42)'),
        ("r1", "example-api", "bitbucket", "open",
         'review requested: "Teammate change" (example-api#55)'),
        ("s2", "example-web", "sessions", "done", "Style the login form"),
    ]  # fmt: skip
    assert transcripts.roots == [[Path(API), Path(WEB)]]
    assert gathered.missing == {}


@spec("FR-007")
def test_each_cap_applies_and_what_was_cut_is_counted() -> None:
    many = tuple(
        (at(4, 8) + timedelta(minutes=n), f"prompt {n} " + "word " * 100) for n in range(30)
    )
    transcripts = FakeTranscripts([SessionPrompts("s", API, many)])
    standup = STANDUP.model_copy(
        update={"limits": StandupLimits(prompt_length=80, prompts_per_session=4)}
    )
    gathered = gather(standup, WINDOW, sources(transcripts=transcripts), WEEK)
    [fact] = gathered.facts
    span, _, text = fact.text.partition(": ")
    assert span == "until 08:29"  # the last prompt's time
    parts = text.split(" / ")
    assert len(parts) == 5  # the first two, a mark, the last two
    assert parts[2] == "(26 more)"
    assert parts[0].startswith("prompt 0 ")
    assert parts[-1].startswith("prompt 29 ")
    assert all(len(part) <= 80 for part in parts)
    assert parts[0].endswith("…")
    assert gathered.cut == {"prompts": 26}


@spec("FR-008")
def test_a_failing_source_is_named_and_the_others_still_gathered() -> None:
    commits = FakeCommits({API: [Commit("b" * 40, at(4, 11), "refs/heads/main", "Fix")]})
    host = FakeCodeHost(error="Bitbucket rejected the token (401); store a new one")
    transcripts = FakeTranscripts(error="no Claude Code transcripts at /example")
    gathered = gather(
        STANDUP, WINDOW, sources(transcripts=transcripts, commits=commits, code_host=host), WEEK
    )
    assert [f.id for f in gathered.facts] == ["c1"]
    assert gathered.missing == {
        "sessions": "no Claude Code transcripts at /example",
        "bitbucket": "Bitbucket rejected the token (401); store a new one",
    }
    failing = FakeCommits(failing={API})
    gathered = gather(STANDUP, WINDOW, sources(commits=failing), WEEK)
    assert gathered.missing == {"git": f"{API}: not a git repository"}


@spec("FR-009")
def test_every_text_is_redacted_and_counted() -> None:
    transcripts = FakeTranscripts(
        [SessionPrompts("s", API, ((at(4, 8), "Mail jane.doe@example.com about Example Corp"),))]
    )
    host = FakeCodeHost(open_prs={REPO: [pull(42, "Rotate AKIAEXAMPLEEXAMPLE12", 4, reviewer())]})
    gathered = gather(STANDUP, WINDOW, sources(transcripts=transcripts, code_host=host), WEEK)
    text = " ".join(f.text for f in gathered.facts)
    for value in ("jane.doe", "AKIA", "Example Corp"):
        assert value not in text
    assert dict(gathered.redactions) == {"email": 1, "deny-listed": 1, "credential": 1}


# The blocker rule (FR-021), on fixed clocks


@spec("FR-021")
def test_no_approval_after_one_full_working_day_is_a_blocker() -> None:
    opened_tuesday = pull(37, "Old cleanup", 3, reviewer())
    assert is_blocker(opened_tuesday, at(5, 9, 45), WEEK)  # all of Wednesday passed
    opened_wednesday = pull(42, "Retry", 4, reviewer())
    assert not is_blocker(opened_wednesday, at(5, 9, 45), WEEK)  # no full day yet
    friday = pull(43, "Friday", 6, reviewer())
    assert not is_blocker(friday, at(9, 9, 45), WEEK)  # the weekend is not a working day
    assert is_blocker(friday, at(10, 9, 45), WEEK)  # Monday passed
    approved = pull(37, "Old cleanup", 3, reviewer(approved=True, state="approved"))
    assert not is_blocker(approved, at(5, 9, 45), WEEK)


@spec("FR-021")
def test_changes_requested_then_answered_is_a_blocker() -> None:
    asked = reviewer(state="changes_requested", day=4)
    unanswered = pull(39, "Rename settings", 4, asked)
    assert not is_blocker(unanswered, at(5, 9, 45), WEEK)
    answered = pull(
        39, "Rename settings", 4, asked, activity=(4,)
    )  # the commit (15:00) came before the request (18:00)
    assert not is_blocker(answered, at(5, 9, 45), WEEK)
    answered_after = pull(
        39, "Rename settings", 4, reviewer(state="changes_requested", day=3), activity=(4,)
    )
    assert is_blocker(answered_after, at(5, 9, 45), WEEK)


@spec("FR-021")
def test_a_blocker_is_marked_in_the_facts() -> None:
    host = FakeCodeHost(
        open_prs={REPO: [pull(37, "Old cleanup", 2, reviewer()), pull(42, "Retry", 4, reviewer())]}
    )
    gathered = gather(STANDUP, WINDOW, sources(code_host=host), WEEK)
    kinds = {f.text.split('"')[1]: f.kind for f in gathered.facts}
    assert kinds == {"Old cleanup": "blocker", "Retry": "open"}
    blocker = next(f for f in gathered.facts if f.kind == "blocker")
    assert "waiting for review since" in blocker.text


@spec("FR-007")
def test_edges_of_the_gathering() -> None:
    from opscout.core.config import Standup, StandupProject

    only_repositories = Standup(
        identities=["dev@example.com"],
        projects={"example-api": StandupProject(repositories=[REPO])},
    )
    transcripts = FakeTranscripts()
    gathered = gather(only_repositories, WINDOW, sources(transcripts=transcripts), WEEK)
    assert transcripts.roots == []  # no path: sessions are not read at all
    assert gathered.facts == ()

    twice = Standup(
        identities=["dev@example.com"],
        projects={
            "example-api": StandupProject(paths=[API]),
            "example-web": StandupProject(paths=[WEB]),
        },
    )
    same = Commit("c" * 40, at(4, 9), "refs/remotes/origin/main", "Shared commit")
    commits = FakeCommits({API: [same], WEB: [same]})
    empty_session = SessionPrompts("s", API, ())
    gathered = gather(
        twice, WINDOW,
        Sources(transcripts=FakeTranscripts([empty_session]), commits=commits, code_host=None),
        WEEK,
    )  # fmt: skip
    assert [(f.id, f.text) for f in gathered.facts] == [("c1", "Shared commit (origin/main)")]


@spec("FR-007")
def test_the_pull_request_cap_keeps_open_work_first() -> None:
    standup = STANDUP.model_copy(update={"limits": StandupLimits(pull_requests=5)})
    closed = [pull(n, f"Closed {n}", 4, state="MERGED") for n in range(10)]
    opened = [pull(100, "Open one", 4, reviewer())]
    host = FakeCodeHost(closed_prs={REPO: closed}, open_prs={REPO: opened})
    gathered = gather(standup, WINDOW, sources(code_host=host), WEEK)
    assert len(gathered.facts) == 5
    assert any("Open one" in f.text for f in gathered.facts)
    assert gathered.cut == {"bitbucket": 6}


@spec("FR-021")
def test_review_states_in_words() -> None:
    approved = pull(46, "Approved", 4, reviewer(approved=True, state="approved"))
    asked = pull(47, "Asked", 4, reviewer(state="changes_requested", day=4))
    answered = pull(48, "Answered", 4, reviewer(state="changes_requested", day=3), activity=(4,))
    host = FakeCodeHost(open_prs={REPO: [approved, asked, answered]})
    texts = [f.text for f in gather(STANDUP, WINDOW, sources(code_host=host), WEEK).facts]
    assert '"Approved" open, approved (example-api#46)' in texts
    assert '"Asked" open, changes requested (example-api#47)' in texts
    assert '"Answered" open, changes requested, answered (example-api#48)' in texts
    merged = pull(49, "Merged", 1, state="MERGED")
    assert not is_blocker(merged, at(9, 9), WEEK)


@spec("FR-007")
def test_times_are_shown_in_the_window_s_local_time() -> None:
    from datetime import UTC

    late = at(4, 22).astimezone(UTC)  # transcripts and the code host give UTC
    transcripts = FakeTranscripts([SessionPrompts("s", API, ((late, "Late fix"),))])
    gathered = gather(STANDUP, WINDOW, sources(transcripts=transcripts), WEEK)
    [fact] = gathered.facts
    assert fact.at.utcoffset() == WINDOW.start.utcoffset()
    assert " 2026-11-04 22:00 sessions: " in fact.line()


@spec("FR-008")
def test_a_repository_that_cannot_be_read_is_named_and_the_others_still_gathered() -> None:
    standup = STANDUP.model_copy(
        update={
            "projects": {
                **STANDUP.projects,
                "example-web": STANDUP.projects["example-web"].model_copy(
                    update={"repositories": ["example-workspace/example-gone"]}
                ),
            }
        }
    )
    host = FakeCodeHost(
        open_prs={REPO: [pull(42, "Retry export job", 4)]},
        gone={"example-workspace/example-gone"},
    )
    gathered = gather(standup, WINDOW, sources(code_host=host), WEEK)
    assert [f.text for f in gathered.facts] == [
        '"Retry export job" open, no approval yet (example-api#42)'
    ]
    assert gathered.missing == {
        "bitbucket": "example-workspace/example-gone: not found, or the token has no access (404)"
    }


@spec("FR-004")
def test_a_session_fact_says_when_its_last_prompt_was() -> None:
    from datetime import UTC

    prompts = ((at(4, 8), "Fix the export retry"), (at(4, 15, 30).astimezone(UTC), "Push it"))
    transcripts = FakeTranscripts([SessionPrompts("s", API, prompts)])
    [fact] = gather(STANDUP, WINDOW, sources(transcripts=transcripts), WEEK).facts
    assert fact.at == at(4, 8)
    assert fact.text == "until 15:30: Fix the export retry / Push it"
    single = FakeTranscripts([SessionPrompts("s", API, prompts[:1])])
    [fact] = gather(STANDUP, WINDOW, sources(transcripts=single), WEEK).facts
    assert fact.text == "Fix the export retry"


@spec("FR-023")
def test_projects_come_from_folders_and_a_failing_folder_is_named() -> None:
    from opscout.core.config import Standup
    from opscout.core.standup import Repository

    standup = Standup(identities=["dev@example.com"], folders=["/opt/example/src", "/opt/gone"])
    commits = FakeCommits(
        {API: [Commit("c" * 40, at(4, 11), "refs/heads/main", "Retry export")]},
        failing={"/opt/gone"},
        found={"/opt/example/src": [Repository(API, None)]},
    )
    gathered = gather(standup, WINDOW, sources(commits=commits), WEEK)
    assert gathered.projects == ("example-api",)
    assert [(f.project, f.text) for f in gathered.facts] == [("example-api", "Retry export (main)")]
    assert gathered.missing == {"git": "/opt/gone: no such folder"}


@spec("FR-009")
def test_a_deny_listed_term_in_a_project_name_never_reaches_the_model() -> None:
    from opscout.core.config import Standup
    from opscout.core.standup import Repository

    path = "/opt/example/src/examplecorp-billing"
    standup = Standup(
        identities=["dev@example.com"], folders=["/opt/example/src"], redact=["ExampleCorp"]
    )
    commits = FakeCommits(
        {path: [Commit("d" * 40, at(4, 11), "refs/heads/main", "Bill")]},
        found={"/opt/example/src": [Repository(path, None)]},
    )
    gathered = gather(standup, WINDOW, sources(commits=commits), WEEK)
    assert gathered.projects == ("deny-listed-billing",)
    assert all("examplecorp" not in fact.line().lower() for fact in gathered.facts)
    assert gathered.redactions == {"deny-listed": 1}


@spec("FR-009")
def test_a_prompt_is_redacted_before_it_is_shortened() -> None:
    from opscout.core.config import StandupLimits

    standup = STANDUP.model_copy(update={"limits": StandupLimits(prompt_length=80)})
    long = "x" * 72 + "ExampleCorp rocks and more words after it"  # cut inside the term
    unbroken = "a" * 60 + "postgres://admin:hunter2pw@db.example.com/x"  # cut inside the URL
    transcripts = FakeTranscripts(
        [SessionPrompts("s", API, ((at(4, 8), long), (at(4, 8), unbroken)))]
    )
    [fact] = gather(standup, WINDOW, sources(transcripts=transcripts), WEEK).facts
    assert "Example" not in fact.text
    assert "postgres" not in fact.text
    assert "admin" not in fact.text


@spec("FR-021")
def test_unanswered_changes_wait_on_the_user_and_answered_ones_are_named_so() -> None:
    from opscout.services.standup import blocker_reason

    asked = reviewer(state="changes_requested", day=3)
    old_unanswered = pull(39, "Rename settings", 2, asked)
    assert blocker_reason(old_unanswered, at(5, 9, 45), WEEK) is None  # it waits on the user
    answered = pull(39, "Rename settings", 2, asked, activity=(4,))
    assert blocker_reason(answered, at(5, 9, 45), WEEK) == "changes requested, answered"
    waiting = pull(37, "Old cleanup", 2, reviewer())
    assert blocker_reason(waiting, at(5, 9, 45), WEEK) == "waiting for review since Monday 2"


@spec("FR-009")
def test_projects_that_redact_to_one_name_are_joined() -> None:
    from opscout.core.config import Standup, StandupProject

    standup = Standup(
        identities=["dev@example.com"],
        projects={
            "examplecorp-api": StandupProject(paths=["/opt/a"], repositories=["w/a"]),
            "example-corp-api": StandupProject(paths=["/opt/b"], repositories=["w/b"]),
        },
        redact=["Example Corp"],
    )
    commits = FakeCommits(
        {
            "/opt/a": [Commit("e" * 40, at(4, 11), "refs/heads/main", "A")],
            "/opt/b": [Commit("f" * 40, at(4, 12), "refs/heads/main", "B")],
        }
    )
    gathered = gather(standup, WINDOW, sources(commits=commits), WEEK)
    assert gathered.projects == ("deny-listed-api",)
    assert [f.project for f in gathered.facts] == ["deny-listed-api", "deny-listed-api"]
