"""
Codeforces API client.

Wraps the public `user.status` endpoint documented at
https://codeforces.com/apiHelp/methods#user.status and converts it into
our internal `Submission` model, filtering for `OK` (accepted) verdicts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from models import Platform, Submission, Verdict


class CodeforcesAPIError(RuntimeError):
    """Raised when the Codeforces API returns a non-OK status or bad payload."""


class CodeforcesService:
    """Thin, testable client around the Codeforces public API."""

    def __init__(
        self,
        handle: str,
        api_base: str = "https://codeforces.com/api",
        max_retries: int = 3,
        backoff_seconds: float = 2.0,
        timeout_seconds: float = 15.0,
        session: requests.Session | None = None,
    ) -> None:
        if not handle:
            raise ValueError("A Codeforces handle is required.")
        self.handle = handle
        self.api_base = api_base.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds
        self.session = session or requests.Session()

    def _retrying(self):
        """Build a tenacity retry decorator honoring instance-configured limits."""
        return retry(
            reraise=True,
            stop=stop_after_attempt(max(1, self._max_retries)),
            wait=wait_exponential(multiplier=self._backoff_seconds, min=1, max=30),
            retry=retry_if_exception_type((requests.RequestException, CodeforcesAPIError)),
        )

    def fetch_recent_submissions(self, count: int = 50) -> list[Submission]:
        """Fetch the `count` most recent submissions for the configured handle.

        Only `OK` (accepted) verdicts are converted and returned; everything
        else is filtered out here so downstream agents never see noise.
        """

        @self._retrying()
        def _do_request() -> dict[str, Any]:
            url = f"{self.api_base}/user.status"
            response = self.session.get(
                url,
                params={"handle": self.handle, "from": 1, "count": count},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") != "OK":
                raise CodeforcesAPIError(
                    f"Codeforces API returned status={payload.get('status')!r}: "
                    f"{payload.get('comment', 'no comment')}"
                )
            return payload

        payload = _do_request()
        raw_submissions = payload.get("result", [])

        submissions: list[Submission] = []
        for raw in raw_submissions:
            if raw.get("verdict") != "OK":
                continue
            submissions.append(self._to_submission(raw))
        return submissions

    @staticmethod
    def _to_submission(raw: dict[str, Any]) -> Submission:
        problem = raw.get("problem", {})
        contest_id = problem.get("contestId")
        index = problem.get("index", "")
        problem_id = f"{contest_id}{index}" if contest_id is not None else index

        contest_id_str = str(contest_id) if contest_id is not None else None
        problem_url = (
            f"https://codeforces.com/problemset/problem/{contest_id}/{index}"
            if contest_id is not None and index
            else None
        )

        return Submission(
            submission_id=str(raw["id"]),
            platform=Platform.CODEFORCES,
            problem_id=problem_id,
            contest_id=contest_id_str,
            problem_index=index,
            problem_name=problem.get("name"),
            problem_url=problem_url,
            verdict=Verdict.ACCEPTED,
            language_raw=raw.get("programmingLanguage", ""),
            submitted_at=datetime.fromtimestamp(
                raw.get("creationTimeSeconds", 0), tz=timezone.utc
            ),
            tags=list(problem.get("tags", [])),
            rating=problem.get("rating"),
        )
