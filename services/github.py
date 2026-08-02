"""
GitHub REST API client.

This service handles *remote* GitHub operations (verifying credentials,
ensuring the target repository exists, fetching its clone URL). Local git
plumbing (add/commit/push) lives in `agents/git_agent.py` via GitPython --
keeping "talk to GitHub's API" and "manipulate the local git repo" as
separate concerns.
"""

from __future__ import annotations

from typing import Any

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


class GitHubAPIError(RuntimeError):
    """Raised for unexpected GitHub API responses."""


class GitHubService:
    """Thin wrapper around the GitHub REST API (v3)."""

    API_BASE = "https://api.github.com"

    def __init__(
        self,
        token: str,
        username: str,
        repo_name: str,
        max_retries: int = 3,
        backoff_seconds: float = 2.0,
        timeout_seconds: float = 15.0,
        session: requests.Session | None = None,
    ) -> None:
        self.token = token
        self.username = username
        self.repo_name = repo_name
        self.timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds
        self.session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _retrying(self):
        return retry(
            reraise=True,
            stop=stop_after_attempt(max(1, self._max_retries)),
            wait=wait_exponential(multiplier=self._backoff_seconds, min=1, max=30),
            retry=retry_if_exception_type((requests.RequestException, GitHubAPIError)),
        )

    def authenticate(self) -> dict[str, Any]:
        """Verify the configured token is valid; returns the authenticated user's info."""

        @self._retrying()
        def _do_request() -> dict[str, Any]:
            response = self.session.get(
                f"{self.API_BASE}/user", headers=self._headers(), timeout=self.timeout_seconds
            )
            if response.status_code == 401:
                raise GitHubAPIError("GitHub authentication failed: invalid or expired token.")
            response.raise_for_status()
            return response.json()

        return _do_request()

    def repository_exists(self) -> bool:
        response = self.session.get(
            f"{self.API_BASE}/repos/{self.username}/{self.repo_name}",
            headers=self._headers(),
            timeout=self.timeout_seconds,
        )
        return response.status_code == 200

    def create_repository(self, private: bool = False, description: str = "") -> dict[str, Any]:
        """Create the portfolio repository under the authenticated user's account."""

        @self._retrying()
        def _do_request() -> dict[str, Any]:
            response = self.session.post(
                f"{self.API_BASE}/user/repos",
                headers=self._headers(),
                json={
                    "name": self.repo_name,
                    "private": private,
                    "description": description or "Automated competitive programming portfolio.",
                    "auto_init": True,
                },
                timeout=self.timeout_seconds,
            )
            if response.status_code not in (201, 200):
                raise GitHubAPIError(
                    f"Failed to create repository {self.repo_name!r}: "
                    f"{response.status_code} {response.text}"
                )
            return response.json()

        return _do_request()

    def ensure_repository(self, private: bool = False) -> str:
        """Ensure the target repo exists, creating it if necessary.

        Returns
        -------
        str
            The HTTPS clone URL (with embedded token) suitable for `git push`.
        """
        if not self.repository_exists():
            self.create_repository(private=private)
        return self.authenticated_clone_url()

    def authenticated_clone_url(self) -> str:
        """Build an HTTPS remote URL with the token embedded for push access."""
        return f"https://{self.token}@github.com/{self.username}/{self.repo_name}.git"
