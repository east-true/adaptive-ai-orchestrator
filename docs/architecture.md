# Kernel v0.1 architecture

## Core flow

```text
Task -> Task analysis -> Adaptive Router -> CLI Agent (capabilities + command builder) -> Process Runner -> CLI process
  \-> Git workspace snapshot (changed files + optional diff)                   \-> ExecutionRecord -> JSONL telemetry
                                                                                       \-> Escalation Policy -> second CLI Agent (only if warranted)
```

`Task` describes required capabilities rather than a model or job title. `Agent` is a CLI adapter plus capabilities and an execution policy. The Kernel coordinates one selected agent per execution. This preserves the **single-agent-first** policy and makes escalation a measurable, deliberate decision rather than a default.

## Structured plans and richer verification

`EngineeringWorkflow.run_plan(tasks)` runs an explicit, caller-supplied ordered list of `Task`s through the unchanged single-task `run()` pipeline, one at a time, stopping at the first non-succeeding step by default (`stop_on_failure`, overridable). There is deliberately no inference of steps from a single task's free-text description: a regex/heuristic decomposition of prose (e.g. numbered lists) risks misfiring on ordinary text ("the bug in section 2.1") that only looks structured — the same category of risk as guessing at an unverified CLI output schema instead of confirming it live (see evolution #1). Structure comes only from what the caller explicitly supplied (a JSON plan file via the `run-plan` CLI subcommand, or a list of `Task` objects programmatically).

`CommandVerifier` retains `command` and `additional_commands` for backward
compatibility. They now produce per-command `EvaluatorResult`s with role
`constraint`; their worst outcome is still projected to the legacy
`VerificationResult` used for workflow control. The built-in process terminal
observation has role `reliability`, while explicit `EvaluatorSpec`s can represent
`quality`, `safety`, or `resource` without substituting one role for another.

The repeatable `--quality-evaluator-command` is intentionally stricter than
`--verify-command`: it requires a directly referenced read-only artifact outside
the agent workspace. The spec version includes the command and initial artifact
hash, and evaluator results preserve expected/before/after hashes plus whether
integrity was verified. A missing, workspace-local, writable, or changed
artifact invalidates the quality result. Legacy log rows are still readable,
but their untyped verification is projected only to `constraint`, never quality.

## Planner

Phase 2 of `project-constitution.md` names the control loop as `Planner -> Executor -> Verifier`. The `plan generate` CLI subcommand is that planner: it asks an existing CLI agent (Claude Code or Codex, through the same adapter layer used for `run`) to write a plan file, then validates it by running the unchanged `EngineeringWorkflow.run` pipeline with a `CommandVerifier` self-check that calls `plan validate`.

That choice keeps the system inside the existing CLI-agent boundary. It does not add a new LLM SDK/API dependency, and it does not touch Phase 6 (`API/SDK Integration`) at all. The planner simply reuses the same routing, execution, verification, and escalation machinery that already exists for normal tasks, but points it at a planning task instead of an implementation task.

## Engineering memory

`EngineeringMemoryStore` keeps an append-only JSONL memory log separate from execution telemetry. It stores caller-authored `MemoryEntry`s for architecture decisions, design reasoning, trade-offs, failure history, project context, and code evolution, and it can query them by type, tag, or keyword. That separation matters: execution telemetry answers "what happened," while engineering memory answers "what should we remember," and both stay explicit rather than inferred from free text or agent output.

## Escalation policy

This implements the flow already named in project-constitution.md 5: Single Agent First -> Task Difficulty Analysis -> Need Additional Intelligence? -> Multi-Agent Collaboration. After the first agent runs and is (optionally) verified, `EscalationPolicy.decide` inspects the execution status, verification status, and the router's own risk/uncertainty/difficulty analysis. It escalates to exactly one more agent when the execution failed, verification failed or timed out, **or** analyzed risk, uncertainty, or difficulty crossed a configured threshold; the latter path can therefore escalate after a successful first attempt. The difficulty threshold defaults higher (4 of 5) than risk/uncertainty (3 of 5) because the difficulty score floors at 1 (never 0); a low threshold would escalate on nearly every multi-capability task, which would violate the "minimum sufficient intelligence" goal. It never overrides an explicitly requested agent (`--agent claude-code` / `--agent codex`) — escalation only applies when the router was free to choose. The second agent is the router's next-best-scored candidate (or, for the deterministic capability-only selector, any other capable agent).

