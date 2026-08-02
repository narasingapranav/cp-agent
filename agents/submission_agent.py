"""
Submission Agent.

Polls configured judges (Codeforces now, LeetCode when enabled) for accepted
submissions and filters out anything already recorded in the database, so
downstream agents only ever see genuinely new work.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.console import Console

from models import Submission
from services.codeforces import CodeforcesService
from services.database import Database
from services.leetcode import LeetCodeService

console = Console()


@dataclass
class SubmissionAgent:
    """Detects newly accepted submissions across all configured platforms."""

    codeforces: CodeforcesService
    database: Database
    leetcode: LeetCodeService | None = None
    poll_count: int = 50

    def check_new_acceptances(self) -> list[Submission]:
        """Return accepted submissions not yet present in the database.

        This is the single entry point the orchestrator / LangGraph node
        calls; it fans out to every configured platform service and merges
        + de-duplicates the results against persisted state.
        """
        all_submissions: list[Submission] = []

        all_submissions.extend(self._safe_fetch(self.codeforces, "Codeforces"))
        if self.leetcode is not None:
            all_submissions.extend(self._safe_fetch(self.leetcode, "LeetCode"))

        if not all_submissions:
            return []

        unprocessed_ids = set(
            self.database.filter_unprocessed([s.submission_id for s in all_submissions])
        )
        new_submissions = [s for s in all_submissions if s.submission_id in unprocessed_ids]

        for submission in new_submissions:
            console.log(
                f"[green]\u2713 Accepted detected[/green] "
                f"{submission.platform.value} {submission.problem_id} "
                f"(submission {submission.submission_id})"
            )

        return new_submissions

    @staticmethod
    def _safe_fetch(service, platform_name: str) -> list[Submission]:
        """Fetch from a platform service, isolating failures per-platform.

        A transient Codeforces outage should never prevent LeetCode (or vice
        versa) from being polled, and should never crash the whole pipeline.
        """
        try:
            return service.fetch_recent_submissions()
        except Exception as exc:  # noqa: BLE001 - intentionally broad, isolates per-platform
            console.log(f"[yellow]\u26a0 {platform_name} poll failed:[/yellow] {exc}")
            return []
