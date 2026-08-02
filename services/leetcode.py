"""
LeetCode service (future support).

LeetCode does not expose a stable public API for submission history the way
Codeforces does; reliable access typically requires an authenticated
GraphQL session cookie. This module defines the same interface as
`CodeforcesService` (`fetch_recent_submissions`) so it can be dropped into
the Submission Agent / orchestrator once implemented, without touching any
other layer.

For now it is a documented, safely-disabled stub: it never makes network
calls unless explicitly enabled, and returns an empty list otherwise.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from models import Platform, Submission, Verdict


class LeetCodeAPIError(RuntimeError):
    """Raised when the LeetCode GraphQL endpoint returns an unexpected payload."""


class LeetCodeService:
    """Stub client for LeetCode accepted-submission polling.

    Parameters
    ----------
    username:
        Public LeetCode username to query.
    enabled:
        Feature flag. When `False` (the default), `fetch_recent_submissions`
        short-circuits and returns `[]` without any network activity. This
        lets the orchestrator always call this service uniformly, and turn
        it on later purely via configuration (`LEETCODE_ENABLED=true`).
    """

    GRAPHQL_URL = "https://leetcode.com/graphql"

    def __init__(
        self,
        username: str = "",
        enabled: bool = False,
        max_retries: int = 3,
        backoff_seconds: float = 2.0,
        timeout_seconds: float = 15.0,
        session: requests.Session | None = None,
    ) -> None:
        self.username = username
        self.enabled = enabled and bool(username)
        self.timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds
        self.session = session or requests.Session()

    def _retrying(self):
        return retry(
            reraise=True,
            stop=stop_after_attempt(max(1, self._max_retries)),
            wait=wait_exponential(multiplier=self._backoff_seconds, min=1, max=30),
            retry=retry_if_exception_type((requests.RequestException, LeetCodeAPIError)),
        )

    def fetch_recent_submissions(self, count: int = 20) -> list[Submission]:
        """Return recent accepted submissions, or `[]` if the feature is disabled.

        NOTE: The public `recentAcSubmissionList` query only exposes title
        slug + timestamp (no verdict detail, no language reliably), so this
        implementation is best-effort and clearly marked experimental. Full
        parity with the Codeforces service requires an authenticated session
        cookie, which is intentionally out of scope until a user opts in.
        """
        if not self.enabled:
            return []

        query = {
            "query": (
                "query recentAcSubmissions($username: String!, $limit: Int!) {"
                "  recentAcSubmissionList(username: $username, limit: $limit) {"
                "    id title titleSlug timestamp lang"
                "  }"
                "}"
            ),
            "variables": {"username": self.username, "limit": count},
        }

        @self._retrying()
        def _do_request() -> dict[str, Any]:
            response = self.session.post(
                self.GRAPHQL_URL, json=query, timeout=self.timeout_seconds
            )
            response.raise_for_status()
            payload = response.json()
            if "errors" in payload:
                raise LeetCodeAPIError(str(payload["errors"]))
            return payload

        payload = _do_request()
        raw_list = (
            payload.get("data", {}).get("recentAcSubmissionList", []) or []
        )

        submissions: list[Submission] = []
        for raw in raw_list:
            submissions.append(
                Submission(
                    submission_id=str(raw["id"]),
                    platform=Platform.LEETCODE,
                    problem_id=raw.get("titleSlug", ""),
                    problem_name=raw.get("title"),
                    problem_url=f"https://leetcode.com/problems/{raw.get('titleSlug', '')}/",
                    verdict=Verdict.ACCEPTED,
                    language_raw=raw.get("lang", ""),
                    submitted_at=datetime.fromtimestamp(
                        int(raw.get("timestamp", 0)), tz=timezone.utc
                    ),
                )
            )
        return submissions