Both attempts are logged as separate JSONL records and the primary record also
nests the escalated attempt. Phase -1 now gives them the same `execution_id`,
distinct `attempt_id`s, a `parent_attempt_id` edge, explicit
`selection_mode`/`cohort`, the complete reason list, and derived
`trigger_classes` (`outcome`, `task_analysis`). Legacy rows receive the same
labels only where their old routing decision or nested escalation reasons make
the derivation possible. These labels make the cohorts inspectable; they do not
make them statistically independent, and the second attempt may still see the
first attempt's workspace changes.

## Router: measured cost, richer risk, and telemetry confidence

`ExecutionHistory.metrics_for` now aggregates `average_cost_usd` from each logged execution's `metadata.cost_usd` when present (today, only Claude Code populates it — see `ClaudeCodeAgent.parse_result`). `AdaptiveRouter.select` applies a fixed penalty to a candidate only when the task sets `cost_limit_usd` *and* that candidate's historical average exceeds it; with no stated budget or no cost samples, cost has no effect on scoring — there's nothing to compare against, so it stays neutral rather than guessed at. This activates `Task.cost_limit_usd`, which previously existed in `domain.py` but was read nowhere.

The interactive shell's `usage` command deliberately reports two structurally different sources. Codex supplies rate-limit percentages through its own undocumented local session-log format, which may change on a Codex CLI upgrade; Claude Code supplies only its subscription tier locally, so the command pairs that account-wide label with cost samples from this project's `ExecutionHistory` and explicitly says that no live quota percentage is available. This asymmetry matches the existing `ExecutionMetadata.cost_usd` behavior where Codex exposes no cost field. The current CLI also has no `cost_limit_usd` input, so the router's historical cost penalty is reachable only through the Python `Task` API and would be asymmetric while Codex cost remains unknown.

`TaskAnalyzer`'s risk keyword list grew to include explicitly irreversible operations (force push, `rm -rf`, drop table, overwrite, no backup, and Korean equivalents) — an extension of the existing text-matching heuristic, not a new inference technique.

Historical evidence (success rate, verification pass rate) is now confidence-weighted by sample count (`_MIN_SAMPLES_FOR_FULL_CONFIDENCE = 5` in `routing.py`): below that many logged executions, evidence blends toward the same neutral prior a candidate with zero history gets, rather than fully trusting a single run. This fixed a real bug in the process — the old `metrics.success_rate or 0.5` treated a genuine 0.0 success rate (an agent that has always failed) as indistinguishable from "no history yet," since `0.0` is falsy in Python.

That fix did not make the resulting router unbiased. With deterministic argmax,
selection-count confidence can pull a good but less-exposed candidate down to
the neutral value and then keep it unselected. Capability affinity also weights
text-inferred and caller-required capabilities equally even though difficulty
does not. These are current limitations to address together in the corrected L0
policy; the legacy metrics are operational diagnostics, not objective quality.

Phase -1 freezes further contamination without replacing that policy with an
arbitrary neutral one: new workflow records are marked `policy_version =
legacy-biased` and `routing_evidence_eligible = false`, and the router excludes
only rows explicitly carrying that false flag. Existing legacy rows remain in
the current score until corrected L0 and its migration boundary are defined in
Phase 1.

**Difficulty/risk no longer conflate thoroughness with complexity.** A real dogfooding run (using the orchestrator to delegate its own engineering-memory feature to Codex — see `memory.py`) surfaced this live: a long, well-specified, six-requirement task description hit the maximum difficulty (5) purely from text length and the number of keyword categories it happened to touch, and risk hit 4 because the test-writing instructions used the word "credential" as an example — not because the task was actually broad or security-sensitive. `difficulty` now weights `task.required_capabilities` (a deliberate, caller-declared signal) far more than merely-inferred-from-text capabilities (full weight vs. a third); the risk-keyword match now needs multiple distinct hits to reach its full contribution instead of any single incidental mention; and the SECURITY_REVIEW risk contribution only fires when that capability was explicitly required, not merely inferred from a stray word. Re-running the exact scenario that surfaced this: difficulty dropped from 5 to 3 and risk from 4 to 2 — below the default escalation thresholds, where before this would have triggered a wasteful second full agent run in `--agent auto` mode.

## CLI ergonomics and progress visibility

Found via dogfooding (using the orchestrator to delegate its own feature work to Codex — see "Engineering memory" above): a ~500-word task description was painful to pass through `--description "..."` on an actual shell command line, and a multi-minute run gave no sign of life until it exited, forcing external polling of `ps aux`/`git status` just to tell it was still working.

