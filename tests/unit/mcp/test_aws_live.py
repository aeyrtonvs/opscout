# SPDX-License-Identifier: Apache-2.0
"""The live AWS gateway: run-time guard, errors, retries, clients (spec 011, FR-007; R2, R8).

No network: sessions carry static fake credentials and every response is stubbed with
botocore's ``Stubber``.
"""

import threading
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from botocore.exceptions import (
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
    ParamValidationError,
    ProfileNotFound,
    SSOTokenLoadError,
    TokenRetrievalError,
    UnauthorizedSSOTokenError,
)
from botocore.stub import Stubber

from opscout.adapters.aws_live import LiveGateway, map_error
from opscout.core.config import AwsEnvironment
from opscout.core.tools import ErrorReason, ToolError

PROD = AwsEnvironment(
    name="example-prod", account_id="123456789012", profile="example-prod", regions=["us-east-1"]
)
DESCRIBE = "cloudwatch:DescribeAlarms"


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 011."""
    return pytest.mark.spec("011", requirement)


def _session(profile: str) -> boto3.session.Session:
    return boto3.session.Session(
        aws_access_key_id="AKIAEXAMPLEEXAMPLE12",
        aws_secret_access_key="example-secret-not-real",  # noqa: S106
        region_name="us-east-1",
    )


@pytest.fixture
def gateway() -> LiveGateway:
    return LiveGateway(session_factory=_session)


@pytest.fixture
def stubbed(gateway: LiveGateway) -> Iterator[Stubber]:
    client = gateway.client(PROD, "us-east-1", "cloudwatch", 40.0)
    with Stubber(client) as stubber:
        yield stubber


@spec("FR-007")
def test_an_undeclared_action_is_refused_before_anything_is_sent(
    gateway: LiveGateway, stubbed: Stubber
) -> None:
    stubbed.add_response("describe_alarms", {"MetricAlarms": []})

    with pytest.raises(ToolError) as error:
        gateway.call(PROD, "us-east-1", DESCRIBE, {}, frozenset({"cloudwatch:ListMetrics"}), 40.0)

    assert error.value.reason is ErrorReason.UNDECLARED_ACTION
    assert DESCRIBE in error.value.message
    with pytest.raises(AssertionError):
        stubbed.assert_no_pending_responses()  # the stubbed response was never consumed


@spec("FR-007")
def test_the_guard_also_stops_a_call_that_bypasses_the_pre_check(
    gateway: LiveGateway, stubbed: Stubber
) -> None:
    """A handler that reached a client another way still cannot call an undeclared action."""
    stubbed.add_response("describe_alarms", {"MetricAlarms": []})
    client = gateway.client(PROD, "us-east-1", "cloudwatch", 40.0)

    with gateway.declared(frozenset({"cloudwatch:ListMetrics"})), pytest.raises(ToolError):
        client.describe_alarms()


@spec("FR-007")
def test_a_declared_call_goes_through(gateway: LiveGateway, stubbed: Stubber) -> None:
    stubbed.add_response("describe_alarms", {"MetricAlarms": [{"AlarmName": "example-cpu"}]})

    response = gateway.call(PROD, "us-east-1", DESCRIBE, {}, frozenset({DESCRIBE}), 40.0)

    assert response["MetricAlarms"][0]["AlarmName"] == "example-cpu"
    stubbed.assert_no_pending_responses()


@spec("FR-004")
def test_a_throttled_call_is_reported_as_throttled(gateway: LiveGateway, stubbed: Stubber) -> None:
    """The one retry is botocore's (``total_max_attempts=2``, checked below): a stubbed
    response bypasses botocore's retry loop, so only the final mapping is tested here."""
    stubbed.add_client_error("describe_alarms", "ThrottlingException", http_status_code=400)

    with pytest.raises(ToolError) as error:
        gateway.call(PROD, "us-east-1", DESCRIBE, {}, frozenset({DESCRIBE}), 40.0)

    assert error.value.reason is ErrorReason.THROTTLED


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "m"}}, "DescribeAlarms")


@spec("FR-004")
@pytest.mark.parametrize(
    ("error", "reason", "fix"),
    [
        (ProfileNotFound(profile="example-prod"), ErrorReason.PROFILE_MISSING, "aws configure sso"),
        (
            TokenRetrievalError(provider="sso", error_msg="expired"),
            ErrorReason.LOGIN_EXPIRED,
            "aws sso login --profile example-prod",
        ),
        (
            UnauthorizedSSOTokenError(),
            ErrorReason.LOGIN_EXPIRED,
            "aws sso login --profile example-prod",
        ),
        (
            SSOTokenLoadError(error_msg="missing"),
            ErrorReason.LOGIN_EXPIRED,
            "aws sso login --profile example-prod",
        ),
        (NoCredentialsError(), ErrorReason.NO_CREDENTIALS, None),
        (EndpointConnectionError(endpoint_url="https://x"), ErrorReason.UNREACHABLE, None),
        (_client_error("ThrottlingException"), ErrorReason.THROTTLED, None),
        (_client_error("AccessDeniedException"), ErrorReason.DENIED, None),
        (_client_error("UnauthorizedOperation"), ErrorReason.DENIED, None),
        (_client_error("ResourceNotFoundException"), ErrorReason.NOT_FOUND, None),
        (_client_error("ValidationException"), ErrorReason.INVALID_INPUT, None),
        (_client_error("MalformedQueryException"), ErrorReason.INVALID_INPUT, None),
        (ParamValidationError(report="bad"), ErrorReason.INVALID_INPUT, None),
        (_client_error("InternalFailure"), ErrorReason.UNREACHABLE, None),
    ],
)
def test_each_error_maps_to_its_reason_and_fix(
    error: Exception, reason: ErrorReason, fix: str | None
) -> None:
    mapped = map_error(error, PROD, DESCRIBE)

    assert mapped.reason is reason
    assert mapped.fix == fix
    if reason is ErrorReason.DENIED:
        assert DESCRIBE in mapped.message


def test_an_unexpected_exception_is_not_mapped() -> None:
    with pytest.raises(TypeError):
        map_error(TypeError("x"), PROD, DESCRIBE)


@spec("FR-004")
def test_clients_use_the_timeouts_and_standard_retries(gateway: LiveGateway) -> None:
    config: Any = gateway.client(PROD, "us-east-1", "logs", 45.0).meta.config
    assert (config.connect_timeout, config.read_timeout) == (5, 20)
    assert config.retries == {"mode": "standard", "total_max_attempts": 2}
    near: Any = gateway.client(PROD, "us-east-1", "logs", 2.0).meta.config
    assert (near.read_timeout, near.retries["total_max_attempts"]) == (7, 1)


@spec("FR-004")
def test_threads_share_one_client_per_environment_region_and_service(
    gateway: LiveGateway,
) -> None:
    clients: list[object] = []

    def ask() -> None:
        clients.append(gateway.client(PROD, "us-east-1", "ecs", 40.0))

    threads = [threading.Thread(target=ask) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len({id(client) for client in clients}) == 1
