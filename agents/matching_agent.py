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
from typing import Callable

from rich.console import Console
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from models import MatchedSolution, Submission
from services.filesystem import FileSystemService, NoMatchingFileError

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

    def match(self, submission: Submission) -> MatchedSolution | None:
        """Attempt to match `submission` to a local file and copy it into the repo.

        Returns `None` (rather than raising) when no match is found, so the
        orchestrator can gracefully skip this submission and retry on a
        later poll once the user's file appears -- a missing file is an
        expected, recoverable condition, not a pipeline-ending error.
        """
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
