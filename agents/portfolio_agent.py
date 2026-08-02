"""
Portfolio Agent.

Regenerates `README.md` inside the portfolio repo with up-to-date
statistics: total solved, today's solved count, per-language breakdown,
per-platform breakdown, current streak, and a table of recent submissions.

The README is fully regenerated (idempotent) from the database each run,
between clearly delimited markers, so any hand-written content the user
adds above/below is preserved.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from rich.console import Console

from models import GeneratedDocumentation, Platform
from services.database import Database

console = Console()

_START_MARKER = "<!-- CP-AGENT:START -->"
_END_MARKER = "<!-- CP-AGENT:END -->"

_EXT_TO_LANGUAGE = {
    ".py": "Python",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".java": "Java",
}

_DEFAULT_README = f"""# Competitive Programming Portfolio

Automatically maintained by [CP-Agent](https://github.com/) -- solving
problems and committing here is fully hands-off.

{_START_MARKER}
{_END_MARKER}
"""


@dataclass
class PortfolioAgent:
    """Maintains the auto-generated statistics section of the portfolio README."""

    database: Database
    repo_path: Path

    @property
    def readme_path(self) -> Path:
        return self.repo_path / "README.md"

    def update(self, latest: GeneratedDocumentation | None = None) -> Path:
        """Recompute stats from the database and rewrite the README section.

        `latest` is accepted (but not required) purely so the orchestrator
        can pass through the just-processed submission for logging; all
        statistics are always derived from the full database so the README
        never drifts out of sync even if a run is interrupted.
        """
        records = self.database.all_records()
        total_solved = len(records)

        today = date.today()
        today_count = sum(
            1 for r in records if self._as_date(r.timestamp) == today
        )

        language_counts: dict[str, int] = {}
        platform_counts: dict[str, int] = {}
        for r in records:
            ext = Path(r.filename).suffix.lower()
            language = _EXT_TO_LANGUAGE.get(ext, ext or "Unknown")
            language_counts[language] = language_counts.get(language, 0) + 1
            platform_counts[r.platform.value] = platform_counts.get(r.platform.value, 0) + 1

        streak = self._compute_streak(records)
        recent = records[:10]

        section = self._render_section(
            total_solved=total_solved,
            today_count=today_count,
            language_counts=language_counts,
            platform_counts=platform_counts,
            streak=streak,
            recent=recent,
        )

        self._write_readme(section)
        console.log(f"[green]\u2713 README updated[/green] ({total_solved} total solved)")
        return self.readme_path

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _as_date(timestamp) -> date:
        if isinstance(timestamp, datetime):
            return timestamp.date()
        if isinstance(timestamp, str):
            return datetime.fromisoformat(timestamp).date()
        return timestamp

    def _compute_streak(self, records) -> int:
        """Count consecutive days (ending today or yesterday) with >=1 solve."""
        if not records:
            return 0
        solved_dates = {self._as_date(r.timestamp) for r in records}
        streak = 0
        cursor = date.today()
        # Allow the streak to still "count" if today has no solve yet but
        # yesterday did -- otherwise it would reset to 0 every morning.
        if cursor not in solved_dates:
            cursor -= timedelta(days=1)
        while cursor in solved_dates:
            streak += 1
            cursor -= timedelta(days=1)
        return streak

    def _render_section(
        self,
        *,
        total_solved: int,
        today_count: int,
        language_counts: dict[str, int],
        platform_counts: dict[str, int],
        streak: int,
        recent,
    ) -> str:
        lines: list[str] = [_START_MARKER, ""]
        lines.append("## \U0001F4CA Statistics")
        lines.append("")
        lines.append(f"- **Total solved:** {total_solved}")
        lines.append(f"- **Solved today:** {today_count}")
        lines.append(f"- **Current streak:** {streak} day(s)")
        lines.append("")

        lines.append("### By platform")
        lines.append("")
        lines.append("| Platform | Solved |")
        lines.append("|----------|--------|")
        for platform in Platform:
            lines.append(f"| {platform.value} | {platform_counts.get(platform.value, 0)} |")
        lines.append("")

        lines.append("### By language")
        lines.append("")
        lines.append("| Language | Solved |")
        lines.append("|----------|--------|")
        for lang, count in sorted(language_counts.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {lang} | {count} |")
        lines.append("")

        lines.append("### Recent submissions")
        lines.append("")
        lines.append("| Date | Platform | Problem | File |")
        lines.append("|------|----------|---------|------|")
        for r in recent:
            ts = self._as_date(r.timestamp).isoformat()
            lines.append(f"| {ts} | {r.platform.value} | {r.problem_id} | `{r.filename}` |")
        lines.append("")
        lines.append(_END_MARKER)
        return "\n".join(lines)

    def _write_readme(self, section: str) -> None:
        self.repo_path.mkdir(parents=True, exist_ok=True)
        if self.readme_path.exists():
            existing = self.readme_path.read_text(encoding="utf-8")
        else:
            existing = _DEFAULT_README

        if _START_MARKER in existing and _END_MARKER in existing:
            before = existing.split(_START_MARKER)[0]
            after = existing.split(_END_MARKER)[-1]
            new_content = f"{before}{section}{after}"
        else:
            # No markers yet (fresh/hand-written README) -- append the section.
            new_content = existing.rstrip() + "\n\n" + section + "\n"

        self.readme_path.write_text(new_content, encoding="utf-8")
