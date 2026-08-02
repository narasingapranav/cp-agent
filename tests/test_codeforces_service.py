from __future__ import annotations

import pytest
import requests

from services.codeforces import CodeforcesAPIError, CodeforcesService


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}")

    def json(self) -> dict:
        return self._payload


class _FakeSession:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.calls: list[dict] = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params})
        return _FakeResponse(self._payload)


_SAMPLE_PAYLOAD = {
    "status": "OK",
    "result": [
        {
            "id": 111,
            "verdict": "OK",
            "programmingLanguage": "PyPy 3-64",
            "creationTimeSeconds": 1700000000,
            "problem": {
                "contestId": 1899,
                "index": "A",
                "name": "Splitting Items",
                "tags": ["greedy"],
                "rating": 1200,
            },
        },
        {
            "id": 112,
            "verdict": "WRONG_ANSWER",
            "programmingLanguage": "GNU C++20",
            "creationTimeSeconds": 1700000001,
            "problem": {"contestId": 1899, "index": "B", "name": "Something", "tags": []},
        },
    ],
}


def test_fetch_recent_submissions_filters_non_ok_verdicts():
    session = _FakeSession(_SAMPLE_PAYLOAD)
    service = CodeforcesService(handle="tourist", session=session, max_retries=1)

    submissions = service.fetch_recent_submissions()

    assert len(submissions) == 1
    assert submissions[0].problem_id == "1899A"
    assert submissions[0].submission_id == "111"
    assert submissions[0].tags == ["greedy"]


def test_fetch_recent_submissions_passes_handle_param():
    session = _FakeSession(_SAMPLE_PAYLOAD)
    service = CodeforcesService(handle="tourist", session=session, max_retries=1)

    service.fetch_recent_submissions(count=10)

    assert session.calls[0]["params"]["handle"] == "tourist"
    assert session.calls[0]["params"]["count"] == 10


def test_non_ok_api_status_raises_after_retries():
    session = _FakeSession({"status": "FAILED", "comment": "handle not found"})
    service = CodeforcesService(
        handle="tourist", session=session, max_retries=1, backoff_seconds=0.01
    )

    with pytest.raises(CodeforcesAPIError):
        service.fetch_recent_submissions()


def test_requires_handle():
    with pytest.raises(ValueError):
        CodeforcesService(handle="")
