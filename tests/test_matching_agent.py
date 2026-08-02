from __future__ import annotations

from pathlib import Path

from agents.matching_agent import MatchingAgent
from services.filesystem import FileSystemService


def test_match_returns_matched_solution_when_file_exists(tmp_path: Path, sample_submission):
    solutions_dir = tmp_path / "solutions"
    solutions_dir.mkdir()
    (solutions_dir / "1899A.py").write_text("print('ok')")

    fs_service = FileSystemService(solutions_dir=solutions_dir, repo_path=tmp_path / "repo")
    agent = MatchingAgent(filesystem=fs_service)

    matched = agent.match(sample_submission)

    assert matched is not None
    assert matched.destination_path.exists()


def test_match_returns_none_when_no_file_found(tmp_path: Path, sample_submission):
    solutions_dir = tmp_path / "solutions"
    solutions_dir.mkdir()

    fs_service = FileSystemService(solutions_dir=solutions_dir, repo_path=tmp_path / "repo")
    agent = MatchingAgent(filesystem=fs_service)

    matched = agent.match(sample_submission)

    assert matched is None
