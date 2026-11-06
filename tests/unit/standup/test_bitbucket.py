# SPDX-License-Identifier: Apache-2.0
"""The user's pull requests from Bitbucket Cloud (spec 009, FR-006, FR-014; research R3).

A fake opener serves hand-written responses that follow Bitbucket's documented shapes.
"""

import base64
import email.message
import io
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from opscout.adapters.bitbucket import BitbucketCloud
from opscout.core.standup import SourceError
from opscout.services.standup import window_for
from tests.unit.chat.fakes import TOKEN_SENTINEL
from tests.unit.standup.fakes import at

SAMPLES = Path(__file__).parent / "samples" / "bitbucket"
WINDOW = window_for(at(5, 9, 45), ["mon", "tue", "wed", "thu", "fri"])
REPO = "example-workspace/example-api"
ME = "{eeeeeeee-0000-4000-8000-eeeeeeeee001}"


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 009."""
    return pytest.mark.spec("009", requirement)


def sample(name: str) -> bytes:
    return (SAMPLES / name).read_bytes()


@dataclass
class FakeOpener:
    """Serves samples by URL; records each request; may fail with HTTP errors in turn."""

    requests: list[urllib.request.Request] = field(default_factory=list)
    errors: list[int] = field(default_factory=list)

    def __call__(self, request: urllib.request.Request, timeout: float) -> io.BytesIO:
        self.requests.append(request)
        assert timeout == 20
        if self.errors:
            code = self.errors.pop(0)
            headers = email.message.Message()
            if code == 429:
                headers["Retry-After"] = "3"
            raise urllib.error.HTTPError(
                request.full_url, code, "error", headers, io.BytesIO(sample("error_401.json"))
            )
        url = urllib.parse.urlparse(request.full_url)
        query = urllib.parse.parse_qs(url.query)
        path = url.path
        if path.endswith("/user"):
            return io.BytesIO(sample("user.json"))
        if path.endswith("/pullrequests/39/commits"):
            return io.BytesIO(sample("commits_39.json"))
        if path.endswith("/pullrequests/39/comments"):
            return io.BytesIO(sample("comments_39.json"))
        if "page" in query:
            return io.BytesIO(sample("open_page2.json"))
        q = query.get("q", [""])[0]
        if "reviewers.uuid" in q:
            return io.BytesIO(sample("reviews.json"))
        if 'state="OPEN"' in q:
            return io.BytesIO(sample("open.json"))
        return io.BytesIO(sample("closed.json"))


def host(opener: Any, slept: list[float] | None = None, clock: Any = None) -> BitbucketCloud:
    """A host whose clock, unless given, moves only when it sleeps."""
    waits = slept if slept is not None else []
    return BitbucketCloud(
        login="dev@example.com",
        token=lambda: TOKEN_SENTINEL,
        opener=opener,
        sleep=waits.append,
        clock=clock or (lambda: sum(waits)),
    )


@spec("FR-006")
def test_closed_open_and_waiting_pull_requests() -> None:
    opener = FakeOpener()
    bitbucket = host(opener)
    closed = bitbucket.closed(REPO, WINDOW)
    assert [(p.number, p.state) for p in closed] == [(41, "MERGED")]
    opened = bitbucket.open(REPO)
    assert sorted(p.number for p in opened) == [37, 39, 42]
    rename = next(p for p in opened if p.number == 39)
    assert rename.participants[0].state == "changes_requested"
    assert rename.user_activity == (at(4, 2, 30),)  # the user's commit after the request
    assert next(p for p in opened if p.number == 42).user_activity == ()
    waiting = bitbucket.reviews_waiting(REPO)
    assert [p.number for p in waiting] == [55]
    paths = [urllib.parse.urlparse(r.full_url).path for r in opener.requests]
    assert paths.count("/2.0/user") == 1


@spec("FR-006")
def test_the_queries() -> None:
    opener = FakeOpener()
    bitbucket = host(opener)
    bitbucket.closed(REPO, WINDOW)
    bitbucket.open(REPO)
    queries = [
        urllib.parse.parse_qs(urllib.parse.urlparse(r.full_url).query) for r in opener.requests
    ]
    closed = next(q for q in queries if "updated_on" in q.get("q", [""])[0])
    assert closed["q"][0] == (
        f'author.uuid="{ME}" AND updated_on>={WINDOW.start.isoformat()}'
        f" AND updated_on<{WINDOW.end.isoformat()}"
    )
    assert closed["state"] == ["MERGED", "DECLINED"]
    assert closed["fields"] == ["+values.participants"]
    opened = next(q for q in queries if 'state="OPEN"' in q.get("q", [""])[0])
    assert opened["q"][0] == f'author.uuid="{ME}" AND state="OPEN"'
    assert "updated_on" not in opened["q"][0]  # all open ones: an old one is a blocker


@spec("FR-014")
def test_only_gets_with_basic_auth_and_the_token_never_shown() -> None:
    opener = FakeOpener()
    bitbucket = host(opener)
    bitbucket.open(REPO)
    assert {r.get_method() for r in opener.requests} == {"GET"}
    expected = base64.b64encode(f"dev@example.com:{TOKEN_SENTINEL}".encode()).decode()
    assert all(r.get_header("Authorization") == f"Basic {expected}" for r in opener.requests)
    rejected = host(FakeOpener(errors=[401]))
    with pytest.raises(SourceError) as error:
        rejected.open(REPO)
    assert "opscout secret set bitbucket_token" in str(error.value)
    assert TOKEN_SENTINEL not in str(error.value)
    with pytest.raises(SourceError, match=r"read:user:bitbucket"):
        host(FakeOpener(errors=[403])).open(REPO)  # the first call: who the token is
    bitbucket = host(FakeOpener())
    bitbucket.open(REPO)
    bitbucket._opener = FakeOpener(errors=[403])
    with pytest.raises(SourceError, match=r"read:pullrequest:bitbucket and read:repository"):
        bitbucket.open(REPO)


@spec("FR-008")
def test_a_repository_not_found_is_that_repository_s_error_only() -> None:
    from opscout.core.standup import RepositoryError

    bitbucket = host(FakeOpener())
    bitbucket.open(REPO)
    bitbucket._opener = FakeOpener(errors=[404])
    with pytest.raises(RepositoryError, match=r"not found, or the token has no access \(404\)"):
        bitbucket.open(REPO)


@spec("FR-006")
def test_pages_are_followed_up_to_five() -> None:
    opener = FakeOpener()
    host(opener).open(REPO)
    pages = [r for r in opener.requests if "page=2" in r.full_url]
    assert len(pages) == 1


@spec("FR-008")
def test_rate_limits_wait_as_asked_and_a_slow_host_gives_up() -> None:
    slept: list[float] = []
    assert host(FakeOpener(errors=[429]), slept).reviews_waiting(REPO)
    assert slept == [3.0]
    many = FakeOpener(errors=[429] * 30)
    with pytest.raises(SourceError, match="60 s"):
        host(many, []).reviews_waiting(REPO)

    def offline(request: urllib.request.Request, timeout: float) -> Any:
        raise urllib.error.URLError("offline")

    nowhere: list[float] = []
    with pytest.raises(SourceError, match="could not be reached"):
        BitbucketCloud(
            login="dev@example.com",
            token=lambda: TOKEN_SENTINEL,
            opener=offline,
            sleep=nowhere.append,
        ).open(REPO)


@spec("FR-008")
def test_the_source_has_one_time_budget_for_every_request() -> None:
    now = [0.0]

    def clock() -> float:
        now[0] += 25.0  # each request seems to take 25 s
        return now[0]

    bitbucket = host(FakeOpener(), clock=clock)
    bitbucket.reviews_waiting(REPO)  # two requests: 50 s so far
    with pytest.raises(SourceError, match="longer than 60 s"):
        bitbucket.reviews_waiting(REPO)


@spec("FR-008")
def test_an_unexpected_answer_is_a_source_error() -> None:
    def odd(request: urllib.request.Request, timeout: float) -> io.BytesIO:
        if request.full_url.endswith("/user"):
            return io.BytesIO(sample("user.json"))
        return io.BytesIO(b'{"values": [{"title": "no id"}]}')

    with pytest.raises(SourceError, match="unexpected"):
        host(odd).open(REPO)

    class Soon(FakeOpener):
        def __call__(self, request: urllib.request.Request, timeout: float) -> io.BytesIO:
            if not self.requests:
                self.requests.append(request)
                headers = email.message.Message()
                headers["Retry-After"] = "soon"
                raise urllib.error.HTTPError(request.full_url, 429, "x", headers, io.BytesIO(b""))
            return super().__call__(request, timeout)

    slept: list[float] = []
    assert host(Soon(), slept).reviews_waiting(REPO)
    assert slept == [5.0]


@spec("FR-006")
def test_reviews_the_user_approved_are_not_waiting() -> None:
    assert [p.number for p in host(FakeOpener()).reviews_waiting(REPO)] == [55]


@spec("FR-014")
def test_a_next_link_off_the_api_is_not_followed() -> None:
    opener = FakeOpener()

    def leading_away(request: urllib.request.Request, timeout: float) -> io.BytesIO:
        if "reviewers.uuid" in request.full_url:
            opener.requests.append(request)
            page = json.loads(sample("reviews.json"))
            page["next"] = "https://elsewhere.example.com/collect"
            return io.BytesIO(json.dumps(page).encode())
        return opener(request, timeout)

    host(leading_away).reviews_waiting(REPO)
    assert not any("elsewhere" in r.full_url for r in opener.requests)
