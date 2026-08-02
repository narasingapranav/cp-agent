from __future__ import annotations

from datetime import datetime, timezone

from agents.portfolio_agent import PortfolioAgent
from models import PipelineRecord, Platform


def test_update_creates_readme_with_stats(tmp_path, tmp_db):
    tmp_db.record(
        PipelineRecord(
            submission_id="1",
            platform=Platform.CODEFORCES,
            problem_id="1899A",
            filename="Codeforces/1899/A.py",
            commit_hash="abc",
            timestamp=datetime.now(timezone.utc),
        )
    )
    agent = PortfolioAgent(database=tmp_db, repo_path=tmp_path)
    readme_path = agent.update()

    content = readme_path.read_text()
    assert "Total solved:** 1" in content
    assert "1899A" in content
    assert "Python" in content


def test_update_preserves_hand_written_content_outside_markers(tmp_path, tmp_db):
    repo_path = tmp_path
    repo_path.mkdir(parents=True, exist_ok=True)
    readme = repo_path / "README.md"
    readme.write_text("# My Custom Title\n\nSome hand-written intro.\n")

    agent = PortfolioAgent(database=tmp_db, repo_path=repo_path)
    agent.update()

    content = readme.read_text()
    assert "My Custom Title" in content
    assert "Some hand-written intro." in content
    assert "Statistics" in content


def test_update_is_idempotent(tmp_path, tmp_db):
    agent = PortfolioAgent(database=tmp_db, repo_path=tmp_path)
    agent.update()
    first = agent.readme_path.read_text()
    agent.update()
    second = agent.readme_path.read_text()
    assert first == second
