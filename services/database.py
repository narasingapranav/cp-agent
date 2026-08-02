"""
SQLite-backed persistence for CP-Agent.

Responsible for:
* Tracking which submission IDs have already been fully processed (so the
  Submission Agent never re-triggers the pipeline for the same AC verdict).
* Storing enough metadata (filename, commit hash, timestamp) to power the
  Portfolio Agent's statistics and the "recent submissions" table.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from models import Platform, PipelineRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_submissions (
    submission_id   TEXT PRIMARY KEY,
    platform        TEXT NOT NULL,
    problem_id      TEXT NOT NULL,
    filename        TEXT NOT NULL,
    commit_hash     TEXT,
    timestamp       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_processed_platform
    ON processed_submissions (platform);

CREATE INDEX IF NOT EXISTS idx_processed_timestamp
    ON processed_submissions (timestamp);
"""


class Database:
    """Small synchronous wrapper around `sqlite3`.

    A context-manager-per-call pattern is used rather than holding one long
    lived connection, which keeps the service safe to call from multiple
    asyncio tasks / threads (the watchdog observer runs on its own thread).
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #

    def is_processed(self, submission_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM processed_submissions WHERE submission_id = ?",
                (submission_id,),
            ).fetchone()
            return row is not None

    def filter_unprocessed(self, submission_ids: list[str]) -> list[str]:
        """Return the subset of `submission_ids` not yet in the database."""
        if not submission_ids:
            return []
        with self._connect() as conn:
            placeholders = ",".join("?" for _ in submission_ids)
            rows = conn.execute(
                f"SELECT submission_id FROM processed_submissions "
                f"WHERE submission_id IN ({placeholders})",
                submission_ids,
            ).fetchall()
            already = {row["submission_id"] for row in rows}
        return [sid for sid in submission_ids if sid not in already]

    def record(self, record: PipelineRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO processed_submissions
                    (submission_id, platform, problem_id, filename, commit_hash, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(submission_id) DO UPDATE SET
                    commit_hash = excluded.commit_hash,
                    timestamp = excluded.timestamp
                """,
                (
                    record.submission_id,
                    record.platform.value,
                    record.problem_id,
                    record.filename,
                    record.commit_hash,
                    record.timestamp.isoformat(),
                ),
            )

    def all_records(self, platform: Optional[Platform] = None) -> list[PipelineRecord]:
        with self._connect() as conn:
            if platform is not None:
                rows = conn.execute(
                    "SELECT * FROM processed_submissions WHERE platform = ? "
                    "ORDER BY timestamp DESC",
                    (platform.value,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM processed_submissions ORDER BY timestamp DESC"
                ).fetchall()

        return [
            PipelineRecord(
                submission_id=row["submission_id"],
                platform=Platform(row["platform"]),
                problem_id=row["problem_id"],
                filename=row["filename"],
                commit_hash=row["commit_hash"],
                timestamp=row["timestamp"],
            )
            for row in rows
        ]

    def count_total(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM processed_submissions").fetchone()
            return int(row["c"])

    def count_by_language_ext(self) -> dict[str, int]:
        """Count solved problems grouped by file extension (proxy for language)."""
        counts: dict[str, int] = {}
        for rec in self.all_records():
            ext = Path(rec.filename).suffix.lower() or "unknown"
            counts[ext] = counts.get(ext, 0) + 1
        return counts
