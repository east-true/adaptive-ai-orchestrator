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
  configuration.py # local project config loading, validation, initialization, and command detection
  control.py      # single-worker local queue, cancellation, and redacted job journal
  diagnostics.py  # `doctor` checks for config, agent login, and runtime prerequisites
  notifications.py # opt-in terminal and desktop completion notifications
  reporting.py    # execution lookup, summaries, Markdown reports, and retry task extraction
  tui.py          # stdlib curses dashboard and shell-free background task launcher
  web_ui.py       # loopback-only stdlib HTTP dashboard over the local queue
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
- [Phase 2a paired-smoke tooling](docs/paired-smoke-tooling.md)
- [Claude 독립 검토와 반영 판단](docs/routing-claude-review.md)
- [진행상황과 이어하기](docs/adaptive-routing-progress.md)

Phase -1 telemetry baseline, Phase 0 typed evaluator, Phase 1 lifecycle/replay와
corrected static L0, Phase 2a agent-free paired dry-run tooling까지 반영했다. 현재의
적은 legacy telemetry로 bandit이나 탐색을 활성화하지 않는다.

## Run the prototype

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.example
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Initialize a local project profile

Create `.orchestrator/config.json` to keep repeated routing, model, timeout,
verification, and escalation options with the workspace:

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli init --workspace .
PYTHONPATH=src python3 -m adaptive_orchestrator.cli doctor --workspace .
```

`init` never runs detected test commands. It only recognizes conservative signals
for npm, Cargo, Go, pytest, and unittest projects and writes the resulting command
strings into the profile. It refuses to replace an existing profile unless
`--force` is explicit. The whole `.orchestrator/` directory is gitignored because
it also contains local execution telemetry and may contain machine-specific model
preferences; copy or maintain a shared profile separately if the team wants one.

The generated shape is:

```json
{
  "version": 1,
  "agent": "auto",
  "models": {
    "claude": null,
    "codex": null,
    "codex_reasoning_effort": null
  },
  "execution": {
    "time_limit_seconds": null,
    "verbose": false,
    "include_git_diff": false
  },
  "verification": {
    "commands": ["python3 -m unittest discover -s tests -v"],
    "time_limit_seconds": null
  },
  "escalation": {
    "enabled": true,
    "risk_threshold": 3,
    "uncertainty_threshold": 3,
    "difficulty_threshold": 4
  },
  "notifications": {
    "terminal_bell": false,
    "desktop": false
  }
}
```

The precedence is built-in defaults, then the local project profile, then
explicit CLI options. Repeatable `--verify-command` options extend the configured
command list. Boolean profile values can be overridden in either direction with
`--verbose`/`--no-verbose`, `--include-git-diff`/`--no-include-git-diff`, and
`--escalation`/`--no-escalation`.

`doctor` validates the profile, checks the Python version, and asks installed
Claude Code and Codex CLIs for their local login status. Missing optional agents
are warnings; having no usable agent, selecting an unavailable agent, an invalid
profile, or an unsupported Python version is a failure.

Set `notifications.terminal_bell` or `notifications.desktop` to opt into local
completion notifications. Desktop notifications use `notify-send` when it is
installed and include only status, verification, agent, and execution ID — task
and result text are deliberately omitted.

## Inspect, report, and retry an execution

Terminal records can be addressed by execution ID, attempt ID, or a legacy
one-based `#number` shown by the interactive shell:

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli show <execution-id> --workspace .
PYTHONPATH=src python3 -m adaptive_orchestrator.cli report <execution-id> --workspace .
PYTHONPATH=src python3 -m adaptive_orchestrator.cli report <execution-id> \
  --workspace . --output reports/run.md
PYTHONPATH=src python3 -m adaptive_orchestrator.cli retry <execution-id> --workspace .
```

`show` prints a compact human-readable outcome. `report` emits Markdown and
omits the recorded Git diff unless `--include-diff` is explicit; it refuses to
replace an existing output unless `--force` is supplied. `retry` reconstructs
only the structured `Task` fields from the terminal record, not the old prompt
or agent output. It requests the original agent by default; use `--agent auto`
when that exact model variant is no longer configured.

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

That legacy policy remains the compatibility default and is still marked
`legacy-biased`. The corrected L0 makes no pre-evidence vendor skill claim: it
uses explicitly required capabilities only as eligibility and requires the
caller to name a baseline. Inferred capabilities remain versioned context.

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli run \
  --workspace . --agent auto \
  --routing-policy static --routing-baseline-agent codex \
  --routing-shadow --routing-seed 17 --environment-epoch local-v1 \
  --description "Review the change" --objective "Report whether it is correct"
```

`--routing-shadow` records always-Claude/Codex, corrected-static,
legacy-adaptive, history-free legacy profile, best-single, stratified
Beta/greedy, and seeded random-safe comparators without changing the active
selection. Only typed binary quality from `paired`/`prospective` cohorts enters
best-single or stratified estimates. Missing evidence remains unavailable, and
the random policy remains shadow-only; exploration is not implemented or
enabled.

