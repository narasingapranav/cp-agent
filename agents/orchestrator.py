"""
Orchestrator.

Wires the Matching -> Documentation -> Portfolio -> Git agents together as a
LangGraph `StateGraph`. The Submission Agent runs *outside* this graph (it
produces zero-or-more new submissions per poll); the orchestrator's `run()`
method is invoked once per detected submission, and persists the pipeline
result to the database on success.

Graph shape:

    matching -> documentation -> portfolio -> git -> END
        \\-> END (no local file matched yet)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, TypedDict

from langgraph.graph import END, StateGraph
from rich.console import Console

from agents.documentation_agent import DocumentationAgent
from agents.git_agent import GitAgent
from agents.matching_agent import MatchingAgent
from agents.portfolio_agent import PortfolioAgent
from models import (
    CommitResult,
    GeneratedDocumentation,
    MatchedSolution,
    PipelineRecord,
    Submission,
)
from services.database import Database

console = Console()


class PipelineState(TypedDict, total=False):
    """Shared state threaded through every LangGraph node.

    Each node reads what it needs and writes its own result field(s); using
    `total=False` lets nodes short-circuit cleanly (e.g. `matched=None`)
    without every field needing to be populated up front.
    """

    submission: Submission
    matched: Optional[MatchedSolution]
    documentation: Optional[GeneratedDocumentation]
    commit_result: Optional[CommitResult]
    error: Optional[str]


@dataclass
class Orchestrator:
    """Builds and runs the LangGraph pipeline for a single accepted submission."""

    matching_agent: MatchingAgent
    documentation_agent: DocumentationAgent
    portfolio_agent: PortfolioAgent
    git_agent: GitAgent
    database: Database

    def __post_init__(self) -> None:
        self._graph = self._build_graph().compile()

    # ------------------------------------------------------------------ #
    # Graph construction
    # ------------------------------------------------------------------ #

    def _build_graph(self) -> StateGraph:
        graph: StateGraph = StateGraph(PipelineState)

        graph.add_node("matching", self._matching_node)
        graph.add_node("documentation", self._documentation_node)
        graph.add_node("record", self._record_node)
        graph.add_node("portfolio", self._portfolio_node)
        graph.add_node("git", self._git_node)

        graph.set_entry_point("matching")

        graph.add_conditional_edges(
            "matching",
            self._route_after_matching,
            {"continue": "documentation", "stop": END},
        )
        graph.add_edge("documentation", "record")
        graph.add_edge("record", "portfolio")
        graph.add_edge("portfolio", "git")
        graph.add_edge("git", END)

        return graph

    @staticmethod
    def _route_after_matching(state: PipelineState) -> str:
        return "continue" if state.get("matched") is not None else "stop"

    # ------------------------------------------------------------------ #
    # Nodes -- each independently testable by calling it with a plain dict.
    # ------------------------------------------------------------------ #

    def _matching_node(self, state: PipelineState) -> dict[str, Any]:
        matched = self.matching_agent.match(state["submission"])
        return {"matched": matched}

    def _documentation_node(self, state: PipelineState) -> dict[str, Any]:
        matched = state["matched"]
        assert matched is not None  # guaranteed by the routing edge
        documentation = self.documentation_agent.generate(matched)
        return {"documentation": documentation}

    def _record_node(self, state: PipelineState) -> dict[str, Any]:
        """Persist the pipeline row *before* portfolio stats are computed.

        Recording here (rather than after the git commit) ensures the very
        solve currently being processed is already reflected in the README
        that the Git Agent commits a moment later -- otherwise the
        "total solved" count would always lag one submission behind.
        `commit_hash` is filled in afterwards by `_git_node` via an upsert.
        """
        documentation = state["documentation"]
        assert documentation is not None
        self.database.record(
            PipelineRecord(
                submission_id=documentation.matched.submission.submission_id,
                platform=documentation.matched.submission.platform,
                problem_id=documentation.matched.submission.problem_id,
                filename=str(
                    documentation.matched.destination_path.relative_to(
                        self.git_agent.repo_path
                    )
                ),
                commit_hash=None,
                timestamp=datetime.now(timezone.utc),
            )
        )
        return {}

    def _portfolio_node(self, state: PipelineState) -> dict[str, Any]:
        self.portfolio_agent.update(state.get("documentation"))
        return {}

    def _git_node(self, state: PipelineState) -> dict[str, Any]:
        documentation = state["documentation"]
        assert documentation is not None
        commit_result = self.git_agent.commit_and_push(documentation)

        self.database.record(
            PipelineRecord(
                submission_id=documentation.matched.submission.submission_id,
                platform=documentation.matched.submission.platform,
                problem_id=documentation.matched.submission.problem_id,
                filename=str(
                    documentation.matched.destination_path.relative_to(
                        self.git_agent.repo_path
                    )
                ),
                commit_hash=commit_result.commit_hash,
                timestamp=datetime.now(timezone.utc),
            )
        )
        return {"commit_result": commit_result}

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def run(self, submission: Submission) -> PipelineState:
        """Run the full pipeline for a single accepted submission.

        Returns the final `PipelineState`. If matching failed, `matched`
        will be `None` and no other stages will have run -- the caller
        (`app.py`) should simply retry this submission on a later poll.
        """
        console.rule(f"[bold]{submission.platform.value} {submission.problem_id}[/bold]")
        try:
            result: PipelineState = self._graph.invoke({"submission": submission})
        except Exception as exc:  # noqa: BLE001 - isolate one submission's failure
            console.log(f"[red]\u2717 Pipeline error for {submission.problem_id}:[/red] {exc}")
            return {"submission": submission, "error": str(exc)}
        return result
