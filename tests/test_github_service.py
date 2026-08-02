from __future__ import annotations

from services.github import GitHubService


class _FakeResponse:
    def __init__(self, status_code: int, json_data=None, text: str = ""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json

    def raise_for_status(self):
        pass


class _FakeSession:
    def __init__(self, exists: bool = True):
        self._exists = exists
        self.get_calls = []
        self.post_calls = []

    def get(self, url, headers=None, timeout=None):
        self.get_calls.append(url)
        if url.endswith("/user"):
            return _FakeResponse(200, {"login": "octocat"})
        return _FakeResponse(200 if self._exists else 404)

    def post(self, url, headers=None, json=None, timeout=None):
        self.post_calls.append(url)
        return _FakeResponse(201, {"full_name": json["name"]})


def test_authenticate_returns_user_info():
    session = _FakeSession()
    service = GitHubService(token="tok", username="me", repo_name="repo", session=session)
    user = service.authenticate()
    assert user["login"] == "octocat"


def test_repository_exists_true():
    session = _FakeSession(exists=True)
    service = GitHubService(token="tok", username="me", repo_name="repo", session=session)
    assert service.repository_exists() is True


def test_ensure_repository_creates_when_missing():
    session = _FakeSession(exists=False)
    service = GitHubService(token="tok", username="me", repo_name="repo", session=session)
    url = service.ensure_repository()
    assert session.post_calls  # repo creation was triggered
    assert url == "https://tok@github.com/me/repo.git"


def test_ensure_repository_skips_creation_when_present():
    session = _FakeSession(exists=True)
    service = GitHubService(token="tok", username="me", repo_name="repo", session=session)
    service.ensure_repository()
    assert not session.post_calls
