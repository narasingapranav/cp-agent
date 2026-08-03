"""
Git Agent.

Performs local git plumbing (`add`, `commit`, `push`) against the portfolio
repository using GitPython, generating a meaningful commit message per
accepted solution, e.g. `CF 1899A: Greedy Observation`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import git
from rich.console import Console

from models import CommitResult, GeneratedDocumentation

console = Console()

_PLATFORM_PREFIX = {
    "Codeforces": "CF",
    "LeetCode": "LC",
}


@dataclass
class GitAgent:
    """Wraps GitPython to commit + push a newly documented solution."""

    repo_path: Path
    remote_url: str | None = None
    dry_run: bool = False
    auto_push: bool = True

    def _repo(self) -> git.Repo:
        try:
            return git.Repo(self.repo_path)
        except git.InvalidGitRepositoryError:
            console.log(f"[cyan]Initializing new git repository at[/cyan] {self.repo_path}")
            return git.Repo.init(self.repo_path)

    def commit_message_for(self, doc: GeneratedDocumentation) -> str:
        submission = doc.matched.submission
        prefix = _PLATFORM_PREFIX.get(submission.platform.value, submission.platform.value)
        title = doc.algorithm if doc.algorithm and doc.algorithm != "N/A" else (
            submission.problem_name or "Solved"
        )
        return f"{prefix} {submission.problem_id}: {title}"

    def commit_and_push(self, doc: GeneratedDocumentation) -> CommitResult:
        """Stage the solution + doc + README, commit, and (optionally) push.

        In `dry_run` mode every step still executes for staging/diffing
        purposes conceptually, but no commit or push is actually made --
        this lets the whole pipeline be exercised safely against a real
        repo without polluting history.
        """
        message = self.commit_message_for(doc)

        if self.dry_run:
            console.log(f"[yellow]\u2713 (dry-run) Commit skipped:[/yellow] {message}")
            return CommitResult(matched=doc.matched, commit_message=message, dry_run=True)

        repo = self._repo()
        self._ensure_remote(repo)

        repo.git.add(A=True)

        if not repo.is_dirty(untracked_files=True) and not repo.index.diff("HEAD"):
            console.log("[yellow]\u26a0 Nothing to commit (working tree clean).[/yellow]")
            return CommitResult(matched=doc.matched, commit_message=message, pushed=False)

        commit = repo.index.commit(message)
        console.log(f"[green]\u2713 Commit created[/green] {commit.hexsha[:8]}: {message}")

        pushed = False
        if self.auto_push and self.remote_url:
            pushed = self._push(repo)

        return CommitResult(
            matched=doc.matched,
            commit_message=message,
            commit_hash=commit.hexsha,
            pushed=pushed,
        )

    def _ensure_remote(self, repo: git.Repo) -> None:
        if not self.remote_url:
            return
        if "origin" in [r.name for r in repo.remotes]:
            origin = repo.remotes.origin
            if list(origin.urls)[0] != self.remote_url:
                origin.set_url(self.remote_url)
        else:
            repo.create_remote("origin", self.remote_url)

    def _push(self, repo: git.Repo) -> bool:
        try:
            branch = repo.active_branch.name
        except TypeError:
            branch = "main"
            repo.git.checkout("-b", branch)

        # A rejected push (stale ref, non-fast-forward, remote rejection, etc.)
        # does NOT raise GitCommandError in GitPython -- it's reported only via
        # PushInfo flags on the returned result. Relying on "no exception" as a
        # proxy for success silently swallows real push failures, so we must
        # inspect the flags explicitly.
        _FAILURE_FLAGS = (
            git.PushInfo.ERROR
            | git.PushInfo.REJECTED
            | git.PushInfo.REMOTE_REJECTED
            | git.PushInfo.REMOTE_FAILURE
        )

        try:
            # Fetch first so our push is based on the latest remote state --
            # reduces (but doesn't eliminate) spurious rejections when
            # multiple commits are pushed back-to-back.
            repo.remotes.origin.fetch()
            push_infos = repo.remotes.origin.push(refspec=f"{branch}:{branch}", set_upstream=True)
        except git.GitCommandError as exc:
            console.log(f"[red]\u2717 Push failed:[/red] {exc}")
            return False

        errors = [pi for pi in push_infos if pi.flags & _FAILURE_FLAGS]
        if errors:
            details = "; ".join(pi.summary.strip() for pi in errors)
            console.log(f"[red]\u2717 Push rejected:[/red] {details}")
            # One retry after a fresh fetch handles the common "stale ref"
            # case (remote moved between our fetch and push).
            try:
                repo.remotes.origin.fetch()
                repo.git.rebase(f"origin/{branch}")
                retry_infos = repo.remotes.origin.push(
                    refspec=f"{branch}:{branch}", set_upstream=True
                )
                retry_errors = [pi for pi in retry_infos if pi.flags & _FAILURE_FLAGS]
                if retry_errors:
                    details = "; ".join(pi.summary.strip() for pi in retry_errors)
                    console.log(f"[red]\u2717 Push retry also failed:[/red] {details}")
                    return False
                console.log(f"[green]\u2713 Push successful on retry[/green] ({branch})")
                return True
            except git.GitCommandError as exc:
                console.log(f"[red]\u2717 Push retry failed:[/red] {exc}")
                return False

        console.log(f"[green]\u2713 Push successful[/green] ({branch})")
        return True