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

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

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
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".c": "C",
    ".cs": "C#",
    ".kt": "Kotlin",
    ".rb": "Ruby",
}

_LANGUAGE_BADGE_COLOR = {
    "Python": "3776AB",
    "C++": "00599C",
    "Java": "007396",
    "JavaScript": "F7DF1E",
    "TypeScript": "3178C6",
    "Go": "00ADD8",
    "Rust": "DEA584",
    "C": "A8B9CC",
    "C#": "239120",
    "Kotlin": "7F52FF",
    "Ruby": "CC342D",
}

_PLATFORM_ICON = {
    Platform.CODEFORCES: "\U0001F535",  # blue circle
    Platform.LEETCODE: "\U0001F7E0",  # orange circle
}

_PLATFORM_BADGE_COLOR = {
    Platform.CODEFORCES: "1F8ACB",
    Platform.LEETCODE: "FFA116",
}

_STREAK_EMOJI_THRESHOLDS = [
    (30, "\U0001F3C6"),  # trophy
    (14, "\U0001F525\U0001F525"),  # double fire
    (7, "\U0001F525"),  # fire
    (1, "\u2728"),  # sparkles
]

_DEFAULT_README = f"""# Competitive Programming Portfolio

Automatically maintained by [CP-Agent](https://github.com/) -- solving
problems and committing here is fully hands-off.

{_START_MARKER}
{_END_MARKER}
"""


def _streak_emoji(streak: int) -> str:
    for threshold, emoji in _STREAK_EMOJI_THRESHOLDS:
        if streak >= threshold:
            return emoji
    return ""


def _badge(label: str, value: str, color: str) -> str:
    """A shields.io static badge, e.g. ![Total Solved](https://img.shields.io/badge/...)."""
    label_enc = quote(label.replace("-", "--"))
    value_enc = quote(str(value).replace("-", "--"))
    return f"![{label}](https://img.shields.io/badge/{label_enc}-{value_enc}-{color}?style=flat-square)"


_CF_ID_RE = re.compile(r"^(\d+)([A-Za-z]\d*)$")


def _problem_url(platform: Platform, problem_id: str) -> str | None:
    """Best-effort link to the original problem, or None if it can't be built."""
    if platform == Platform.LEETCODE:
        return f"https://leetcode.com/problems/{problem_id}/"
    if platform == Platform.CODEFORCES:
        match = _CF_ID_RE.match(problem_id)
        if match:
            contest, index = match.groups()
            return f"https://codeforces.com/problemset/problem/{contest}/{index}"
    return None


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
            language = _EXT_TO_LANGUAGE.get(ext, ext.lstrip(".").upper() or "Unknown")
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

        # --- Headline badges -------------------------------------------------
        badges = [
            _badge("Total Solved", total_solved, "2E8B57"),
            _badge("Solved Today", today_count, "4C8BF5"),
            _badge("Streak", f"{streak} days {_streak_emoji(streak)}".strip(), "E25822"),
        ]
        for platform in Platform:
            count = platform_counts.get(platform.value, 0)
            color = _PLATFORM_BADGE_COLOR.get(platform, "999999")
            badges.append(_badge(platform.value, count, color))
        lines.append(" ".join(badges))
        lines.append("")
        lines.append(f"_Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}_")
        lines.append("")
        lines.append("---")
        lines.append("")

        # --- By platform -------------------------------------------------
        lines.append("## \U0001F4CA Overview")
        lines.append("")
        lines.append("### By platform")
        lines.append("")
        lines.append("| Platform | Solved |")
        lines.append("|:--|--:|")
        for platform in Platform:
            icon = _PLATFORM_ICON.get(platform, "")
            count = platform_counts.get(platform.value, 0)
            lines.append(f"| {icon} {platform.value} | **{count}** |")
        lines.append("")

        # --- By language -------------------------------------------------
        if language_counts:
            lines.append("### By language")
            lines.append("")
            lang_badges = [
                _badge(lang, count, _LANGUAGE_BADGE_COLOR.get(lang, "555555"))
                for lang, count in sorted(language_counts.items(), key=lambda kv: -kv[1])
            ]
            lines.append(" ".join(lang_badges))
            lines.append("")

        # --- Recent submissions -------------------------------------------------
        lines.append("### \U0001F553 Recent submissions")
        lines.append("")
        lines.append("| Date | Platform | Problem | Solution |")
        lines.append("|:--|:--|:--|:--|")
        for r in recent:
            ts = self._as_date(r.timestamp).isoformat()
            icon = _PLATFORM_ICON.get(r.platform, "")
            url = _problem_url(r.platform, r.problem_id)
            problem_cell = f"[{r.problem_id}]({url})" if url else r.problem_id
            file_link = Path(r.filename).as_posix()
            file_cell = f"[`{Path(r.filename).name}`](./{quote(file_link)})"
            lines.append(f"| {ts} | {icon} {r.platform.value} | {problem_cell} | {file_cell} |")
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