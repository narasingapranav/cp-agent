"""
Matching Agent.

Pairs a newly accepted `Submission` with the corresponding local source
file, then copies that file into the canonical repo layout
(`repo/<Platform>/<contest>/<index>.<ext>`).

Also exposes a `watchdog`-based observer so the agent can react instantly
to files being saved in the user's editor, in addition to being invoked
synchronously from the LangGraph pipeline right after a submission is
detected as accepted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from rich.console import Console
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from models import Language, MatchedSolution, Platform, Submission
from services.filesystem import FileSystemService, NoMatchingFileError
from services.leetcode import LeetCodeAPIError, LeetCodeService, extension_for_lang

console = Console()

_WATCHED_EXTENSIONS = {".py", ".cpp", ".cc", ".cxx", ".java"}


class _SolutionFileHandler(FileSystemEventHandler):
    """Watchdog handler that forwards relevant save events to a callback."""

    def __init__(self, on_saved: Callable[[str], None]) -> None:
        self._on_saved = on_saved

    def on_created(self, event: FileSystemEvent) -> None:
        self._maybe_forward(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._maybe_forward(event)

    def _maybe_forward(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        if not any(str(event.src_path).lower().endswith(ext) for ext in _WATCHED_EXTENSIONS):
            return
        self._on_saved(str(event.src_path))


@dataclass
class MatchingAgent:
    """Locates and organizes the local solution file for an accepted submission."""

    filesystem: FileSystemService
    leetcode: Optional[LeetCodeService] = None

    def match(self, submission: Submission) -> MatchedSolution | None:
        """Attempt to match `submission` to source code and stage it into the repo.

        For LeetCode submissions, when a `LeetCodeService` with a configured
        session cookie is available, the actual submitted code is fetched
        directly from LeetCode and written straight into the repo -- no
        local solution file is required. All other cases (Codeforces, or
        LeetCode without a session cookie configured) fall back to the
        local-file lookup.

        Returns `None` (rather than raising) when no match/fetch succeeds,
        so the orchestrator can gracefully skip this submission and retry on
        a later poll -- a missing file/expired cookie is an expected,
        recoverable condition, not a pipeline-ending error.
        """
        if submission.platform == Platform.LEETCODE and self.leetcode is not None:
            matched = self._match_via_leetcode_api(submission)
            if matched is not None:
                return matched
            # Fall through to local-file lookup as a backup path.

        try:
            matched = self.filesystem.build_matched_solution(submission)
        except NoMatchingFileError as exc:
            console.log(f"[yellow]\u26a0 No local file matched yet:[/yellow] {exc}")
            return None

        self.filesystem.materialize(matched)
        console.log(
            f"[green]\u2713 File matched[/green] "
            f"{matched.source_path.name} -> {matched.destination_path}"
        )
        return matched

    def _match_via_leetcode_api(self, submission: Submission) -> MatchedSolution | None:
        """Fetch code directly from LeetCode and write it into the repo.

        No local source file is read or required -- `source_path` is set to
        the same location as `destination_path` since the file is created
        directly there.
        """
        try:
            code, lang_name = self.leetcode.fetch_submission_code(submission.submission_id)
        except LeetCodeAPIError as exc:
            console.log(
                f"[yellow]\u26a0 Could not fetch code from LeetCode yet:[/yellow] {exc}"
            )
            return None

        ext = extension_for_lang(lang_name or submission.language_raw)
        destination = (
            self.filesystem.repo_path / submission.platform.value / f"{submission.problem_id}{ext}"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(code, encoding="utf-8")

        matched = MatchedSolution(
            submission=submission,
            source_path=destination,
            language=Language.from_extension(ext),
            destination_path=destination,
        )
        console.log(
            f"[green]\u2713 Code fetched from LeetCode[/green] -> {matched.destination_path}"
        )
        return matched

    def start_watching(self, on_saved: Callable[[str], None]) -> Observer:
        """Start a background watchdog observer over the solutions directory.

        Returns the running `Observer` so the caller controls its lifecycle
        (e.g. `observer.stop(); observer.join()` on shutdown).
        """
        handler = _SolutionFileHandler(on_saved)
        observer = Observer()
        observer.schedule(handler, str(self.filesystem.solutions_dir), recursive=True)
        observer.start()
        console.log(
            f"[cyan]Watching[/cyan] {self.filesystem.solutions_dir} for new solution files..."
        )
        return observer