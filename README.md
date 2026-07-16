# Adaptive AI Software Engineering Orchestrator — Kernel v0.1

This repository contains the first, intentionally small control-plane kernel. It controls logged-in coding-agent CLIs, not LLM SDKs or APIs. Single-agent-first is still the default: a task runs on exactly one selected agent, and the Kernel escalates to exactly one more only when execution failure, verification failure, or high analyzed risk/uncertainty/difficulty warrants it (see "Escalation" below). It does not implement full multi-agent orchestration (parallel or collaborating agents) — that remains project-constitution.md's Phase 5.

## Architecture decision

**Stack:** Python 3.10+, standard library, `unittest`, and JSON Lines logging. Claude Code and Codex are subprocess execution targets.

Python provides a small, portable process-control surface. The standard-library-only core keeps the kernel testable without provider credentials, network access, or framework lock-in. JSON Lines is append-only and easy to ingest later into a database, warehouse, or evaluation pipeline.

Starting with a web framework and provider SDKs would make an early API wrapper, but would bypass the existing subscription-authenticated CLI workflows. Putting subprocess logic in each agent would duplicate timeout/error rules. This kernel instead models capability requirements separately from CLI adapters and centralizes process control.

## Repository layout

```
src/adaptive_orchestrator/
  domain.py       # vendor-neutral task, execution, and verification contracts
  agents.py       # CLI adapters: Claude Code and Codex + declared capabilities
  process_runner.py # timeout, output, and process-status collection
  git_snapshot.py # best-effort changed-file and diff collection
  logging.py      # append-only execution telemetry
  kernel.py       # single-agent-first coordinator
  history.py      # reads JSONL telemetry into per-agent metrics
  memory.py       # append-only engineering memory store
  routing.py      # task analysis (capabilities/difficulty/risk/uncertainty) + adaptive agent scoring
  planning.py      # deterministic single-step capability-only selector
  verification.py # runs one or more shell-free verification commands, worst-of aggregation
  escalation.py   # decides whether a second agent's attempt is warranted
  workflow.py     # wires selection + execution + verification + escalation; run() and run_plan()
  cli.py          # `run`, `run-plan`, and `memory` subcommands
  tools.py        # workspace-bounded file/shell/git tool runtime
  example.py      # minimal end-to-end usage without a real CLI agent
tests/            # unit and end-to-end prototype tests
docs/             # architecture and roadmap decisions
```

## Run the prototype

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.example
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Run a task

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli run \
  --workspace . --agent codex \
  --description "Run the unit tests and report the result. Do not modify files." \
  --objective "Confirm the Kernel test suite passes." \
  --capability testing --time-limit 300 \
  --verify-command "python3 -m unittest discover -s tests -v"
```

The command analyzes task text to infer capabilities, difficulty, risk, and uncertainty. It then scores every capable agent using a configurable policy and local execution history, runs one selected agent, then runs the optional verification command(s). It returns the analysis and candidate scores as JSON and writes them to `.orchestrator/executions.jsonl`.

If the task text is easier to keep in a file, use `--description-file` and `--objective-file` instead. The CLI reads UTF-8 text and strips a single trailing newline if present:

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli run \
  --workspace . --agent codex \
  --description-file description.txt \
  --objective-file objective.txt \
  --capability testing --time-limit 300 \
  --verify-command "python3 -m unittest discover -s tests -v"
```

The default policy is only a starting hypothesis: it mildly favors Codex for code/test/debug signals and Claude Code for repository/architecture/planning signals. Both remain eligible whenever they support the analyzed capabilities; selection is not a fixed role assignment. The policy and historical evidence are visible in every routing decision.

Historical success/verification rates are confidence-weighted by sample count — a handful of logged runs pulls a candidate's score toward the same neutral baseline a brand-new agent gets, rather than being fully trusted. Set `Task.cost_limit_usd` and a candidate whose logged average cost (currently tracked for Claude Code only) exceeds it is penalized; leave it unset and cost has no effect on routing.

