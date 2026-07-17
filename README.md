# Adaptive AI Software Engineering Orchestrator — Kernel v0.1

This repository contains the first, intentionally small control-plane kernel. It controls logged-in coding-agent CLIs, not LLM SDKs or APIs. Single-agent-first is still the default: the workflow runs one selected agent first and escalates to exactly one more only when execution failure, verification failure, or high analyzed risk/uncertainty/difficulty warrants it (see "Escalation" below). It does not implement full multi-agent orchestration (parallel or collaborating agents) — that remains project-constitution.md's Phase 5.

## Architecture decision

**Stack:** Python 3.10+, standard library, `unittest`, and JSON Lines logging. Claude Code and Codex are subprocess execution targets.

Python provides a small, portable process-control surface. The standard-library-only core keeps the kernel testable without provider credentials, network access, or framework lock-in. JSON Lines is append-only and easy to ingest later into a database, warehouse, or evaluation pipeline.

Starting with a web framework and provider SDKs would make an early API wrapper, but would bypass the existing subscription-authenticated CLI workflows. Putting subprocess logic in each agent would duplicate timeout/error rules. This kernel instead models capability requirements separately from CLI adapters and centralizes process control.

## Repository layout

```
src/adaptive_orchestrator/
  __init__.py     # public re-exports (Agent, Task, OrchestratorKernel, EngineeringMemoryStore, ...)
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
  cli.py          # `run`, `run-plan`, `plan`, and `memory` subcommands
  shell.py        # interactive session UX over the existing CLI dispatch
  usage.py        # reads locally available Codex/Claude account information
  tools.py        # workspace-bounded file/shell/git tool runtime
  example.py      # minimal end-to-end usage without a real CLI agent
tests/            # unit and end-to-end prototype tests
docs/             # architecture and roadmap decisions
```

Adaptive routing 개선 작업은 다음 문서에서 추적한다.

- [설계: Evidence-First Stratified Temporal Routing](docs/adaptive-routing-v2.md)
- [연구 교차검토](docs/routing-research-review.md)
- [평가 프로토콜](docs/routing-evaluation-protocol.md)
- [Claude 독립 검토와 반영 판단](docs/routing-claude-review.md)
- [진행상황과 이어하기](docs/adaptive-routing-progress.md)

설계는 아직 runtime 구현이 아니다. 현재의 적은 legacy telemetry로 복잡한
bandit을 바로 활성화하지 않고, typed evaluator와 durable event부터 구현하는
순서를 택했다.

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

To pin a model or Codex reasoning effort for a routed command, pass the corresponding adapter options. They are accepted by `run`, `run-plan`, and `plan generate`:

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli run \
  --workspace . --agent codex:gpt-5.5:high \
  --codex-model gpt-5.5 --codex-reasoning-effort high \
  --claude-model opus \
  --description "Run the unit tests" --objective "Confirm the suite passes"
```

Configured variants receive derived registry IDs (`claude-code:<model>` and `codex:<model>:<reasoning-effort>`; omitted parts are left out). Use that derived ID with `--agent` to request a specific variant, or leave `--agent auto` to route between the configured variants. Execution logs retain both the exact variant ID and its stable vendor base ID. The current router nevertheless reads exact-ID metrics only, so routing history does **not** yet back off across model changes; that is an explicit next-step gap.

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

## Generate a plan

`plan validate` checks that a JSON file matches the plan schema expected by `run-plan`. `plan generate` asks an existing CLI agent to turn a one-line request into that same JSON shape, then validates the result with the same workflow/verifier stack. If you do not pass `--output`, it writes `plan.json` in the workspace.

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli plan generate \
  "Add a regression test for the login bug" \
  --workspace . \
  --output plans/login-plan.json \
  --agent auto

sed -n '1,200p' plans/login-plan.json

PYTHONPATH=src python3 -m adaptive_orchestrator.cli plan validate plans/login-plan.json

PYTHONPATH=src python3 -m adaptive_orchestrator.cli run-plan plans/login-plan.json \
  --workspace . --agent auto \
  --verify-command "python3 -m unittest discover -s tests -v"
```

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

## Interactive shell

