"""Shared pytest fixtures for CP-Agent's test suite."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Ensure the project root is importable when running `pytest` from anywhere.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from models import Platform, Submission, Verdict  # noqa: E402
from services.database import Database  # noqa: E402


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Database:
    return Database(tmp_path / "solved.db")


@pytest.fixture()
def sample_submission() -> Submission:
    return Submission(
        submission_id="123456",
        platform=Platform.CODEFORCES,
        problem_id="1899A",
        contest_id="1899",
        problem_index="A",
        problem_name="Splitting Items",
        problem_url="https://codeforces.com/problemset/problem/1899/A",
        verdict=Verdict.ACCEPTED,
        language_raw="GNU C++20",
        submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        tags=["greedy", "games"],
        rating=1200,
    )
