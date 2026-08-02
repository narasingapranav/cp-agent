from __future__ import annotations

from datetime import datetime, timezone

from models import PipelineRecord, Platform


def test_new_database_has_no_processed_submissions(tmp_db):
    assert tmp_db.count_total() == 0
    assert tmp_db.is_processed("1") is False


def test_record_and_lookup_roundtrip(tmp_db):
    record = PipelineRecord(
        submission_id="1",
        platform=Platform.CODEFORCES,
        problem_id="1899A",
        filename="Codeforces/1899/A.py",
        commit_hash="abc123",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    tmp_db.record(record)

    assert tmp_db.is_processed("1") is True
    assert tmp_db.count_total() == 1

    fetched = tmp_db.all_records()[0]
    assert fetched.submission_id == "1"
    assert fetched.commit_hash == "abc123"


def test_filter_unprocessed_excludes_known_ids(tmp_db):
    tmp_db.record(
        PipelineRecord(
            submission_id="1",
            platform=Platform.CODEFORCES,
            problem_id="1899A",
            filename="Codeforces/1899/A.py",
            commit_hash=None,
        )
    )
    unprocessed = tmp_db.filter_unprocessed(["1", "2", "3"])
    assert unprocessed == ["2", "3"]


def test_filter_unprocessed_empty_input_returns_empty(tmp_db):
    assert tmp_db.filter_unprocessed([]) == []


def test_record_upsert_updates_commit_hash(tmp_db):
    base = PipelineRecord(
        submission_id="1",
        platform=Platform.CODEFORCES,
        problem_id="1899A",
        filename="Codeforces/1899/A.py",
        commit_hash=None,
    )
    tmp_db.record(base)
    tmp_db.record(base.model_copy(update={"commit_hash": "deadbeef"}))

    fetched = tmp_db.all_records()[0]
    assert fetched.commit_hash == "deadbeef"
    assert tmp_db.count_total() == 1
