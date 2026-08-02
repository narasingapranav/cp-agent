from __future__ import annotations

from pathlib import Path

from agents.documentation_agent import DocumentationAgent
from agents.git_agent import GitAgent
from agents.matching_agent import MatchingAgent
from agents.orchestrator import Orchestrator
from agents.portfolio_agent import PortfolioAgent
from services.filesystem import FileSystemService


def _build_orchestrator(tmp_path: Path, database) -> Orchestrator:
    solutions_dir = tmp_path / "solutions"
    repo_path = tmp_path / "repo"
    solutions_dir.mkdir()
    repo_path.mkdir()

    filesystem = FileSystemService(solutions_dir=solutions_dir, repo_path=repo_path)
    matching_agent = MatchingAgent(filesystem=filesystem)
    documentation_agent = DocumentationAgent(prompts_dir=tmp_path, openai_api_key="")
    portfolio_agent = PortfolioAgent(database=database, repo_path=repo_path)
    git_agent = GitAgent(repo_path=repo_path, dry_run=False, auto_push=False)

    return Orchestrator(
        matching_agent=matching_agent,
        documentation_agent=documentation_agent,
        portfolio_agent=portfolio_agent,
        git_agent=git_agent,
        database=database,
    ), solutions_dir, repo_path


def test_full_pipeline_runs_end_to_end(tmp_path, tmp_db, sample_submission):
    orchestrator, solutions_dir, repo_path = _build_orchestrator(tmp_path, tmp_db)
    (solutions_dir / "1899A.py").write_text("print('accepted')")

    result = orchestrator.run(sample_submission)

    assert result["matched"] is not None
    assert result["documentation"] is not None
    assert result["commit_result"].commit_hash is not None
    assert tmp_db.is_processed(sample_submission.submission_id)
    assert (repo_path / "Codeforces" / "1899" / "A.py").exists()
    assert (repo_path / "Codeforces" / "1899" / "A.md").exists()
    assert (repo_path / "README.md").exists()


def test_pipeline_stops_early_when_no_file_matched(tmp_path, tmp_db, sample_submission):
    orchestrator, solutions_dir, repo_path = _build_orchestrator(tmp_path, tmp_db)
    # No source file written -- matching should fail and the graph should stop.

    result = orchestrator.run(sample_submission)

    assert result.get("matched") is None
    assert "documentation" not in result
    assert not tmp_db.is_processed(sample_submission.submission_id)
