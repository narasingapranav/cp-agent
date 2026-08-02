"""
LeetCode service.

LeetCode does not expose a stable public API for submission history the way
Codeforces does. `fetch_recent_submissions` uses the public, unauthenticated
`recentAcSubmissionList` query (title/slug/timestamp only -- no source code).

To retrieve the actual submitted *code* (so a local solution file is never
required), `fetch_submission_code` uses the authenticated `submissionDetails`
query, which requires a logged-in session cookie (`LEETCODE_SESSION`). This
is the only way to get source code out of LeetCode outside of the browser;
there is no public API for it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from models import Platform, Submission, Verdict


class LeetCodeAPIError(RuntimeError):
    """Raised when the LeetCode GraphQL endpoint returns an unexpected payload."""


# Best-effort mapping from LeetCode's `lang`/`langName` values to file extensions.
_LANG_TO_EXTENSION = {
    "python": ".py",
    "python3": ".py",
    "cpp": ".cpp",
    "c++": ".cpp",
    "java": ".java",
    "c": ".c",
    "csharp": ".cs",
    "c#": ".cs",
    "javascript": ".js",
    "typescript": ".ts",
    "golang": ".go",
    "go": ".go",
    "kotlin": ".kt",
    "swift": ".swift",
    "rust": ".rs",
    "ruby": ".rb",
    "scala": ".scala",
    "php": ".php",
}


def extension_for_lang(lang: str) -> str:
    """Best-effort file extension for a LeetCode `lang` string. Defaults to `.txt`."""
    return _LANG_TO_EXTENSION.get((lang or "").strip().lower(), ".txt")


class LeetCodeService:
    """Client for LeetCode accepted-submission polling and code retrieval.

    Parameters
    ----------
    username:
        Public LeetCode username to query.
    enabled:
        Feature flag. When `False` (the default), `fetch_recent_submissions`
        short-circuits and returns `[]` without any network activity. This
        lets the orchestrator always call this service uniformly, and turn
        it on later purely via configuration (`LEETCODE_ENABLED=true`).
    session_cookie:
        Value of the `LEETCODE_SESSION` cookie from a logged-in browser
        session. Required only for `fetch_submission_code`; the recent-AC
        polling above works without it. Keep this secret -- it is
        equivalent to your LeetCode login.
    """

    GRAPHQL_URL = "https://leetcode.com/graphql"

    def __init__(
        self,
        username: str = "",
        enabled: bool = False,
        session_cookie: str = "",
        max_retries: int = 3,
        backoff_seconds: float = 2.0,
        timeout_seconds: float = 15.0,
        session: requests.Session | None = None,
    ) -> None:
        self.username = username
        self.enabled = enabled and bool(username)
        self.session_cookie = session_cookie
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

    def fetch_submission_code(self, submission_id: str) -> tuple[str, str]:
        """Fetch the actual source code for an accepted submission.

        Requires `session_cookie` (`LEETCODE_SESSION`) to be set -- LeetCode
        only exposes submission source to the authenticated owner of that
        submission, there is no public equivalent.

        Returns
        -------
        (code, lang) : tuple[str, str]
            The submitted source code and LeetCode's raw language string
            (e.g. `"python3"`, `"cpp"`), suitable for `extension_for_lang`.

        Raises
        ------
        LeetCodeAPIError
            If no session cookie is configured, or the API call fails / the
            response doesn't contain a `code` field (e.g. expired cookie).
        """
        if not self.session_cookie:
            raise LeetCodeAPIError(
                "LEETCODE_SESSION is not configured; cannot fetch submission code. "
                "Set LEETCODE_SESSION in .env (from your browser's leetcode.com cookies)."
            )

        query = {
            "query": (
                "query submissionDetails($submissionId: Int!) {"
                "  submissionDetails(submissionId: $submissionId) {"
                "    code lang { name } "
                "  }"
                "}"
            ),
            "variables": {"submissionId": int(submission_id)},
        }
        cookies = {"LEETCODE_SESSION": self.session_cookie}
        headers = {"Referer": "https://leetcode.com", "Content-Type": "application/json"}

        @self._retrying()
        def _do_request() -> dict[str, Any]:
            response = self.session.post(
                self.GRAPHQL_URL,
                json=query,
                cookies=cookies,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            if "errors" in payload:
                raise LeetCodeAPIError(str(payload["errors"]))
            return payload

        payload = _do_request()
        details = payload.get("data", {}).get("submissionDetails")
        if not details or not details.get("code"):
            raise LeetCodeAPIError(
                f"submissionDetails returned no code for submission {submission_id} "
                "-- session cookie may be expired or invalid."
            )
        lang = (details.get("lang") or {}).get("name", "")
        return details["code"], lang