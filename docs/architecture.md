# Kernel v0.1 architecture

## Core flow

```text
Task -> Task analysis -> Adaptive Router -> CLI Agent (capabilities + command builder) -> Process Runner -> CLI process
  \-> Git workspace snapshot (changed files + optional diff)                   \-> ExecutionRecord -> JSONL telemetry
                                                                                       \-> Escalation Policy -> second CLI Agent (only if warranted)
```

`Task` describes required capabilities rather than a model or job title. `Agent` is a CLI adapter plus capabilities and an execution policy. The Kernel coordinates one selected agent per execution. This preserves the **single-agent-first** policy and makes escalation a measurable, deliberate decision rather than a default.

## Escalation policy

This implements the flow already named in project-constitution.md 5: Single Agent First -> Task Difficulty Analysis -> Need Additional Intelligence? -> Multi-Agent Collaboration. After the first agent runs and is (optionally) verified, `EscalationPolicy.decide` inspects the execution status, verification status, and the router's own risk/uncertainty/difficulty analysis. It escalates to exactly one more agent only when there is a concrete reason: the execution failed, verification failed or timed out, or analyzed risk, uncertainty, or difficulty crossed a configured threshold. The difficulty threshold defaults higher (4 of 5) than risk/uncertainty (3 of 5) because the difficulty score floors at 1 (never 0); a low threshold would escalate on nearly every multi-capability task, which would violate the "minimum sufficient intelligence" goal. It never overrides an explicitly requested agent (`--agent claude-code` / `--agent codex`) — escalation only applies when the router was free to choose. The second agent is the router's next-best-scored candidate (or, for the deterministic capability-only selector, any other capable agent). Both attempts are logged as independent JSONL records so `ExecutionHistory` keeps accurate per-agent metrics; the primary record additionally nests the escalated attempt so a single execution tells the whole story.

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

1. Add structured CLI event adapters and normalize execution/cost metadata where available. **Done for Claude Code** (`ClaudeCodeAgent.parse_result`, verified against `2.1.211`'s `--output-format json`). **Pending for Codex**: `exec --json`'s successful-turn schema is unverified — the local Codex CLI account hit its usage cap mid-verification (30-day rolling window, resets ~2026-08-16), so only the error-turn shape (`thread.started`/`turn.started`/`error`/`turn.failed`) is confirmed. Revisit once the cap resets and a real successful run can be inspected.
2. Expand the current deterministic planner/executor/verifier loop with structured task plans and richer verification.
3. Expand the current task-analysis router with measured cost, richer risk signals, and sufficient observed telemetry.
4. Store architecture decisions and evaluation outcomes as engineering memory.
5. Tune escalation thresholds from observed telemetry instead of fixed defaults, and consider richer escalation strategies (e.g. majority vote across agents) once there is measured benefit.
