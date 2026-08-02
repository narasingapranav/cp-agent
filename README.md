# CP-Agent

**CP-Agent** is an autonomous, agent-based AI system that watches your competitive
programming activity and automatically builds and maintains your GitHub
portfolio — with zero manual git work.

```
Solve Problem → Save file → Submit to Codeforces/LeetCode → Accepted
      → Agent detects acceptance → Matches accepted submission with local file
      → Organizes repository → Generates README update → Generates AI explanation
      → Commits → Pushes to GitHub
```

---

## Table of contents

- [Architecture](#architecture)
- [Project layout](#project-layout)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Example output](#example-output)
- [Testing](#testing)
- [Extending CP-Agent](#extending-cp-agent)
- [Design notes](#design-notes)

---

## Architecture

CP-Agent is built as a set of small, independently testable **agents**, each
wrapping one or more **services**. A [LangGraph](https://github.com/langchain-ai/langgraph)
`StateGraph` orchestrates the agents into a single pipeline that runs once
per newly-accepted submission:

```
                 ┌───────────────────┐
   poll loop →   │ Submission Agent  │  (Codeforces / LeetCode services)
                 └─────────┬─────────┘
                           │ new accepted submissions
                           ▼
                 ┌───────────────────┐
                 │  Matching Agent   │  (filesystem service)
                 └─────────┬─────────┘
                    matched? │ no → stop, retry next poll
                           │ yes
                           ▼
                 ┌───────────────────┐
                 │ Documentation     │  (OpenAI, or offline template)
                 │ Agent             │
                 └─────────┬─────────┘
                           ▼
                 ┌───────────────────┐
                 │  Record (SQLite)  │
                 └─────────┬─────────┘
                           ▼
                 ┌───────────────────┐
                 │  Portfolio Agent  │  (README.md stats)
                 └─────────┬─────────┘
                           ▼
                 ┌───────────────────┐
                 │    Git Agent      │  (GitPython: add, commit, push)
                 └───────────────────┘
```

Each agent depends only on the services/interfaces it needs (constructor
/ dependency injection), so every node in the graph can be unit tested in
isolation by passing in fakes — see [`tests/`](tests/).

| Layer      | Module                              | Responsibility                                             |
|------------|--------------------------------------|--------------------------------------------------------------|
| Agent      | `agents/submission_agent.py`        | Poll judges, filter out already-processed submissions        |
| Agent      | `agents/matching_agent.py`          | Find + copy the local source file for an accepted submission |
| Agent      | `agents/documentation_agent.py`     | Generate a Markdown write-up (LLM or offline fallback)        |
| Agent      | `agents/portfolio_agent.py`         | Regenerate README statistics                                  |
| Agent      | `agents/git_agent.py`               | `git add/commit/push` with a meaningful commit message        |
| Agent      | `agents/orchestrator.py`            | LangGraph wiring of the above                                 |
| Service    | `services/codeforces.py`            | Codeforces `user.status` API client (with retries)             |
| Service    | `services/leetcode.py`              | LeetCode client stub — safely disabled until `LEETCODE_ENABLED=true` |
| Service    | `services/github.py`                | GitHub REST API — verify auth, ensure repo exists              |
| Service    | `services/filesystem.py`            | Scan/match/organize local solution files                       |
| Service    | `services/database.py`              | SQLite persistence (processed submissions, stats)               |

---

## Project layout

```
CP-Agent/
├── app.py                     # Composition root + poll loop
├── config.py                  # Pydantic settings (.env)
├── models.py                  # Shared Pydantic domain models
├── requirements.txt
├── .env.example
├── .gitignore
│
├── agents/
│   ├── submission_agent.py
│   ├── matching_agent.py
│   ├── documentation_agent.py
│   ├── git_agent.py
│   ├── portfolio_agent.py
│   └── orchestrator.py
│
├── services/
│   ├── codeforces.py
│   ├── leetcode.py
│   ├── github.py
│   ├── filesystem.py
│   └── database.py
│
├── memory/                    # solved.db lives here (git-ignored)
├── repo/                      # Your git-managed portfolio (Codeforces/, LeetCode/)
├── solutions/                 # Point your editor here — drop solved files
├── prompts/                   # LLM prompt templates
├── logs/                      # Rotated app + rich console logs
└── tests/                     # pytest suite (36 tests)
```

---

## Installation

**Requirements:** Python 3.11+, git, a Codeforces handle, and (optionally) a
GitHub personal access token and an OpenAI API key.

```bash
git clone <your-fork-or-this-repo> CP-Agent
cd CP-Agent

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# now edit .env — see Configuration below
```

---

## Configuration

All configuration lives in `.env` (see [`.env.example`](.env.example) for the
full annotated list). The essentials:

```dotenv
# Required to poll for accepted submissions
CODEFORCES_HANDLE=your_handle

# Required for CP-Agent to push commits to GitHub.
# Personal access token needs "repo" scope: https://github.com/settings/tokens
GITHUB_TOKEN=ghp_xxx
GITHUB_USERNAME=your-username
GITHUB_REPO_NAME=competitive-programming

# Optional — enables LLM-generated write-ups. Without this, CP-Agent still
# runs end-to-end and produces clearly-labeled offline documentation.
OPENAI_API_KEY=

# Where your editor saves solved files, and where the git-managed portfolio lives.
LOCAL_SOLUTIONS_DIR=./solutions
REPO_PATH=./repo

POLL_INTERVAL_SECONDS=60
DRY_RUN=false        # true = run the full pipeline but skip git commit/push
AUTO_PUSH=true
```

If `GITHUB_TOKEN`/`GITHUB_USERNAME`/`GITHUB_REPO_NAME` are left blank, CP-Agent
still commits locally to `REPO_PATH` — useful for trying it out before wiring
up GitHub.

---

## Usage

**Run continuously** (the intended production mode — polls Codeforces every
`POLL_INTERVAL_SECONDS`):

```bash
python app.py
```

**Run a single poll-and-process cycle** (useful for testing, or for driving
CP-Agent from cron/systemd instead of its own loop):

```bash
python app.py --once
```

**Dry run** (exercises the whole pipeline — matching, docs, README — but
skips git commit/push):

```bash
python app.py --dry-run
```

**Workflow in practice:**

1. Solve a problem in your editor; save the file under `LOCAL_SOLUTIONS_DIR`
   (e.g. `solutions/1899A.py`, or `solutions/1899/A.cpp`).
2. Submit it on Codeforces.
3. Once it's `Accepted`, CP-Agent's next poll detects it, matches it to your
   saved file, generates a write-up, updates `repo/README.md`, and commits +
   pushes automatically. Stop `app.py` any time with `Ctrl+C` — it shuts down
   gracefully.

---

## Example output

Console (Rich) output for a single detected acceptance:

```
[17:04:21] ✓ Accepted detected Codeforces 1899A (submission 999001)
──────────────────────────── Codeforces 1899A ────────────────────────────
[17:04:21] ✓ File matched 1899A.py -> repo/Codeforces/1899/A.py
[17:04:21] ✓ Documentation generated repo/Codeforces/1899/A.md
[17:04:21] ✓ README updated (1 total solved)
[17:04:21] ✓ Commit created d18dbc6d: CF 1899A: Greedy Observation
[17:04:21] ✓ Push successful (main)
```

Generated `repo/Codeforces/1899/A.md`:

```markdown
# 1899A — Splitting Items

**Platform:** Codeforces
**Problem link:** https://codeforces.com/problemset/problem/1899/A
**Language:** python
**Tags:** greedy, games

## Summary

Accepted solution for Splitting Items on Codeforces.

## Key Observation

...

## Algorithm

Greedy

## Complexity

| Time | Space |
|------|-------|
| O(n log n) | O(n) |
```

Auto-maintained section of `repo/README.md`:

```markdown
<!-- CP-AGENT:START -->

## 📊 Statistics

- **Total solved:** 1
- **Solved today:** 1
- **Current streak:** 1 day(s)

### By platform

| Platform | Solved |
|----------|--------|
| Codeforces | 1 |
| LeetCode | 0 |

### By language

| Language | Solved |
|----------|--------|
| Python | 1 |

### Recent submissions

| Date | Platform | Problem | File |
|------|----------|---------|------|
| 2026-08-02 | Codeforces | 1899A | `Codeforces/1899/A.py` |

<!-- CP-AGENT:END -->
```

Everything outside the `CP-AGENT:START`/`END` markers is left untouched, so
you can freely add your own intro/bio above this section.

---

## Testing

```bash
pip install -r requirements.txt   # includes pytest, pytest-mock, freezegun
pytest -q
```

36 tests cover every service and agent in isolation (mocked HTTP sessions,
temp directories, temp SQLite databases, and a real local git repo for the
Git Agent), plus two end-to-end orchestrator tests that run the full
LangGraph pipeline against a temporary filesystem.

---

## Extending CP-Agent

The project was deliberately structured so each of these is a small,
localized change:

| Feature                     | Where to add it |
|------------------------------|------------------|
| AtCoder / CodeChef / HackerRank | New `services/<platform>.py` implementing `fetch_recent_submissions()`, wired into `SubmissionAgent` in `app.py` (same pattern as `leetcode.py`) |
| AI code review               | New `agents/review_agent.py`, add a graph node between `matching` and `documentation` |
| Topic / difficulty prediction | Extend `DocumentationAgent._llm_analysis` prompt + `GeneratedDocumentation` model |
| Discord / Telegram notifications | New `services/notifications.py`, call from a new final graph node after `git` |
| Dashboard                    | A small FastAPI/Flask app reading `services/database.py` — no changes needed to the pipeline |
| Daily/weekly/monthly reports  | New agent reading `Database.all_records()` on a schedule, independent of the main poll loop |

`LeetCodeService` in `services/leetcode.py` is already implemented as a
disabled-by-default stub with the exact same interface as
`CodeforcesService`, specifically to make this pattern concrete.

---

## Design notes

- **Idempotency & safety.** Every processed submission is recorded in SQLite
  by `submission_id`; the Submission Agent filters these out before they
  ever reach the graph, so re-running or restarting CP-Agent never produces
  duplicate commits.
- **Graceful degradation.** A Codeforces outage doesn't block LeetCode (or
  vice versa) — failures are isolated per-platform. A missing OpenAI key
  doesn't block documentation — it falls back to a clearly-labeled offline
  template. A missing local file doesn't crash the pipeline — the Matching
  Agent returns `None` and the graph stops early, to be retried next poll.
- **`DRY_RUN`.** Every agent still runs; only the Git Agent's actual
  `commit`/`push` calls are skipped, so you can safely validate the whole
  pipeline against a real repo first.
- **Copy, not move.** The Matching Agent copies solution files into `repo/`
  rather than moving them, so your `solutions/` scratch directory is never
  mutated by CP-Agent.