To pin a model or Codex reasoning effort for a routed command, pass the corresponding adapter options. They are accepted by `run`, `run-plan`, and `plan generate`:

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli run \
  --workspace . --agent codex:gpt-5.5:high \
  --codex-model gpt-5.5 --codex-reasoning-effort high \
  --claude-model opus \
  --description "Run the unit tests" --objective "Confirm the suite passes"
```

Configured variants receive derived registry IDs (`claude-code:<model>` and `codex:<model>:<reasoning-effort>`; omitted parts are left out). Use that derived ID with `--agent` to request a specific variant, or leave `--agent auto` to route between the configured variants. Execution logs retain both the exact variant ID and its stable vendor base ID. The compatibility legacy router still reads exact-ID operational metrics. Phase 1 objective-quality shadows instead use explicit exact-agent → base-agent backoff within one environment epoch and never treat a static prior as a measured sample.

Historical success/verification rates are confidence-weighted by sample count — a handful of logged runs pulls a candidate's score toward the same neutral baseline a brand-new agent gets, rather than being fully trusted. Set `Task.cost_limit_usd` and a candidate whose logged average cost (currently tracked for Claude Code only) exceeds it is penalized; leave it unset and cost has no effect on routing.

`--verify-command` is repeatable — every configured check runs and the worst
outcome wins. These commands are conservatively recorded as `constraint`
evaluators, never as task-quality evidence:

```bash
--verify-command "ruff check ." --verify-command "python3 -m unittest discover -s tests -v"
```

Use `--quality-evaluator-command` only for a task-specific objective evaluator.
It must directly reference at least one read-only artifact outside the agent
workspace. The artifact content is hashed before agent execution and before and
after evaluation; a mismatch invalidates the result. Both flags are repeatable.

```bash
--quality-evaluator-command "python3 /opt/orchestrator-evaluators/login-acceptance.py ." \
--quality-evaluator-artifact /opt/orchestrator-evaluators/login-acceptance.py
```

For testing tasks, that protected artifact should implement a held-out test,
mutation check, or hidden buggy implementation rather than accepting a test the
agent just wrote as proof of its own quality. `VerificationResult` remains the
backward-compatible aggregate used to control workflow success; typed
`evaluations` and `evaluation_projection` carry the evidence semantics.

## Lifecycle events and replay

CLI workflows fsync append-only `selection_made`, `execution_started`,
`execution_terminal`/`execution_reconciled`, per-evaluator
`evaluation_completed`, and `outcome_finalized` events. Selection events record
the policy/config/context/environment versions, every eligible candidate's
deterministic propensity, selected propensity, and shadow decisions before the
agent subprocess starts.

The event source and disposable `routing-state.json` projection default to an
XDG user-state directory keyed by the resolved workspace, outside the
agent-writeable repository. Override it with `--control-state-dir` when the
runtime has a different protected writable location. The directory must remain
outside `--workspace`.

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli replay --workspace .
PYTHONPATH=src python3 -m adaptive_orchestrator.cli replay --workspace . --rebuild-state
PYTHONPATH=src python3 -m adaptive_orchestrator.cli replay --workspace . --reconcile-incomplete
```

Replay rejects sequence gaps, event-ID collisions, invalid transitions, and
malformed rows. Duplicate identical event IDs are idempotent. On the next local
startup, a `started` attempt whose PID is no longer alive is reconciled as
abandoned and finalized; a live concurrent owner is left alone. Interrupting a
subprocess kills and reaps it before re-raising the interrupt. Legacy execution
JSONL is reported only for schema/record reproduction and explicitly never as
counterfactual support.

## Prepare a paired smoke without running agents

The `paired-smoke-manifest-v1` contract pins four low-risk tasks, both exact
agent environments, one protected task-specific evaluator per task, the Git
base/fixtures, metrics, budget, and stop/exclusion rules before outcomes exist.

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli paired validate \
  experiments/phase2a-smoke-v1.json --source-repository .
PYTHONPATH=src python3 -m adaptive_orchestrator.cli paired dry-run \
  experiments/phase2a-smoke-v1.json --source-repository . \
  --workspace-root /protected/paired-workspaces
```

The dry run invokes neither Claude Code nor Codex. It creates eight persistent,
independent shallow checkouts containing only the exact detached base commit,
checks their clean base and fixture hashes, and emits balanced seeded order plus
stable pair/execution/attempt IDs. They share neither Git refs nor a common Git
directory, and existing targets are never overwritten. See the
[paired-smoke tooling contract](docs/paired-smoke-tooling.md) before preparing a
real manifest.

The actual runner is a separate, explicit gate. It revalidates the manifest,
installed CLI versions, protected evaluators, and a fresh workspace/control
boundary before starting the eight attempts. It never reuses or overwrites a
dry-run checkout or an existing control log.

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli paired run \
  experiments/phase2a-smoke-v1.json --source-repository . \
  --workspace-root /protected/fresh-paired-run \
  --control-state-dir /protected/fresh-paired-control \
  --confirm-agent-execution
```

