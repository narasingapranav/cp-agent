from __future__ import annotations

from datetime import datetime, timezone

import git

from agents.git_agent import GitAgent
from models import GeneratedDocumentation, Language, MatchedSolution


def _make_doc(tmp_path, sample_submission) -> GeneratedDocumentation:
    dest = tmp_path / "Codeforces" / "1899" / "A.py"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("print('ok')")
    matched = MatchedSolution(
        submission=sample_submission,
        source_path=dest,
        language=Language.PYTHON,
        destination_path=dest,
    )
    md_path = dest.with_suffix(".md")
    md_path.write_text("# doc")
    return GeneratedDocumentation(
        matched=matched,
        summary="s",
        key_observation="k",
        algorithm="Greedy",
        time_complexity="O(n)",
        space_complexity="O(1)",
        tags=["greedy"],
        markdown="# doc",
        markdown_path=md_path,
    )


def test_commit_message_format(tmp_path, sample_submission):
    agent = GitAgent(repo_path=tmp_path)
    doc = _make_doc(tmp_path, sample_submission)
    message = agent.commit_message_for(doc)
    assert message == "CF 1899A: Greedy"


def test_commit_and_push_dry_run_does_not_touch_git(tmp_path, sample_submission):
    doc = _make_doc(tmp_path, sample_submission)
    agent = GitAgent(repo_path=tmp_path, dry_run=True)

    result = agent.commit_and_push(doc)

    assert result.dry_run is True
    assert result.commit_hash is None
    assert not (tmp_path / ".git").exists()


def test_commit_and_push_creates_real_commit(tmp_path, sample_submission):
    doc = _make_doc(tmp_path, sample_submission)
    agent = GitAgent(repo_path=tmp_path, dry_run=False, auto_push=False)

    result = agent.commit_and_push(doc)

    assert result.commit_hash is not None
    repo = git.Repo(tmp_path)
    assert repo.head.commit.message == "CF 1899A: Greedy"


def test_commit_and_push_second_call_with_no_changes_is_noop(tmp_path, sample_submission):
    doc = _make_doc(tmp_path, sample_submission)
    agent = GitAgent(repo_path=tmp_path, dry_run=False, auto_push=False)

    first = agent.commit_and_push(doc)
    second = agent.commit_and_push(doc)

    assert first.commit_hash is not None
    assert second.commit_hash is None
    assert second.pushed is False
