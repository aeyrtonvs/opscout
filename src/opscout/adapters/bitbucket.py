# SPDX-License-Identifier: Apache-2.0
"""BitbucketCloud: the user's pull requests, read with a read-only API token.

GET requests only, with HTTP Basic authentication (the account's login and an API token
with read scopes), through the operating system's certificates. Titles, states, times,
branches and review states are read; never descriptions, diffs or comment text
(spec 009, research R3). The token stays in this module.
"""

import base64
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime
from typing import IO, Any, Final

import truststore

from opscout.core.standup import Participant, PullRequest, RepositoryError, SourceError, Window

API: Final = "https://api.bitbucket.org/2.0"
TIMEOUT: Final = 20
SOURCE_SECONDS: Final = 60.0
PAGES: Final = 5
STORE_HINT: Final = "store a new one with opscout secret set bitbucket_token"
UNEXPECTED: Final = "Bitbucket sent an unexpected answer"

Opener = Callable[[urllib.request.Request, float], IO[bytes]]


def _context() -> ssl.SSLContext:
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def _open(request: urllib.request.Request, timeout: float) -> IO[bytes]:
    response: IO[bytes] = urllib.request.urlopen(  # noqa: S310  (a fixed https base)
        request, timeout=timeout, context=_context()
    )
    return response


def _time(value: object) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _seconds(value: object) -> float:
    """Return a Retry-After header's seconds; 5 when it is missing or not a number."""
    try:
        return max(0.0, float(str(value))) if value else 5.0
    except ValueError:
        return 5.0


