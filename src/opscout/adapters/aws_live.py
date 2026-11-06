# SPDX-License-Identifier: Apache-2.0
"""The live AWS gateway, through boto3 (spec 011, research R2, R3, R7, R8).

Two guards keep a tool to its declared actions (FR-007): ``call`` refuses an undeclared
action up front, and a botocore ``before-parameter-build`` handler refuses any operation
outside the current call's declarations before the request is built or signed, even when
code reaches a client another way. Sessions and clients are created once, under a lock,
because a boto3 ``Session`` is not thread-safe and tools run in parallel threads.
"""

import math
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any, Final

import boto3
from botocore import xform_name
from botocore.config import Config
from botocore.exceptions import (
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    NoCredentialsError,
    ParamValidationError,
    ProfileNotFound,
    ReadTimeoutError,
    SSOTokenLoadError,
    TokenRetrievalError,
    UnauthorizedSSOTokenError,
)

from opscout.core.aws import client_for, iam_action
from opscout.core.config import AwsEnvironment
from opscout.core.tools import ErrorReason, ToolError

CONNECT_TIMEOUT: Final = 5
READ_TIMEOUT: Final = 20
GRACE: Final = 10
"""How far past the deadline a call in flight may run (research R7)."""

_THROTTLING: Final = frozenset(
    {
        "Throttling",
        "ThrottlingException",
        "ThrottledException",
        "RequestThrottled",
        "RequestThrottledException",
        "RequestLimitExceeded",
        "TooManyRequestsException",
        "SlowDown",
        "PriorRequestNotComplete",
        "EC2ThrottledException",
    }
)
_INVALID: Final = ("Validation", "InvalidParameter", "MalformedQuery", "InvalidQuery")

SessionFactory = Callable[[str], Any]


def _profile_session(profile: str) -> Any:
    return boto3.session.Session(profile_name=profile)


def map_error(error: Exception, environment: AwsEnvironment, action: str) -> ToolError:
    """Map a botocore error to the tool error users see (research R8).

    Raises the error itself when it is not one of botocore's.
    """
    profile = environment.profile
    if isinstance(error, ToolError):
        return error
    if isinstance(error, ProfileNotFound):
        return ToolError(ErrorReason.PROFILE_MISSING, f"profile {profile}")
    if isinstance(error, TokenRetrievalError | UnauthorizedSSOTokenError | SSOTokenLoadError):
        return ToolError(
            ErrorReason.LOGIN_EXPIRED,
            f"profile {profile}",
            fix=f"aws sso login --profile {profile}",
        )
    if isinstance(error, NoCredentialsError):
        return ToolError(ErrorReason.NO_CREDENTIALS, f"profile {profile}")
    if isinstance(
        error,
        EndpointConnectionError | ConnectTimeoutError | ReadTimeoutError | ConnectionClosedError,
    ):
        return ToolError(ErrorReason.UNREACHABLE, f"{action} in {environment.name}")
    if isinstance(error, ParamValidationError):
        return ToolError(ErrorReason.INVALID_INPUT, f"{action}: {error}")
    if isinstance(error, ClientError):
        code = str(error.response.get("Error", {}).get("Code", ""))
        message = str(error.response.get("Error", {}).get("Message", ""))
        if code in _THROTTLING:
            return ToolError(ErrorReason.THROTTLED, f"{action} in {environment.name}")
        if code.startswith(("AccessDenied", "UnauthorizedOperation", "UnauthorizedAccess")):
            return ToolError(ErrorReason.DENIED, f"{action} in {environment.name} ({code})")
        if "NotFound" in code or code.startswith("NoSuch"):
            return ToolError(ErrorReason.NOT_FOUND, f"{action}: {message}")
        if code.startswith(_INVALID):
            return ToolError(ErrorReason.INVALID_INPUT, f"{action}: {code}: {message}")
        return ToolError(ErrorReason.UNREACHABLE, f"{action} failed in AWS ({code})")
    raise error


class LiveGateway:
    """Calls AWS read actions with the profile of each environment."""

    def __init__(self, session_factory: SessionFactory = _profile_session) -> None:
        self._session_factory = session_factory
        self._sessions: dict[str, Any] = {}
        self._clients: dict[tuple[str, str, str, int], Any] = {}
        self._lock = threading.Lock()
        self._local = threading.local()

    @contextmanager
    def declared(self, allowed: frozenset[str]) -> Iterator[None]:
        """Within this block, this thread may call only ``allowed`` actions."""
        previous = getattr(self._local, "allowed", None)
        self._local.allowed = allowed
        try:
            yield
        finally:
            self._local.allowed = previous

    def _guard(self, model: Any, **_: Any) -> None:
        action = iam_action(model.service_model.service_name, model.name)
        allowed: frozenset[str] | None = getattr(self._local, "allowed", None)
        if allowed is None or action not in allowed:
            raise ToolError(ErrorReason.UNDECLARED_ACTION, action)

    def client(
        self, environment: AwsEnvironment, region: str, service: str, remaining: float
    ) -> Any:
        """The client for this environment, region and service, with a read timeout that
        fits the time ``remaining``; created once and shared across threads."""
        timeout = min(READ_TIMEOUT, 5 * math.ceil((max(remaining, 0) + GRACE) / 5))
        key = (environment.profile, region, service, timeout)
        with self._lock:
            if key not in self._clients:
                if environment.profile not in self._sessions:
                    self._sessions[environment.profile] = self._session_factory(environment.profile)
                client = self._sessions[environment.profile].client(
                    service,
                    region_name=region,
                    config=Config(
                        connect_timeout=CONNECT_TIMEOUT,
                        read_timeout=timeout,
                        retries={"mode": "standard", "total_max_attempts": 2},
                    ),
                )
                client.meta.events.register_first("before-parameter-build", self._guard)
                self._clients[key] = client
            return self._clients[key]

    def call(
        self,
        environment: AwsEnvironment,
        region: str,
        action: str,
        params: Mapping[str, Any],
        allowed: frozenset[str],
        remaining: float,
    ) -> Mapping[str, Any]:
        """Call one declared read action and return AWS's response (FR-007)."""
        if action not in allowed:
            raise ToolError(ErrorReason.UNDECLARED_ACTION, action)
        prefix, operation = action.split(":", 1)
        try:
            client = self.client(environment, region, client_for(prefix), remaining)
            with self.declared(allowed):
                response: Mapping[str, Any] = getattr(client, xform_name(operation))(**params)
        except Exception as error:  # every botocore error becomes a ToolError (R8)
            raise map_error(error, environment, action) from None
        return response