`run`'s `--description`/`--objective` each now accept an alternative `--description-file`/`--objective-file` (mutually exclusive with the inline form, enforced via `parser.error`), reading UTF-8 text from a file instead of surviving shell quoting.

`--verbose` (available on `run`, `run-plan`, and `plan generate`) streams the running agent's stdout to stderr line-by-line as it arrives, prefixed with the command and requested agent, while stdout still only carries the final result. For `run`/`run-plan` that result is JSON; successful `plan generate` instead prints its existing plan summary. This is purely additive: `SubprocessRunner` now takes an optional `on_output_line` callback and reads stdout/stderr concurrently via two threads instead of blocking on `subprocess.run`, but when no callback is given (the default), behavior is unchanged. It only echoes raw lines — it does not attempt to parse or pretty-print an agent's structured output, since that already happens after the process exits via `Agent.parse_result`.

The interactive shell in `adaptive_orchestrator.shell` remains deliberately thinner than the CLI itself. It stores session-only workspace, agent, and repeated workflow defaults; `task`/`compose` and the routed commands translate those values back into argv and call `cli.main` directly. Detailed help delegates to the same argparse definitions. Shell-native behavior is limited to input/session ergonomics and read-only local views (`history`, `recent`, `usage`); execution, planning, verification, escalation, JSON output, and parser validation remain owned by the existing CLI and core layers.

## Deliberate boundaries

- **Domain:** no SDK, filesystem, or subprocess dependency.
- **Agent:** owns prompt construction, CLI syntax, and required-capability validation.
- **Adaptive Router:** infers task signals, scores capable agents using configurable policy and local history, and emits an explainable decision.
- **Process runner:** runs argument vectors without a shell, handles timeouts, normalizes output/state, and can optionally stream stdout as it arrives without changing what it returns.
- **Git snapshot:** best-effort collection of workspace state after execution. It does not attribute changes to an agent.
- **Telemetry:** records task, selected agent, command, agent-process duration, result, errors, workspace files, and an opt-in diff. Final records now have stable execution/attempt identity, UTC occurrence time, policy/config identity, cohort, evidence eligibility, evaluator-level typed results, and role-separated observation projections. It still lacks started/terminal lifecycle events and end-to-end workflow duration, so interrupted execution reconciliation is not yet durable.

## Security posture of local tools

The Process Runner uses argument vectors (`shell=False`). Claude defaults to `acceptEdits`; Codex defaults to `workspace-write`. Neither adapter adds a dangerous permission-bypass option. The JSONL logger masks common sensitive keys and token patterns, but is not a DLP boundary; Git diff collection is opt-in. Numeric usage-count fields such as `input_tokens` now use a narrow allowlist so resource telemetry survives while string values under token-named keys and literal credentials remain redacted. v0.1 is a local-development runtime, not a sandbox or multi-tenant security boundary.

## Evolution path

1. Add structured CLI event adapters and normalize execution/cost metadata where available. **Done**: `ClaudeCodeAgent.parse_result` (verified against `2.1.211`'s `--output-format json`) and `CodexAgent.parse_result` (verified against `0.144.5`'s `exec --json`: `thread.started`/`item.completed` with `item.type == "agent_message"`/`turn.completed` with token `usage`/`error`+`turn.failed` on failure). Codex exposes no cost field, so `ExecutionMetadata.cost_usd` is `None` for Codex — an honest gap in what the CLI reports, not a parsing shortfall.
2. Expand the current deterministic planner/executor/verifier loop with structured task plans and richer verification. **Done**: `EngineeringWorkflow.run_plan` (explicit ordered `Task` list, see "Structured plans and richer verification" above) and `CommandVerifier.additional_commands` (multi-command, worst-of aggregation).
3. Expand the current task-analysis router with measured cost and richer risk signals. **Partially done**: the fields and heuristics exist, but objective-quality evidence, comparable cost, unbiased exposure, and sufficient telemetry do not. See "Router: measured cost, richer risk, and telemetry confidence" above and [Adaptive Routing v2](adaptive-routing-v2.md).
4. Store architecture decisions and evaluation outcomes as engineering memory. **Done**: `EngineeringMemoryStore` (explicit `MemoryEntry` records in `.orchestrator/memory.jsonl`, queryable by type/tag/keyword, and populated only by the `memory` CLI subcommands).
5. Tune escalation thresholds from observed telemetry instead of fixed defaults, and consider richer escalation strategies (e.g. majority vote across agents) once there is measured benefit.
