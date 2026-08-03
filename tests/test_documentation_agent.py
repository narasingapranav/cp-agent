from __future__ import annotations

from pathlib import Path

from agents.documentation_agent import DocumentationAgent
from models import Language, MatchedSolution


def _matched(tmp_path: Path, sample_submission) -> MatchedSolution:
    source = tmp_path / "A.py"
    source.write_text("print('hello')")
    dest = tmp_path / "repo" / "Codeforces" / "1899" / "A.py"
    return MatchedSolution(
        submission=sample_submission,
        source_path=source,
        language=Language.PYTHON,
        destination_path=dest,
    )


def test_offline_fallback_generates_markdown_without_api_key(tmp_path, sample_submission):
    matched = _matched(tmp_path, sample_submission)
    matched.destination_path.parent.mkdir(parents=True, exist_ok=True)
    matched.destination_path.write_text("print('hello')")

    agent = DocumentationAgent(prompts_dir=tmp_path, gemini_api_key="")
    doc = agent.generate(matched)

    assert doc.markdown_path.exists()
    assert "1899A" in doc.markdown
    assert doc.tags == sample_submission.tags


def test_offline_fallback_used_when_llm_raises(tmp_path, sample_submission, monkeypatch):
    matched = _matched(tmp_path, sample_submission)
    matched.destination_path.parent.mkdir(parents=True, exist_ok=True)
    matched.destination_path.write_text("print('hello')")

    agent = DocumentationAgent(prompts_dir=tmp_path, gemini_api_key="fake-key")
    monkeypatch.setattr(
        agent,
        "_llm_analysis",
        lambda matched, source: (_ for _ in ()).throw(RuntimeError("api down")),
    )

    doc = agent.generate(matched)
    assert doc.algorithm == "Unspecified (offline mode)"