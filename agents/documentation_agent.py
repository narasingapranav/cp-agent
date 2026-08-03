"""
Documentation Agent.

Generates a Markdown write-up (problem summary, key observation, algorithm,
complexity, tags) for each accepted solution, using an LLM when a Gemini
API key is configured, and falling back to a heuristic offline analysis
otherwise so the whole pipeline remains runnable with zero paid API access.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich.console import Console

from models import GeneratedDocumentation, MatchedSolution

console = Console()

_PLATFORM_BADGE_COLOR = {"Codeforces": "1F8ACB", "LeetCode": "FFA116"}
_LANGUAGE_BADGE_COLOR = {
    "python": "3776AB", "cpp": "00599C", "java": "007396", "javascript": "F7DF1E",
    "typescript": "3178C6", "go": "00ADD8", "rust": "DEA584", "c": "A8B9CC",
}
_LANG_TO_FENCE = {
    "python": "python", "cpp": "cpp", "java": "java", "javascript": "javascript",
    "typescript": "typescript", "go": "go", "rust": "rust", "c": "c",
}


def _badge(label: str, value: str, color: str) -> str:
    from urllib.parse import quote
    return (
        f"![{label}](https://img.shields.io/badge/"
        f"{quote(label)}-{quote(str(value))}-{color}?style=flat-square)"
    )


_MARKDOWN_TEMPLATE = """\
# {emoji} {problem_id} — {problem_name}

{badges}

**Problem link:** [{problem_url_label}]({problem_url}) &nbsp;|&nbsp; **Solved:** {solved_date}

---

## \U0001F4DD Summary

{summary}

## \U0001F50D Key Observation

{key_observation}

## \u2699\uFE0F Algorithm

**{algorithm}**

## \u23F1\uFE0F Complexity

| Time | Space |
|:--:|:--:|
| `{time_complexity}` | `{space_complexity}` |

## \U0001F3F7\uFE0F Tags

{tags}

<details>
<summary>\U0001F4BB View solution</summary>

```{code_fence}
{source_code}
```

