"""
Documentation Agent.

Generates a Markdown write-up (problem summary, key observation, algorithm,
complexity, tags) for each accepted solution, using an LLM when an OpenAI
API key is configured, and falling back to a deterministic offline template
otherwise so the whole pipeline remains runnable with zero paid API access.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console

from models import GeneratedDocumentation, MatchedSolution

console = Console()

_MARKDOWN_TEMPLATE = """\
# {problem_id} — {problem_name}

**Platform:** {platform}
**Problem link:** {problem_url}
**Language:** {language}
**Tags:** {tags}

## Summary

{summary}

## Key Observation

{key_observation}

## Algorithm

{algorithm}

## Complexity

| Time | Space |
|------|-------|
| {time_complexity} | {space_complexity} |
"""


@dataclass
class DocumentationAgent:
    """Produces a `GeneratedDocumentation` record for a matched solution.

    Parameters
    ----------
    prompts_dir:
        Directory containing `documentation_prompt.txt`.
    openai_api_key:
        When non-empty, the agent calls the OpenAI Chat Completions API.
        When empty, `_offline_analysis` is used instead -- this keeps the
        project fully runnable without any paid API key, per the "future
        OpenAI integration" requirement (the LLM path is additive, not
        required).
    """

    prompts_dir: Path
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    def generate(self, matched: MatchedSolution) -> GeneratedDocumentation:
        source_code = self._read_source_safely(matched.source_path)
        analysis = self._analyze(matched, source_code)

        markdown = _MARKDOWN_TEMPLATE.format(
            problem_id=matched.submission.problem_id,
            problem_name=matched.submission.problem_name or "Untitled",
            platform=matched.submission.platform.value,
            problem_url=matched.submission.problem_url or "N/A",
            language=matched.language.value,
            tags=", ".join(analysis["tags"]) if analysis["tags"] else "n/a",
            summary=analysis["summary"],
            key_observation=analysis["key_observation"],
            algorithm=analysis["algorithm"],
            time_complexity=analysis["time_complexity"],
            space_complexity=analysis["space_complexity"],
        )

        markdown_path = matched.destination_path.with_suffix(".md")
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(markdown, encoding="utf-8")

        console.log(f"[green]\u2713 Documentation generated[/green] {markdown_path}")

        return GeneratedDocumentation(
            matched=matched,
            summary=analysis["summary"],
            key_observation=analysis["key_observation"],
            algorithm=analysis["algorithm"],
            time_complexity=analysis["time_complexity"],
            space_complexity=analysis["space_complexity"],
            tags=analysis["tags"],
            markdown=markdown,
            markdown_path=markdown_path,
        )

    # ------------------------------------------------------------------ #
    # Analysis strategies
    # ------------------------------------------------------------------ #

    def _analyze(self, matched: MatchedSolution, source_code: str) -> dict:
        if self.openai_api_key:
            try:
                return self._llm_analysis(matched, source_code)
            except Exception as exc:  # noqa: BLE001 - fall back rather than crash the pipeline
                console.log(
                    f"[yellow]\u26a0 LLM documentation failed, "
                    f"using offline fallback:[/yellow] {exc}"
                )
        return self._offline_analysis(matched, source_code)

    def _llm_analysis(self, matched: MatchedSolution, source_code: str) -> dict:
        """Call the OpenAI API to analyze the solution. Requires `openai` package."""
        from openai import OpenAI  # imported lazily so the dependency is optional at runtime

        client = OpenAI(api_key=self.openai_api_key)
        prompt_template = (self.prompts_dir / "documentation_prompt.txt").read_text(
            encoding="utf-8"
        )
        prompt = prompt_template.format(
            problem_name=matched.submission.problem_name or "Unknown",
            platform=matched.submission.platform.value,
            problem_id=matched.submission.problem_id,
            problem_url=matched.submission.problem_url or "N/A",
            known_tags=", ".join(matched.submission.tags) or "none",
            language=matched.language.value,
            source_code=source_code[:6000],  # guard against oversized prompts
        )

        response = client.chat.completions.create(
            model=self.openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)

        return {
            "summary": data.get("summary", "N/A"),
            "key_observation": data.get("key_observation", "N/A"),
            "algorithm": data.get("algorithm", "N/A"),
            "time_complexity": data.get("time_complexity", "N/A"),
            "space_complexity": data.get("space_complexity", "N/A"),
            "tags": list(data.get("tags", [])) or matched.submission.tags,
        }

    @staticmethod
    def _offline_analysis(matched: MatchedSolution, source_code: str) -> dict:
        """Deterministic, dependency-free fallback used when no LLM key is configured.

        This intentionally does not try to be clever about algorithm
        detection -- it produces an honest, clearly-labeled placeholder that
        the user (or a later LLM pass) can refine, rather than guessing.
        """
        line_count = len(source_code.splitlines())
        tags = matched.submission.tags or ["untagged"]
        return {
            "summary": (
                f"Accepted solution for {matched.submission.problem_name or matched.submission.problem_id} "
                f"on {matched.submission.platform.value}."
            ),
            "key_observation": (
                "Not generated (no OPENAI_API_KEY configured) -- add one to enable "
                "LLM-authored insights, or edit this file manually."
            ),
            "algorithm": "Unspecified (offline mode)",
            "time_complexity": "N/A",
            "space_complexity": "N/A",
            "tags": tags,
        }

    @staticmethod
    def _read_source_safely(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
