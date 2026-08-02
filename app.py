"""
CP-Agent entrypoint.

Wires together the service layer (Codeforces/LeetCode/GitHub/filesystem/db),
the agent layer (submission/matching/documentation/portfolio/git), and the
LangGraph orchestrator, then runs the poll loop described in the project
brief:

    Solve Problem -> Save file -> Submit -> Accepted
        -> Agent detects acceptance -> Matches local file
        -> Organizes repo -> Generates README -> Generates AI explanation
        -> Commits -> Pushes to GitHub

Usage
-----
    python app.py            # run the continuous poll loop
    python app.py --once      # run a single poll iteration and exit
    python app.py --dry-run   # override .env DRY_RUN=true for this run
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from types import FrameType

from rich.console import Console
from rich.logging import RichHandler

from agents.documentation_agent import DocumentationAgent
from agents.git_agent import GitAgent
from agents.matching_agent import MatchingAgent
from agents.orchestrator import Orchestrator
from agents.portfolio_agent import PortfolioAgent
from agents.submission_agent import SubmissionAgent
from config import Settings, get_settings
from services.codeforces import CodeforcesService
from services.database import Database
from services.filesystem import FileSystemService
from services.github import GitHubService
from services.leetcode import LeetCodeService

console = Console()
logger = logging.getLogger("cp_agent")

_shutdown_requested = False


def _configure_logging(logs_dir) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "cp_agent.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[
            RichHandler(console=console, rich_tracebacks=True, show_path=False),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )


def _handle_signal(signum: int, frame: FrameType | None) -> None:
    global _shutdown_requested
    console.log(f"[yellow]Received signal {signum}, shutting down gracefully...[/yellow]")
    _shutdown_requested = True


class Application:
    """Composition root: builds every service/agent and runs the poll loop."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        settings.ensure_directories()

        # --- Services ---
        self.database = Database(settings.database_path)
        self.codeforces = CodeforcesService(
            handle=settings.codeforces_handle,
            api_base=settings.codeforces_api_base,
            max_retries=settings.max_retries,
            backoff_seconds=settings.retry_backoff_seconds,
        )
        self.leetcode = LeetCodeService(
            username=settings.leetcode_username,
            enabled=settings.leetcode_enabled,
            max_retries=settings.max_retries,
            backoff_seconds=settings.retry_backoff_seconds,
        )
        self.filesystem = FileSystemService(
            solutions_dir=settings.local_solutions_dir,
            repo_path=settings.repo_path,
        )
        self.github = GitHubService(
            token=settings.github_token,
            username=settings.github_username,
            repo_name=settings.github_repo_name,
            max_retries=settings.max_retries,
            backoff_seconds=settings.retry_backoff_seconds,
        )

        # --- Agents ---
        self.submission_agent = SubmissionAgent(
            codeforces=self.codeforces,
            database=self.database,
            leetcode=self.leetcode if settings.leetcode_enabled else None,
        )
        self.matching_agent = MatchingAgent(filesystem=self.filesystem)
        self.documentation_agent = DocumentationAgent(
            prompts_dir=settings.prompts_dir,
            openai_api_key=settings.openai_api_key,
            openai_model=settings.openai_model,
        )
        self.portfolio_agent = PortfolioAgent(
            database=self.database, repo_path=settings.repo_path
        )

        remote_url = self._resolve_remote_url()
        self.git_agent = GitAgent(
            repo_path=settings.repo_path,
            remote_url=remote_url,
            dry_run=settings.dry_run,
            auto_push=settings.auto_push,
        )

        self.orchestrator = Orchestrator(
            matching_agent=self.matching_agent,
            documentation_agent=self.documentation_agent,
            portfolio_agent=self.portfolio_agent,
            git_agent=self.git_agent,
            database=self.database,
        )

    def _resolve_remote_url(self) -> str | None:
        if self.settings.dry_run:
            return None
        if not (self.settings.github_token and self.settings.github_username
                and self.settings.github_repo_name):
            console.log(
                "[yellow]\u26a0 GitHub is not fully configured; "
                "commits will be made locally only.[/yellow]"
            )
            return None
        try:
            return self.github.ensure_repository()
        except Exception as exc:  # noqa: BLE001
            console.log(f"[yellow]\u26a0 Could not verify/create GitHub repo:[/yellow] {exc}")
            return None

    def poll_once(self) -> int:
        """Run a single detect -> pipeline cycle. Returns count of submissions processed."""
        new_submissions = self.submission_agent.check_new_acceptances()
        for submission in new_submissions:
            self.orchestrator.run(submission)
        return len(new_submissions)

    def run_forever(self) -> None:
        console.rule("[bold cyan]CP-Agent[/bold cyan]")
        console.log(
            f"Polling every {self.settings.poll_interval_seconds}s for "
            f"[bold]{self.settings.codeforces_handle}[/bold] on Codeforces"
            + (" and LeetCode" if self.settings.leetcode_enabled else "")
        )
        while not _shutdown_requested:
            try:
                self.poll_once()
            except Exception as exc:  # noqa: BLE001 - keep the daemon alive across errors
                console.log(f"[red]\u2717 Unexpected error during poll:[/red] {exc}")

            for _ in range(self.settings.poll_interval_seconds):
                if _shutdown_requested:
                    break
                time.sleep(1)

        console.log("[cyan]CP-Agent stopped.[/cyan]")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CP-Agent: autonomous CP portfolio builder.")
    parser.add_argument(
        "--once", action="store_true", help="Run a single poll iteration and exit."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Force dry-run mode (no git commit/push)."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    if args.dry_run:
        settings.dry_run = True

    _configure_logging(settings.logs_dir)
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    app = Application(settings)

    if args.once:
        processed = app.poll_once()
        console.log(f"Processed {processed} new submission(s).")
        return 0

    app.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