class BitbucketCloud:
    """The ``CodeHost`` port on Bitbucket Cloud's REST API."""

    def __init__(
        self,
        login: str,
        token: Callable[[], str],
        opener: Opener = _open,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._login = login
        self._token = token
        self._opener = opener
        self._sleep = sleep
        self._clock = clock
        self._me: str | None = None
        self._started: float | None = None  # one time budget for the whole source

    def closed(self, repository: str, window: Window) -> list[PullRequest]:
        """Return the user's pull requests merged or declined in the window.

        Bitbucket gives no closing time in a list, so the last update stands for it: inside
        the window, never after it.
        """
        query = (
            f'author.uuid="{self._uuid()}" AND updated_on>={window.start.isoformat()}'
            f" AND updated_on<{window.end.isoformat()}"
        )
        found = self._list(repository, query, states=("MERGED", "DECLINED"))
        return [p for p in found if window.start <= p.updated < window.end]

    def open(self, repository: str) -> list[PullRequest]:
        """Return all the user's open pull requests, with what they did after a review."""
        found = self._list(repository, f'author.uuid="{self._uuid()}" AND state="OPEN"')
        return [self._with_activity(repository, request) for request in found]

    def reviews_waiting(self, repository: str) -> list[PullRequest]:
        """Return the open pull requests waiting on the user's review, not yet approved."""
        me = self._uuid()
        found = self._list(repository, f'reviewers.uuid="{me}" AND state="OPEN"')
        return [p for p in found if not any(q.user == me and q.approved for q in p.participants)]

    def _uuid(self) -> str:
        if self._me is None:
            answer = self._get(f"{API}/user", scope="read:user:bitbucket")
            if not isinstance(answer.get("uuid"), str):
                raise SourceError(UNEXPECTED)
            self._me = answer["uuid"]
        return self._me

    def _list(self, repository: str, query: str, states: tuple[str, ...] = ()) -> list[PullRequest]:
        params = [("q", query), *(("state", state) for state in states)]
        params.append(("fields", "+values.participants"))
        url: str | None = (
            f"{API}/repositories/{repository}/pullrequests?{urllib.parse.urlencode(params)}"
        )
        found: list[PullRequest] = []
        for _ in range(PAGES):
            if url is None:
                break
            page = self._get(url)
            try:
                found += [self._pull_request(repository, value) for value in page["values"]]
            except (KeyError, TypeError, ValueError):
                raise SourceError(UNEXPECTED) from None
            following = page.get("next")
            # The token goes only to the API: a next link anywhere else is not followed.
            url = (
                following
                if isinstance(following, str) and following.startswith(f"{API}/")
                else None
            )
        return found

    def _pull_request(self, repository: str, value: dict[str, Any]) -> PullRequest:
        participants = tuple(
            Participant(
                user=str(p.get("user", {}).get("uuid", "")),
                role=str(p.get("role", "")),
                approved=bool(p.get("approved")),
                state=p.get("state"),
                at=_time(p["participated_on"]) if p.get("participated_on") else None,
            )
            for p in value.get("participants", [])
        )
        return PullRequest(
            repository=repository,
            number=int(value["id"]),
            title=str(value.get("title", "")),
            state=str(value.get("state", "")),
            created=_time(value["created_on"]),
            updated=_time(value["updated_on"]),
            branch=str(value.get("source", {}).get("branch", {}).get("name", "")),
            participants=participants,
        )

    def _with_activity(self, repository: str, request: PullRequest) -> PullRequest:
        """Add when the user pushed or commented, for a pull request with changes requested."""
        if not any(p.state == "changes_requested" for p in request.participants):
            return request
        base = f"{API}/repositories/{repository}/pullrequests/{request.number}"
        me = self._uuid()
        commits = self._get(f"{base}/commits").get("values", [])
        comments = self._get(
            f"{base}/comments?{urllib.parse.urlencode({'q': f'user.uuid="{me}"'})}"
        ).get("values", [])
        try:
            times = [
                _time(c["date"])
                for c in commits
                if c.get("author", {}).get("user", {}).get("uuid") == me and c.get("date")
            ]
            times += [_time(c["created_on"]) for c in comments if c.get("created_on")]
        except (AttributeError, TypeError, ValueError):
            raise SourceError(UNEXPECTED) from None
        return PullRequest(**{**request.__dict__, "user_activity": tuple(sorted(times))})

    def _get(
        self,
        url: str,
        scope: str = "read:pullrequest:bitbucket and read:repository:bitbucket",
    ) -> dict[str, Any]:
        """GET a JSON document, waiting on rate limits within the source's time budget."""
        credentials = base64.b64encode(f"{self._login}:{self._token()}".encode()).decode()
        request = urllib.request.Request(  # noqa: S310  (a fixed https base)
            url,
            headers={"Authorization": f"Basic {credentials}", "Accept": "application/json"},
            method="GET",
        )
        if self._started is None:
            self._started = self._clock()
        while True:
            if self._clock() - self._started > SOURCE_SECONDS:
                raise SourceError(
                    f"Bitbucket took longer than {SOURCE_SECONDS:.0f} s; the rest was not read"
                )
            try:
                with self._opener(request, TIMEOUT) as response:
                    data = json.loads(response.read())
                if not isinstance(data, dict):
                    raise SourceError(UNEXPECTED)
                return data
            except urllib.error.HTTPError as error:
                error.close()  # its body is never read; release the connection
                if error.code == 401:
                    raise SourceError(f"Bitbucket rejected the token (401); {STORE_HINT}") from None
                if error.code == 403:
                    raise SourceError(
                        f"the Bitbucket token lacks a scope (403): it needs {scope}; create a "
                        f"new one with read:pullrequest:bitbucket, read:repository:bitbucket "
                        f"and read:user:bitbucket, then {STORE_HINT}"
                    ) from None
                if error.code == 404:
                    raise RepositoryError("not found, or the token has no access (404)") from None
                if error.code != 429:
                    raise SourceError(f"Bitbucket answered {error.code}") from None
                wait = _seconds(error.headers.get("Retry-After"))
                if self._clock() - self._started + wait > SOURCE_SECONDS:
                    raise SourceError("Bitbucket kept limiting the rate for 60 s") from None
                self._sleep(wait)
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
                raise SourceError(
                    f"Bitbucket could not be reached ({type(error).__name__})"
                ) from None
