"""
Filesystem helpers used by the Matching Agent.

Responsible for:
* Scanning the user's local "solutions" directory for source files.
* Guessing which local file corresponds to a given accepted `Submission`.
* Copying/renaming matched files into the canonical repo layout, e.g.
  `repo/Codeforces/1899/A.py`.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from models import Language, MatchedSolution, Platform, Submission

_SOURCE_EXTENSIONS = {".py", ".cpp", ".cc", ".cxx", ".java"}

# Matches things like "1899A", "1899_A", "1899-A" (contest id + index) so we
# can locate a source file even if the user didn't name it with the exact
# same separators CP-Agent uses internally.
_PROBLEM_ID_PATTERN = re.compile(r"(?P<contest>\d+)[_\-]?(?P<index>[A-Za-z]\d*)")


class NoMatchingFileError(FileNotFoundError):
    """Raised when no local source file can be confidently matched to a submission."""


class FileSystemService:
    """Scans a directory tree and matches files to accepted submissions."""

    def __init__(self, solutions_dir: Path, repo_path: Path) -> None:
        self.solutions_dir = Path(solutions_dir)
        self.repo_path = Path(repo_path)

    def list_source_files(self) -> list[Path]:
        """Recursively list every candidate source file under `solutions_dir`."""
        if not self.solutions_dir.exists():
            return []
        return [
            p
            for p in self.solutions_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in _SOURCE_EXTENSIONS
        ]

    def find_match(self, submission: Submission) -> Path:
        """Locate the local source file that most likely corresponds to `submission`.

        Matching strategy (in priority order):
        1. Exact problem id appears in the filename or an immediate parent
           directory name (case-insensitive), e.g. `1899A.py`, `1899/A.py`.
        2. Contest id + index both appear somewhere in the file's full
           relative path, in either order (e.g. `contest1899/taskA.cpp`).

        Raises
        ------
        NoMatchingFileError
            If no candidate file satisfies either strategy.
        """
        problem_id = submission.problem_id.lower()
        contest = (submission.contest_id or "").lower()
        index = (submission.problem_index or "").lower()

        candidates = self.list_source_files()
        if not candidates:
            raise NoMatchingFileError(
                f"No source files found under {self.solutions_dir} to match "
                f"submission {submission.submission_id} ({submission.problem_id})."
            )

        # Strategy 1: filename or parent dir literally contains the problem id.
        for path in candidates:
            haystack = f"{path.parent.name}/{path.stem}".lower()
            if problem_id and problem_id in haystack.replace("_", "").replace("-", ""):
                return path

        # Strategy 2: contest id AND index both present somewhere in the path.
        if contest and index:
            for path in candidates:
                rel = str(path.relative_to(self.solutions_dir)).lower()
                if contest in rel and re.search(rf"\b{re.escape(index)}\b", rel):
                    return path

        raise NoMatchingFileError(
            f"Could not confidently match submission {submission.submission_id} "
            f"({submission.problem_id}) to any file under {self.solutions_dir}."
        )

    def destination_for(self, submission: Submission, source: Path) -> Path:
        """Compute the canonical repo destination path for a matched submission.

        Layout: `repo/<Platform>/<contest_or_problem>/<index>.<ext>`
        Falls back to `repo/<Platform>/<problem_id><ext>` when there is no
        separate contest/index split (e.g. LeetCode slugs).
        """
        ext = source.suffix.lower()
        platform_dir = self.repo_path / submission.platform.value

        if submission.contest_id and submission.problem_index:
            return platform_dir / submission.contest_id / f"{submission.problem_index}{ext}"
        return platform_dir / f"{submission.problem_id}{ext}"

    def build_matched_solution(self, submission: Submission) -> MatchedSolution:
        source = self.find_match(submission)
        language = Language.from_extension(source.suffix)
        destination = self.destination_for(submission, source)
        return MatchedSolution(
            submission=submission,
            source_path=source,
            language=language,
            destination_path=destination,
        )

    def materialize(self, matched: MatchedSolution) -> Path:
        """Copy the matched source file into its canonical repo location.

        We copy (rather than move) so the user's working `solutions_dir`
        remains untouched -- useful if they keep solving problems in a
        scratch directory outside the git-tracked repo.
        """
        matched.destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(matched.source_path, matched.destination_path)
        return matched.destination_path

    @staticmethod
    def extract_problem_id_from_name(name: str) -> str | None:
        """Best-effort extraction of a CF-style problem id from an arbitrary string."""
        match = _PROBLEM_ID_PATTERN.search(name)
        if not match:
            return None
        return f"{match.group('contest')}{match.group('index').upper()}"
