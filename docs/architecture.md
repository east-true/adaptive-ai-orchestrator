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

`CommandVerifier` similarly gained `additional_commands: Sequence[Sequence[str]]` alongside its original single `command` field (fully backward compatible — existing single-command callers are unaffected). Every configured command runs regardless of the others' outcome, since they are typically independent checks (lint, typecheck, test); the aggregate `VerificationResult.status` is the worst of the individual outcomes, with per-command output concatenated under a `$ <command>` header.

## Engineering memory

`EngineeringMemoryStore` keeps an append-only JSONL memory log separate from execution telemetry. It stores caller-authored `MemoryEntry`s for architecture decisions, design reasoning, trade-offs, failure history, project context, and code evolution, and it can query them by type, tag, or keyword. That separation matters: execution telemetry answers "what happened," while engineering memory answers "what should we remember," and both stay explicit rather than inferred from free text or agent output.

## Escalation policy

This implements the flow already named in project-constitution.md 5: Single Agent First -> Task Difficulty Analysis -> Need Additional Intelligence? -> Multi-Agent Collaboration. After the first agent runs and is (optionally) verified, `EscalationPolicy.decide` inspects the execution status, verification status, and the router's own risk/uncertainty/difficulty analysis. It escalates to exactly one more agent only when there is a concrete reason: the execution failed, verification failed or timed out, or analyzed risk, uncertainty, or difficulty crossed a configured threshold. The difficulty threshold defaults higher (4 of 5) than risk/uncertainty (3 of 5) because the difficulty score floors at 1 (never 0); a low threshold would escalate on nearly every multi-capability task, which would violate the "minimum sufficient intelligence" goal. It never overrides an explicitly requested agent (`--agent claude-code` / `--agent codex`) — escalation only applies when the router was free to choose. The second agent is the router's next-best-scored candidate (or, for the deterministic capability-only selector, any other capable agent). Both attempts are logged as independent JSONL records so `ExecutionHistory` keeps accurate per-agent metrics; the primary record additionally nests the escalated attempt so a single execution tells the whole story.

## Router: measured cost, richer risk, and telemetry confidence

`ExecutionHistory.metrics_for` now aggregates `average_cost_usd` from each logged execution's `metadata.cost_usd` when present (today, only Claude Code populates it — see `ClaudeCodeAgent.parse_result`). `AdaptiveRouter.select` applies a fixed penalty to a candidate only when the task sets `cost_limit_usd` *and* that candidate's historical average exceeds it; with no stated budget or no cost samples, cost has no effect on scoring — there's nothing to compare against, so it stays neutral rather than guessed at. This activates `Task.cost_limit_usd`, which previously existed in `domain.py` but was read nowhere.

`TaskAnalyzer`'s risk keyword list grew to include explicitly irreversible operations (force push, `rm -rf`, drop table, overwrite, no backup, and Korean equivalents) — an extension of the existing text-matching heuristic, not a new inference technique.

Historical evidence (success rate, verification pass rate) is now confidence-weighted by sample count (`_MIN_SAMPLES_FOR_FULL_CONFIDENCE = 5` in `routing.py`): below that many logged executions, evidence blends toward the same neutral prior a candidate with zero history gets, rather than fully trusting a single run. This fixed a real bug in the process — the old `metrics.success_rate or 0.5` treated a genuine 0.0 success rate (an agent that has always failed) as indistinguishable from "no history yet," since `0.0` is falsy in Python.

**Difficulty/risk no longer conflate thoroughness with complexity.** A real dogfooding run (using the orchestrator to delegate its own engineering-memory feature to Codex — see `memory.py`) surfaced this live: a long, well-specified, six-requirement task description hit the maximum difficulty (5) purely from text length and the number of keyword categories it happened to touch, and risk hit 4 because the test-writing instructions used the word "credential" as an example — not because the task was actually broad or security-sensitive. `difficulty` now weights `task.required_capabilities` (a deliberate, caller-declared signal) far more than merely-inferred-from-text capabilities (full weight vs. a third); the risk-keyword match now needs multiple distinct hits to reach its full contribution instead of any single incidental mention; and the SECURITY_REVIEW risk contribution only fires when that capability was explicitly required, not merely inferred from a stray word. Re-running the exact scenario that surfaced this: difficulty dropped from 5 to 3 and risk from 4 to 2 — below the default escalation thresholds, where before this would have triggered a wasteful second full agent run in `--agent auto` mode.

## Deliberate boundaries

- **Domain:** no SDK, filesystem, or subprocess dependency.
- **Agent:** owns prompt construction, CLI syntax, and required-capability validation.
- **Adaptive Router:** infers task signals, scores capable agents using configurable policy and local history, and emits an explainable decision.
- **Process runner:** runs argument vectors without a shell, handles timeouts, and normalizes output/state.
- **Git snapshot:** best-effort collection of workspace state after execution. It does not attribute changes to an agent.
- **Telemetry:** records task, selected agent, command, timing, result, errors, workspace files, and an opt-in diff for later evaluation and routing.

## Security posture of local tools

The Process Runner uses argument vectors (`shell=False`). Claude defaults to `acceptEdits`; Codex defaults to `workspace-write`. Neither adapter adds a dangerous permission-bypass option. The JSONL logger masks common sensitive keys and token patterns, but is not a DLP boundary; Git diff collection is opt-in. v0.1 is a local-development runtime, not a sandbox or multi-tenant security boundary.

## Evolution path

1. Add structured CLI event adapters and normalize execution/cost metadata where available. **Done**: `ClaudeCodeAgent.parse_result` (verified against `2.1.211`'s `--output-format json`) and `CodexAgent.parse_result` (verified against `0.144.5`'s `exec --json`: `thread.started`/`item.completed` with `item.type == "agent_message"`/`turn.completed` with token `usage`/`error`+`turn.failed` on failure). Codex exposes no cost field, so `ExecutionMetadata.cost_usd` is `None` for Codex — an honest gap in what the CLI reports, not a parsing shortfall.
2. Expand the current deterministic planner/executor/verifier loop with structured task plans and richer verification. **Done**: `EngineeringWorkflow.run_plan` (explicit ordered `Task` list, see "Structured plans and richer verification" above) and `CommandVerifier.additional_commands` (multi-command, worst-of aggregation).
3. Expand the current task-analysis router with measured cost, richer risk signals, and sufficient observed telemetry. **Done**: see "Router: measured cost, richer risk, and telemetry confidence" above.
4. Store architecture decisions and evaluation outcomes as engineering memory. **Done**: `EngineeringMemoryStore` (explicit `MemoryEntry` records in `.orchestrator/memory.jsonl`, queryable by type/tag/keyword, and populated only by the `memory` CLI subcommands).
5. Tune escalation thresholds from observed telemetry instead of fixed defaults, and consider richer escalation strategies (e.g. majority vote across agents) once there is measured benefit.
