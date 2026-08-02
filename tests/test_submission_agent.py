from __future__ import annotations

from agents.submission_agent import SubmissionAgent
from models import PipelineRecord


class _FakeService:
    def __init__(self, submissions):
        self._submissions = submissions

    def fetch_recent_submissions(self):
        return self._submissions


class _FailingService:
    def fetch_recent_submissions(self):
        raise RuntimeError("network down")


def test_check_new_acceptances_returns_all_when_db_empty(tmp_db, sample_submission):
    agent = SubmissionAgent(codeforces=_FakeService([sample_submission]), database=tmp_db)
    result = agent.check_new_acceptances()
    assert result == [sample_submission]


def test_check_new_acceptances_excludes_already_processed(tmp_db, sample_submission):
    tmp_db.record(
        PipelineRecord(
            submission_id=sample_submission.submission_id,
            platform=sample_submission.platform,
            problem_id=sample_submission.problem_id,
            filename="Codeforces/1899/A.py",
            commit_hash="abc",
        )
    )
    agent = SubmissionAgent(codeforces=_FakeService([sample_submission]), database=tmp_db)
    result = agent.check_new_acceptances()
    assert result == []


def test_check_new_acceptances_isolates_platform_failures(tmp_db, sample_submission):
    agent = SubmissionAgent(
        codeforces=_FailingService(),
        database=tmp_db,
        leetcode=_FakeService([]),
    )
    # Should not raise even though Codeforces polling fails.
    result = agent.check_new_acceptances()
    assert result == []


def test_check_new_acceptances_merges_multiple_platforms(tmp_db, sample_submission):
    other = sample_submission.model_copy(update={"submission_id": "999"})
    agent = SubmissionAgent(
        codeforces=_FakeService([sample_submission]),
        database=tmp_db,
        leetcode=_FakeService([other]),
    )
    result = agent.check_new_acceptances()
    ids = {s.submission_id for s in result}
    assert ids == {sample_submission.submission_id, "999"}
