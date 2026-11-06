# Contract: ports

New, in `opscout.core.standup`:

```python
class Transcripts(Protocol):
    def prompts(self, window: Window) -> Iterable[SessionPrompts]: ...  # cwd, session, prompts


class Commits(Protocol):
    def commits(self, path: Path, identities: Sequence[str], window: Window) -> list[Commit]: ...


class CodeHost(Protocol):
    def pull_requests(self, repository: str, window: Window) -> list[PullRequest]: ...
    def reviews_waiting(self, repository: str) -> list[PullRequest]: ...
```

Each raises `SourceError(reason)`; the services turn it into a missing source (FR-008). A
repository that is not found or not reachable with the token raises `RepositoryError`, a
`SourceError` for that repository only: the others are still read, and the source is named
missing with each such repository.

| Port | Adapter | Fake |
|---|---|---|
| `Transcripts` | `adapters.claude_transcripts.TranscriptFiles` (reads `<claude config>/projects/*/*.jsonl`) | sessions in memory |
| `Commits` | `adapters.git_log.GitLog` (read-only `git log`) | commits in memory; one test on a real temporary repository |
| `CodeHost` | `adapters.bitbucket.BitbucketCloud` (`urllib`, `truststore`, Basic auth with the stored token) | pull requests in memory; the adapter is tested on recorded, hand-written responses |

Changed, in `opscout.core.daemon` (spec 007): `RunProfile.validation_context`; `Start.prepare`;
`Preparation` (`Run` or `Ready`). The runner passes the context to `model_validate`.
