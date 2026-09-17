import time
from unittest.mock import MagicMock, patch

import pytest

from funnellens.lsq_client import LSQClient, LSQRateLimitError, LSQTransientError, RecordLimitError, mask_secrets
from funnellens.settings import Secrets, Settings


def make_settings(**api_overrides) -> Settings:
    api = {
        "page_size": 2,
        "opportunity_search_page_size": 2,
        "max_records": 5,
        "max_opportunity_search_records": 5,
        "retry_attempts": 3,
        "max_workers": 3,
    }
    api.update(api_overrides)
    return Settings(
        secrets=Secrets(access_key="TESTACCESSKEY", secret_key="TESTSECRETKEY", api_host="api-test.leadsquared.com"),
        config={
            "timezone": "Asia/Kolkata",
            "fields": {
                "opportunity_stage": "mx_Custom_2",
                "opportunity_status": "Status",
                "source": "Source",
                "enrolled_date": "mx_Custom_45",
            },
            "stages": [],
            "excluded_owner_roles": [],
            "excluded_owner_names": [],
            "opportunity_event_code": 12000,
            "api": api,
        },
    )


def make_response(status_code: int, json_body=None, text: str = "", headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text or str(json_body)
    resp.headers = headers or {}
    resp.json.return_value = json_body
    return resp


def test_mask_secrets_redacts_both_keys():
    text = "https://api.example.com/v2/x?accessKey=abc123&secretKey=def456&other=1"
    masked = mask_secrets(text)
    assert "abc123" not in masked
    assert "def456" not in masked
    assert "accessKey=***" in masked
    assert "secretKey=***" in masked
    assert "other=1" in masked


def test_pagination_fetches_every_page():
    client = LSQClient(make_settings(page_size=2, max_records=10))
    pages = [
        [{"ProspectID": "1"}, {"ProspectID": "2"}],
        [{"ProspectID": "3"}, {"ProspectID": "4"}],
        [{"ProspectID": "5"}],  # shorter than page_size -> last page
    ]
    with patch.object(client, "_session") as mock_session:
        mock_session.request.side_effect = [make_response(200, json_body=p) for p in pages]
        result = client.search_leads("CreatedOn", "2026-01-01 00:00:00", ">=", "ProspectID")
    assert [r["ProspectID"] for r in result] == ["1", "2", "3", "4", "5"]
    assert mock_session.request.call_count == 3


def test_pagination_raises_record_limit_error_instead_of_truncating():
    client = LSQClient(make_settings(page_size=2, max_records=3))
    pages = [
        [{"ProspectID": "1"}, {"ProspectID": "2"}],
        [{"ProspectID": "3"}, {"ProspectID": "4"}],
        [{"ProspectID": "5"}, {"ProspectID": "6"}],
    ]
    with patch.object(client, "_session") as mock_session:
        mock_session.request.side_effect = [make_response(200, json_body=p) for p in pages]
        with pytest.raises(RecordLimitError):
            client.search_leads("CreatedOn", "2026-01-01 00:00:00", ">=", "ProspectID")


def test_retry_on_429_then_success():
    client = LSQClient(make_settings(retry_attempts=3, rate_limit_window_seconds=0.01))
    with patch.object(client, "_session") as mock_session:
        mock_session.request.side_effect = [
            make_response(429, text="rate limited"),
            make_response(200, json_body=[{"ID": "u1", "StatusCode": 0}]),
        ]
        result = client.get_users()
    assert result == [{"ID": "u1", "StatusCode": 0}]
    assert mock_session.request.call_count == 2


def test_429_retry_after_is_respected():
    client = LSQClient(make_settings(retry_attempts=2))
    with patch.object(client, "_session") as mock_session:
        mock_session.request.side_effect = [
            make_response(429, text="rate limited", headers={"Retry-After": "0.05"}),
            make_response(200, json_body=[]),
        ]
        start = time.monotonic()
        assert client.get_users() == []
    assert time.monotonic() - start >= 0.045


def test_permanent_429_raises_clear_rate_limit_error():
    client = LSQClient(make_settings(retry_attempts=2))
    with patch.object(client, "_session") as mock_session:
        mock_session.request.return_value = make_response(429, text="rate limited", headers={"Retry-After": "0"})
        with pytest.raises(LSQRateLimitError, match="rate limit"):
            client.get_users()
    assert mock_session.request.call_count == 2


def test_retry_exhausted_raises_transient_error():
    client = LSQClient(make_settings(retry_attempts=2))
    with patch.object(client, "_session") as mock_session:
        mock_session.request.side_effect = [
            make_response(500, text="server error"),
            make_response(500, text="server error"),
        ]
        with pytest.raises(LSQTransientError):
            client.get_users()
    assert mock_session.request.call_count == 2


def test_secrets_never_appear_in_raised_exception_text():
    client = LSQClient(make_settings(retry_attempts=1))
    with patch.object(client, "_session") as mock_session:
        mock_session.request.return_value = make_response(500, text="boom with accessKey=TESTACCESSKEY leaked")
        with pytest.raises(LSQTransientError) as exc_info:
            client.get_users()
    message = str(exc_info.value)
    assert "TESTACCESSKEY" not in message
    assert "TESTSECRETKEY" not in message


def test_secrets_never_appear_in_connection_error_text():
    import requests

    client = LSQClient(make_settings(retry_attempts=1))
    with patch.object(client, "_session") as mock_session:
        mock_session.request.side_effect = requests.exceptions.ConnectionError(
            "failed: accessKey=TESTACCESSKEY&secretKey=TESTSECRETKEY"
        )
        with pytest.raises(LSQTransientError) as exc_info:
            client.get_users()
    message = str(exc_info.value)
    assert "TESTACCESSKEY" not in message
    assert "TESTSECRETKEY" not in message


def test_run_parallel_preserves_input_order():
    client = LSQClient(make_settings(max_workers=3))
    calls = [lambda i=i: i for i in range(10)]
    assert client.run_parallel(calls) == list(range(10))


def test_throttle_delays_once_the_window_is_full():
    client = LSQClient(make_settings())
    client._rate_limit_calls = 2
    client._rate_limit_window = 0.2
    start = time.monotonic()
    for _ in range(3):
        client._throttle()
    assert time.monotonic() - start >= 0.2


def test_throttle_does_not_delay_under_the_limit():
    client = LSQClient(make_settings())
    client._rate_limit_calls = 100
    start = time.monotonic()
    for _ in range(5):
        client._throttle()
    assert time.monotonic() - start < 0.1


def test_parallel_workers_share_one_rate_limit_budget():
    client = LSQClient(make_settings(max_workers=4, rate_limit_requests=2, rate_limit_window_seconds=0.1))
    request_times = []

    def request(*args, **kwargs):
        request_times.append(time.monotonic())
        return make_response(200, json_body=[])

    with patch.object(client, "_session") as mock_session:
        mock_session.request.side_effect = request
        assert client.run_parallel([client.get_users] * 4) == [[], [], [], []]

    assert len(request_times) == 4
    assert sorted(request_times)[2] - sorted(request_times)[0] >= 0.09