If you want to set the workspace and agent once, then issue short commands repeatedly, use the stdlib shell on top of the existing CLI dispatch:

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.shell
Adaptive Orchestrator shell. Type help or ? for commands; task <request> for a quick run.
adaptive[auto:adaptive-ai-orchestrator]> workspace .
Workspace set to /home/leo/adaptive-ai-orchestrator
adaptive[auto:adaptive-ai-orchestrator]> agent codex
Agent set to codex
adaptive[codex:adaptive-ai-orchestrator]> set verbose on
verbose set to on
adaptive[codex:adaptive-ai-orchestrator]> set verify python3 -m unittest
verify set to python3 -m unittest
adaptive[codex:adaptive-ai-orchestrator]> compose
Enter request. Finish with a line containing only '.'
> Run the unit tests.
> Fix any failures and explain their cause.
> .
{ ... existing cli.main JSON output ... }
adaptive[codex:adaptive-ai-orchestrator]> recent 2
#10 codex completed verify=passed duration=14.2s — Run the unit tests. Fix any failures and explain their cause.
#9 claude-code completed verify=skipped duration=8.1s — Review the implementation
adaptive[codex:adaptive-ai-orchestrator]> history
claude-code: ... legacy execution/verification metrics ...
codex: ... legacy execution/verification metrics ...
adaptive[codex:adaptive-ai-orchestrator]> usage
Codex: ... current local plan usage when available ...
Claude Code: ... subscription and logged project-cost summary ...
adaptive[codex:adaptive-ai-orchestrator]> exit
```

The shell keeps session state only for the lifetime of the process. The prompt and `status` command show the active workspace and agent; `cd` aliases `workspace`, and `q` aliases `quit`. `task <request>` is the shortest execution path: it sends the rest of the line as both `--description` and `--objective`. `compose` does the same for a multiline request, ending input with a line containing only `.`. Use `run` when description and objective or other CLI flags need to differ.

`set` stores frequently repeated options for the current session. `verbose` and `no_escalation` accept `on` or `off`, `time_limit` accepts positive seconds or `off`, and `verify` accepts command text or `off`. `settings` shows the active values:

```text
set verbose on
set no_escalation off
set time_limit 600
set verify python3 -m unittest
settings
```

The defaults are translated back into normal CLI argv. A time limit applies only to `task`/`run`, because `run-plan` and `plan generate` do not expose that task-level flag; the other workflow defaults apply to all routed shell commands. Options then follow their existing argparse behavior: a later single-value option such as `--time-limit` wins, repeatable `--verify-command` values accumulate with the session default, and a session-level `no_escalation` must be turned off with `set no_escalation off` before a command because the CLI has no inverse flag.

`recent [count]` reads the existing workspace JSONL log and shows the last appended records first with agent, execution status, verification status, agent-process duration, and a compact task description. Append order is not a timestamp or durable lifecycle order; the current schema has neither. The command only reads and formats the legacy telemetry, mapping a missing verification object to `not-run`. `help run`, `help run_plan`, `help plan_generate`, and the corresponding plan/memory topics delegate to the existing argparse help, keeping shell help aligned with CLI flags.

Command names, `agent` values, workspace directories, and plan-file paths support tab completion. Invalid workspace paths are rejected without losing the current session state, command typos suggest a close match, and a blank line is a no-op rather than `cmd.Cmd`'s default behavior of repeating the previous command.

Most commands still only build an argv list and call the existing `adaptive_orchestrator.cli.main` dispatch, so they stay aligned with normal CLI flags and output conventions. Shell-native convenience commands include session views (`status`, `settings`) and read-only local-data views (`history`, `recent`, `usage`). `history` currently exposes legacy operational metrics, not objective task-quality or unbiased policy estimates; do not use its percentages to rank agents.

## Watching a long run

`run`, `run-plan`, and `plan generate` accept `--verbose`, which streams the running agent's stdout to stderr as it arrives instead of staying silent until the process exits:

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli run --agent codex --verbose \
  --description "..." --objective "..."
```

`run`/`run-plan` stdout still only carries the final JSON result, while successful `plan generate` keeps its existing plan summary. In every case `--verbose` output goes to stderr, so the command's normal stdout contract is unaffected.

## Escalation

Single-agent-first stays the default. If the first agent's execution fails, its verification command fails or times out, or the router's own analysis flags high risk, uncertainty, or difficulty, `EngineeringWorkflow` escalates once to the next-best-scored capable agent and records both attempts (`execution.escalation` in the JSON output). It never escalates past an explicitly requested `--agent`. Tune or disable it with:

```bash
--no-escalation
--escalation-risk-threshold 3          # 0-5, default 3
--escalation-uncertainty-threshold 3   # 0-5, default 3
--escalation-difficulty-threshold 4    # 1-5, default 4 (floors at 1, so this stays higher than the others)
```

## Safety and privacy

This kernel launches coding agents that can modify the configured workspace. Run it only in repositories you trust and with a permission/sandbox mode appropriate to that repository. The default adapters do **not** enable CLI permission-bypass flags.

Execution records may contain task prompts, context, CLI output, and workspace paths. The JSONL logger applies best-effort masking for sensitive key names and common token formats; it is not a secret-scanning or data-loss-prevention system. Do not place credentials or private data in task content. Git diff capture is disabled by default and must be explicitly enabled with `--include-git-diff` in the CLI or `include_git_diff=True` in the Python API.

`workspace_modified_files` and `workspace_git_diff` describe the workspace after execution. They can include changes that existed before the agent ran; they are not an attribution mechanism.

## CLI compatibility

The adapters use Claude Code's non-interactive `--print` mode and Codex CLI's non-interactive `exec` mode. Their exact flags are CLI-version dependent; validate `claude --help` and `codex exec --help` after upgrading either CLI.

The current implementation was locally validated against Claude Code `2.1.211` and Codex CLI `0.144.5`.

## Current limits

- Routing is rule-based and its initial preference values are not learned from enough production evidence yet.
- Current `--agent auto` combines unvalidated capability/complexity/risk priors with selection-count shrinkage and deterministic argmax. Until the corrected L0 policy is implemented, do not treat new auto runs as unbiased skill evidence; use an explicit agent for ordinary work.
- Both adapters parse structured CLI output into normalized `ExecutionMetadata`: Claude Code's `--print --output-format json` (verified against `2.1.211`) and Codex CLI's `exec --json` (verified against `0.144.5`). Codex CLI does not expose a cost field the way Claude Code does, so `ExecutionMetadata.cost_usd` stays `None` for Codex executions — this reflects what the CLI actually reports, not a parsing gap.
- Cost limits cannot be reliably enforced for subscription-backed CLIs.
- The execution JSONL log records telemetry; engineering memory lives in a separate JSONL store and is only populated by explicit `memory record` calls.
- Log redaction is best-effort; it cannot guarantee removal of every secret embedded in free text or diffs.

## Next development increment

Implement Phase -1 of the adaptive-routing design: add stable execution/policy
identity, repair usage redaction and duration semantics, and label escalation
cohorts without changing the selection policy to an arbitrary new neutral. Then
distinguish task-quality evidence from constraint/process checks and record
interruption-safe lifecycle events. Only after those observations are
trustworthy should routing thresholds or learned policies be tuned. See the
[progress handoff](docs/adaptive-routing-progress.md) for the ordered checklist.
