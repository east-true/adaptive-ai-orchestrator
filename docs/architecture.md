# Kernel v0.1 architecture

## Core flow

```text
Task -> Task analysis -> Adaptive Router -> CLI Agent (capabilities + command builder) -> Process Runner -> CLI process
  \-> Git workspace snapshot (changed files + optional diff)                   \-> ExecutionRecord -> JSONL telemetry
```

`Task` describes required capabilities rather than a model or job title. `Agent` is a CLI adapter plus capabilities and an execution policy. The Kernel coordinates one selected agent per execution. This preserves the **single-agent-first** policy and makes any future escalation a measurable, deliberate decision.

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

1. Add structured CLI event adapters and normalize execution/cost metadata where available.
2. Expand the current deterministic planner/executor/verifier loop with structured task plans and richer verification.
3. Expand the current task-analysis router with measured cost, richer risk signals, and sufficient observed telemetry.
4. Store architecture decisions and evaluation outcomes as engineering memory.
5. Introduce multi-agent escalation policies only with a measured benefit.