Omitting `--confirm-agent-execution` starts no agent and fails closed. The
preregistered Phase 2a smoke has not been executed yet.

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

`recent [count]` reads the compatibility workspace execution JSONL and shows the last appended final records first with agent, execution status, verification status, agent-process duration, and a compact task description. It does not read or summarize the protected lifecycle source; use `replay` for lifecycle validation. `help run`, `help run_plan`, `help plan_generate`, and the corresponding plan/memory topics delegate to the existing argparse help, keeping shell help aligned with CLI flags.

Command names, `agent` values, workspace directories, and plan-file paths support tab completion. Invalid workspace paths are rejected without losing the current session state, command typos suggest a close match, and a blank line is a no-op rather than `cmd.Cmd`'s default behavior of repeating the previous command.

Most commands still only build an argv list and call the existing `adaptive_orchestrator.cli.main` dispatch, so they stay aligned with normal CLI flags and output conventions. Shell-native convenience commands include session views (`status`, `settings`) and read-only local-data views (`history`, `recent`, `usage`). `history` currently exposes legacy operational metrics, not objective task-quality or unbiased policy estimates; do not use its percentages to rank agents.

## Full-screen terminal UI

For a dashboard-oriented local workflow, start the stdlib `curses` TUI:

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.tui --workspace .
```

It combines terminal records with the protected lifecycle event projection,
keeps escalated attempts together, and can show `selected`, `started`,
`terminal`, `evaluated`, or `finalized` progress before the terminal JSONL row
exists. Pass the same `--control-state-dir` used by routed CLI commands when a
non-default protected state directory is configured. Press `n` to compose a short task;
the TUI launches the normal `cli run` path as a shell-free child process and
shows its combined live output. Only one task is admitted at a time. `c` sends
SIGTERM to the dedicated child process group, preventing a cancelled UI child
from leaving its coding-agent subprocess behind. `r` refreshes terminal records,
arrow keys or `j`/`k` move through them, and `q` exits only when no task is
running.

The TUI is intentionally a client of existing CLI and telemetry contracts. It
does not duplicate routing, verification, escalation, configuration, or report
logic.

## Local Web UI and background queue

Start the loopback-only local dashboard and its single-worker queue with:

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.web_ui \
  --workspace . --host 127.0.0.1 --port 8765
```

The workspace is fixed when the server starts; HTTP clients cannot choose an
arbitrary filesystem path. The server refuses non-loopback bind addresses and
generates an ephemeral control token required by every `/api/` request. The
built-in page uses that token for same-origin requests, inserts job data with
`textContent`, and receives restrictive no-store, MIME-sniffing, framing, and
content-security headers.

Submitted jobs run sequentially through the normal CLI in dedicated process
groups. Cancellation targets only that group. Status snapshots and a bounded
output tail are appended to `.orchestrator/jobs.jsonl` with the existing
best-effort redaction. Because redaction can alter request text, queued or
running snapshots are marked `interrupted` after a daemon restart rather than
being executed from journal content. Users can deliberately submit them again
after inspection.

This is a local single-user control surface, not a multi-tenant or remote-access
server. Task text and CLI output can still contain private repository context;
the existing telemetry privacy warnings apply to the job journal as well.

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
- The compatibility default `--routing-policy legacy` still combines unvalidated capability/complexity/risk priors with selection-count shrinkage. Use explicit `--routing-policy static --routing-baseline-agent ...` for corrected L0; neither mode turns ordinary auto runs into unbiased skill evidence.
- Both adapters parse structured CLI output into normalized `ExecutionMetadata`: Claude Code's `--print --output-format json` (verified against `2.1.211`) and Codex CLI's `exec --json` (verified against `0.144.5`). Codex CLI does not expose a cost field the way Claude Code does, so `ExecutionMetadata.cost_usd` stays `None` for Codex executions — this reflects what the CLI actually reports, not a parsing gap.
- Cost limits cannot be reliably enforced for subscription-backed CLIs.
- The execution JSONL log records telemetry; engineering memory lives in a separate JSONL store and is only populated by explicit `memory record` calls.
- Log redaction is best-effort; it cannot guarantee removal of every secret embedded in free text or diffs.
- Evaluator path/mode and pre/post hash checks detect common artifact contamination, but v0.1 is not a hardened sandbox or immutable evaluation service.
- The protected control directory relies on the agent sandbox not granting writes outside the workspace; it is not a cryptographically signed remote ledger.
- Paired tooling validates and analyzes the pipeline but does not yet execute the 4-task/8-execution smoke or calculate confirmatory confidence intervals.

## Next development increment

Pre-register the actual four low-risk tasks and protected task-specific
evaluators, commit the manifest, and review `paired validate`/`paired dry-run`
output before adding the 8-execution runner. Do not enable prospective
exploration or promote a learned policy. See the
[progress handoff](docs/adaptive-routing-progress.md) for the ordered checklist.