</details>
"""


@dataclass
class DocumentationAgent:
    """Produces a `GeneratedDocumentation` record for a matched solution.

    Parameters
    ----------
    prompts_dir:
        Directory containing `documentation_prompt.txt`.
    gemini_api_key:
        When non-empty, the agent calls the Gemini API. When empty,
        `_offline_analysis` is used instead -- this keeps the project fully
        runnable without any paid API key (the LLM path is additive, not
        required). The offline path uses lightweight source-code heuristics
        rather than a bare placeholder, so write-ups stay useful either way.
    """

    prompts_dir: Path
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    max_embedded_code_chars: int = 4000

    def generate(self, matched: MatchedSolution) -> GeneratedDocumentation:
        source_code = self._read_source_safely(matched.source_path)
        analysis = self._analyze(matched, source_code)

        platform = matched.submission.platform.value
        emoji = "\U0001F535" if platform == "Codeforces" else "\U0001F7E0"
        tags = analysis["tags"] or ["untagged"]

        badges = " ".join([
            _badge("Platform", platform, _PLATFORM_BADGE_COLOR.get(platform, "999999")),
            _badge("Language", matched.language.value, _LANGUAGE_BADGE_COLOR.get(matched.language.value, "555555")),
        ])
        tag_badges = " ".join(f"`{t}`" for t in tags)

        embedded_code = source_code
        if len(embedded_code) > self.max_embedded_code_chars:
            embedded_code = embedded_code[: self.max_embedded_code_chars] + "\n... (truncated)"

        markdown = _MARKDOWN_TEMPLATE.format(
            emoji=emoji,
            problem_id=matched.submission.problem_id,
            problem_name=matched.submission.problem_name or "Untitled",
            badges=badges,
            problem_url_label="View on " + platform,
            problem_url=matched.submission.problem_url or "#",
            solved_date=matched.submission.submitted_at.strftime("%Y-%m-%d")
            if matched.submission.submitted_at else datetime.now().strftime("%Y-%m-%d"),
            summary=analysis["summary"],
            key_observation=analysis["key_observation"],
            algorithm=analysis["algorithm"],
            time_complexity=analysis["time_complexity"],
            space_complexity=analysis["space_complexity"],
            tags=tag_badges,
            code_fence=_LANG_TO_FENCE.get(matched.language.value, ""),
            source_code=embedded_code or "(source unavailable)",
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
        if self.gemini_api_key:
            try:
                return self._llm_analysis(matched, source_code)
            except Exception as exc:  # noqa: BLE001 - fall back rather than crash the pipeline
                console.log(
                    f"[yellow]\u26a0 LLM documentation failed, "
                    f"using offline fallback:[/yellow] {exc}"
                )
        return self._offline_analysis(matched, source_code)

    def _llm_analysis(self, matched: MatchedSolution, source_code: str) -> dict:
        """Call the Gemini API to analyze the solution. Requires `google-genai` package."""
        from google import genai  # imported lazily so the dependency is optional at runtime
        from google.genai import types

        client = genai.Client(api_key=self.gemini_api_key)
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

        response = client.models.generate_content(
            model=self.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )
        content = response.text or "{}"
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
        """Heuristic, dependency-free fallback used when no LLM key is configured.

        This does simple pattern-matching over the source (loop nesting,
        recursion, common library calls) to produce a genuinely useful --
        if approximate -- write-up instead of a bare "Unspecified"
        placeholder. Estimates are clearly labeled as such so they are
        never mistaken for an authoritative complexity analysis.
        """
        code = source_code or ""
        lower = code.lower()
        problem_name = matched.submission.problem_name or matched.submission.problem_id

        # --- structural signals -------------------------------------------------
        max_loop_nesting = DocumentationAgent._max_loop_nesting(code)
        is_recursive = DocumentationAgent._looks_recursive(code)
        uses_sort = bool(re.search(r"\bsort(ed)?\s*\(|\.sort\s*\(|Arrays\.sort|Collections\.sort", code))
        uses_hashmap = bool(re.search(r"\b(dict|set|unordered_map|unordered_set|HashMap|HashSet)\b", code))
        uses_dp_array = bool(re.search(r"\bdp\s*[\[=]|memo\s*[\[=]|@lru_cache|@cache\b", code))
        uses_two_pointer_hint = bool(re.search(r"\bleft\b.*\bright\b|\blo\b.*\bhi\b", lower, re.S))
        uses_bfs_dfs = bool(re.search(r"\bqueue\b|deque\(|\bstack\b|\bvisited\b", lower))
        uses_binary_search = bool(re.search(r"bisect|binary\s*search|while\s*\(?\s*lo\s*<=?\s*hi", lower))

        # --- technique guess -------------------------------------------------
        techniques = []
        if uses_dp_array:
            techniques.append("Dynamic programming")
        if uses_binary_search:
            techniques.append("Binary search")
        if uses_bfs_dfs:
            techniques.append("Graph/tree traversal (BFS/DFS)")
        if is_recursive and not uses_dp_array:
            techniques.append("Recursion")
        if uses_two_pointer_hint and max_loop_nesting <= 1:
            techniques.append("Two pointers")
        if uses_hashmap:
            techniques.append("Hash map/set lookup")
        if uses_sort:
            techniques.append("Sorting")
        if not techniques:
            techniques.append("Direct simulation / brute force")
        algorithm = " + ".join(techniques)

        # --- complexity guess (heuristic, clearly labeled) -------------------------------------------------
        if uses_dp_array:
            time_complexity = "~O(n\u00b2) (estimated -- DP table detected)"
        elif max_loop_nesting >= 2:
            time_complexity = f"~O(n^{max_loop_nesting}) (estimated -- {max_loop_nesting} nested loops)"
        elif uses_sort:
            time_complexity = "~O(n log n) (estimated -- sort detected)"
        elif uses_binary_search:
            time_complexity = "~O(log n) (estimated -- binary search detected)"
        elif max_loop_nesting == 1 or is_recursive:
            time_complexity = "~O(n) (estimated)"
        else:
            time_complexity = "O(1)\u2013O(n) (estimated -- could not confidently infer)"

        space_complexity = "~O(n) (estimated)" if (uses_hashmap or uses_dp_array) else "~O(1) (estimated)"

        tags = list(matched.submission.tags) or []
        for tech, tag in [
            (uses_dp_array, "dp"), (uses_binary_search, "binary-search"),
            (uses_bfs_dfs, "graph"), (is_recursive, "recursion"),
            (uses_hashmap, "hash-map"), (uses_sort, "sorting"),
        ]:
            if tech and tag not in tags:
                tags.append(tag)
        if not tags:
            tags = ["untagged"]

        return {
            "summary": f"Accepted solution for {problem_name} on {matched.submission.platform.value}.",
            "key_observation": (
                "Auto-generated from source-code heuristics (no GEMINI_API_KEY configured) -- "
                "set one in .env for LLM-authored insight, or edit this section manually."
            ),
            "algorithm": algorithm,
            "time_complexity": time_complexity,
            "space_complexity": space_complexity,
            "tags": tags,
        }

    @staticmethod
    def _max_loop_nesting(code: str) -> int:
        """Rough max nesting depth of for/while loops, based on indentation/braces."""
        max_depth = depth = 0
        for line in code.splitlines():
            stripped = line.strip()
            if re.match(r"^(for|while)\b", stripped) or re.match(r"^.*\b(for|while)\s*\(", stripped):
                depth += 1
                max_depth = max(max_depth, depth)
            # crude dedent heuristic for brace-based languages
            depth -= stripped.count("}") if "{" in code else 0
        return max_depth if max_depth else (1 if re.search(r"\b(for|while)\b", code) else 0)

    @staticmethod
    def _looks_recursive(code: str) -> bool:
        match = re.search(r"def\s+(\w+)\s*\(|(\w+)\s*\([^)]*\)\s*\{", code)
        if not match:
            return False
        name = next(g for g in match.groups() if g)
        # crude check: function name appears again later in the body (self-call)
        return code.count(name) >= 2

    @staticmethod
    def _read_source_safely(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""