`--verify-command` is repeatable — every configured check runs (they're treated as independent, e.g. lint + typecheck + test) and the worst outcome wins:

```bash
--verify-command "ruff check ." --verify-command "python3 -m unittest discover -s tests -v"
```

## Run a structured plan

A plan is an explicit, caller-authored ordered list of tasks — there is no inference of steps from free-text prose, since guessing at structure that isn't really there (e.g. treating "the bug in section 2.1" as step "2.1") is a correctness risk, not a convenience. A JSON plan file looks like:

```json
[
  {"description": "Fix the failing login test", "objective": "Login flow works again", "capabilities": ["debugging"]},
  {"description": "Add a regression test for the login fix", "objective": "Prevent recurrence", "capabilities": ["testing"]}
]
```

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli run-plan plan.json \
  --workspace . --agent auto \
  --verify-command "python3 -m unittest discover -s tests -v"
```

Each step runs through the exact same routing/execution/verification/escalation pipeline as `run`. By default the plan stops at the first step that doesn't succeed; pass `--continue-on-failure` to run every step regardless and inspect all of them.

## Record engineering memory

Engineering memory is separate from execution telemetry. It is caller-authored, append-only, and queryable by type, tag, or keyword.

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli memory record \
  --workspace . \
  --type architecture_decision \
  --title "Use JSONL for memory" \
  --summary "Store explicit engineering memory entries in a queryable log." \
  --rationale "Append-only and easy to inspect locally." \
  --tag memory \
  --tag architecture
```

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli memory search \
  --workspace . \
  --tag memory \
  --keyword architecture
```

## Watching a long run

`run` and `run-plan` both accept `--verbose`, which streams the running agent's stdout to stderr as it arrives instead of staying silent until the process exits:

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli run --agent codex --verbose \
  --description "..." --objective "..."
```

stdout still only ever carries the final JSON result — `--verbose` output goes to stderr so scripts parsing stdout are unaffected.

## Escalation

Single-agent-first stays the default. If the first agent's execution fails, its verification command fails or times out, or the router's own analysis flags high risk, uncertainty, or difficulty, the Kernel escalates once to the next-best-scored capable agent and records both attempts (`execution.escalation` in the JSON output). It never escalates past an explicitly requested `--agent`. Tune or disable it with:

```bash
--no-escalation
--escalation-risk-threshold 3          # 0-5, default 3
--escalation-uncertainty-threshold 3   # 0-5, default 3
--escalation-difficulty-threshold 4    # 1-5, default 4 (floors at 1, so this stays higher than the others)
```

## Safety and privacy

This kernel launches coding agents that can modify the configured workspace. Run it only in repositories you trust and with a permission/sandbox mode appropriate to that repository. The default adapters do **not** enable CLI permission-bypass flags.

Execution records may contain task prompts, context, CLI output, and workspace paths. The JSONL logger applies best-effort masking for sensitive key names and common token formats; it is not a secret-scanning or data-loss-prevention system. Do not place credentials or private data in task content. Git diff capture is disabled by default and must be explicitly enabled with `include_git_diff=True`.

`workspace_modified_files` and `workspace_git_diff` describe the workspace after execution. They can include changes that existed before the agent ran; they are not an attribution mechanism.

## CLI compatibility

The adapters use Claude Code's non-interactive `--print` mode and Codex CLI's non-interactive `exec` mode. Their exact flags are CLI-version dependent; validate `claude --help` and `codex exec --help` after upgrading either CLI.

The current implementation was locally validated against Claude Code `2.1.211` and Codex CLI `0.144.5`.

## Current limits

- Routing is rule-based and its initial preference values are not learned from enough production evidence yet.
- Both adapters parse structured CLI output into normalized `ExecutionMetadata`: Claude Code's `--print --output-format json` (verified against `2.1.211`) and Codex CLI's `exec --json` (verified against `0.144.5`). Codex CLI does not expose a cost field the way Claude Code does, so `ExecutionMetadata.cost_usd` stays `None` for Codex executions — this reflects what the CLI actually reports, not a parsing gap.
- Cost limits cannot be reliably enforced for subscription-backed CLIs.
- The execution JSONL log records telemetry; engineering memory lives in a separate JSONL store and is only populated by explicit `memory record` calls.
- Log redaction is best-effort; it cannot guarantee removal of every secret embedded in free text or diffs.

## Next development increment

Tune escalation thresholds from observed telemetry instead of fixed defaults once there's enough of it.
