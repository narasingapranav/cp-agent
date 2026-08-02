from __future__ import annotations

from pathlib import Path

import pytest

from models import Language
from services.filesystem import FileSystemService, NoMatchingFileError


def test_find_match_by_filename(tmp_path: Path, sample_submission):
    solutions_dir = tmp_path / "solutions"
    (solutions_dir).mkdir()
    solution_file = solutions_dir / "1899A.py"
    solution_file.write_text("print('hi')")

    service = FileSystemService(solutions_dir=solutions_dir, repo_path=tmp_path / "repo")
    match = service.find_match(sample_submission)

    assert match == solution_file


def test_find_match_by_parent_directory(tmp_path: Path, sample_submission):
    solutions_dir = tmp_path / "solutions"
    (solutions_dir / "1899").mkdir(parents=True)
    solution_file = solutions_dir / "1899" / "A.py"
    solution_file.write_text("print('hi')")

    service = FileSystemService(solutions_dir=solutions_dir, repo_path=tmp_path / "repo")
    match = service.find_match(sample_submission)

    assert match == solution_file


def test_find_match_raises_when_no_candidates(tmp_path: Path, sample_submission):
    solutions_dir = tmp_path / "solutions"
    solutions_dir.mkdir()
    service = FileSystemService(solutions_dir=solutions_dir, repo_path=tmp_path / "repo")

    with pytest.raises(NoMatchingFileError):
        service.find_match(sample_submission)


def test_destination_for_uses_contest_and_index(tmp_path: Path, sample_submission):
    service = FileSystemService(solutions_dir=tmp_path / "solutions", repo_path=tmp_path / "repo")
    dest = service.destination_for(sample_submission, Path("A.py"))

    assert dest == tmp_path / "repo" / "Codeforces" / "1899" / "A.py"


def test_build_matched_solution_sets_language(tmp_path: Path, sample_submission):
    solutions_dir = tmp_path / "solutions"
    solutions_dir.mkdir()
    (solutions_dir / "1899A.py").write_text("print(1)")

    service = FileSystemService(solutions_dir=solutions_dir, repo_path=tmp_path / "repo")
    matched = service.build_matched_solution(sample_submission)

    assert matched.language == Language.PYTHON


def test_materialize_copies_file_to_destination(tmp_path: Path, sample_submission):
    solutions_dir = tmp_path / "solutions"
    solutions_dir.mkdir()
    source = solutions_dir / "1899A.py"
    source.write_text("print('accepted')")

    service = FileSystemService(solutions_dir=solutions_dir, repo_path=tmp_path / "repo")
    matched = service.build_matched_solution(sample_submission)
    dest = service.materialize(matched)

    assert dest.exists()
    assert dest.read_text() == "print('accepted')"
    assert source.exists()  # original left untouched (copy, not move)
