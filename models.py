"""
Shared domain models for CP-Agent.

Keeping these in one module (rather than duplicating ad-hoc dicts across
agents/services) is what lets each LangGraph node validate its inputs/outputs
and lets tests construct fixtures cheaply.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class Platform(str, Enum):
    CODEFORCES = "Codeforces"
    LEETCODE = "LeetCode"


class Verdict(str, Enum):
    ACCEPTED = "OK"
    WRONG_ANSWER = "WRONG_ANSWER"
    TIME_LIMIT_EXCEEDED = "TIME_LIMIT_EXCEEDED"
    RUNTIME_ERROR = "RUNTIME_ERROR"
    COMPILATION_ERROR = "COMPILATION_ERROR"
    OTHER = "OTHER"


class Language(str, Enum):
    PYTHON = "python"
    CPP = "cpp"
    JAVA = "java"
    UNKNOWN = "unknown"

    @classmethod
    def from_extension(cls, extension: str) -> "Language":
        mapping = {
            ".py": cls.PYTHON,
            ".cpp": cls.CPP,
            ".cc": cls.CPP,
            ".cxx": cls.CPP,
            ".java": cls.JAVA,
        }
        return mapping.get(extension.lower(), cls.UNKNOWN)


class Submission(BaseModel):
    """A single accepted submission fetched from a judge's API."""

    submission_id: str
    platform: Platform
    problem_id: str = Field(..., description="e.g. '1899A' for Codeforces problem 1899, index A")
    contest_id: Optional[str] = None
    problem_index: Optional[str] = None
    problem_name: Optional[str] = None
    problem_url: Optional[str] = None
    verdict: Verdict
    language_raw: str = Field(default="", description="Raw language string reported by the judge")
    submitted_at: datetime
    tags: list[str] = Field(default_factory=list)
    rating: Optional[int] = None


class MatchedSolution(BaseModel):
    """Result of pairing a Submission with a local source file."""

    submission: Submission
    source_path: Path
    language: Language
    destination_path: Path


class GeneratedDocumentation(BaseModel):
    """LLM (or offline template) generated write-up for a solved problem."""

    matched: MatchedSolution
    summary: str
    key_observation: str
    algorithm: str
    time_complexity: str
    space_complexity: str
    tags: list[str]
    markdown: str
    markdown_path: Path


class CommitResult(BaseModel):
    """Outcome of the Git Agent's commit + push step."""

    matched: MatchedSolution
    commit_message: str
    commit_hash: Optional[str] = None
    pushed: bool = False
    dry_run: bool = False


class PipelineRecord(BaseModel):
    """Row persisted to SQLite once a submission has been fully processed."""

    submission_id: str
    platform: Platform
    problem_id: str
    filename: str
    commit_hash: Optional[str]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
