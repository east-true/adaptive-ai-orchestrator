*Documentation › Guides › How it behaves*

# How it behaves

What the kernel decides on your behalf, and what it writes down.

## Why this shape

**Stack:** Python 3.10+, standard library, `unittest`, and JSON Lines logging. Claude Code and Codex are subprocess execution targets.

Python provides a small, portable process-control surface. The standard-library-only core keeps the kernel testable without provider credentials, network access, or framework lock-in. JSON Lines is append-only and easy to ingest later into a database, warehouse, or evaluation pipeline.

Starting with a web framework and provider SDKs would make an early API wrapper, but would bypass the existing subscription-authenticated CLI workflows. Putting subprocess logic in each agent would duplicate timeout/error rules. This kernel instead models capability requirements separately from CLI adapters and centralizes process control.

## Routing policy

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

## Escalation

Single-agent-first stays the default. If the first agent's execution fails, its verification command fails or times out, or the router's own analysis flags high risk, uncertainty, or difficulty, `EngineeringWorkflow` escalates once to the next-best-scored capable agent and records both attempts (`execution.escalation` in the JSON output). It never escalates past an explicitly requested `--agent`. Tune or disable it with:

```bash
--no-escalation
--escalation-risk-threshold 3          # 0-5, default 3
--escalation-uncertainty-threshold 3   # 0-5, default 3
--escalation-difficulty-threshold 4    # 1-5, default 4 (floors at 1, so this stays higher than the others)
```

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

**What replay rejects.** Sequence gaps, event-ID collisions, invalid
transitions, and malformed rows. Repeating an identical event ID is idempotent.
On the next local startup, a `started` attempt whose PID is no longer alive is
reconciled as abandoned and finalized; a live concurrent owner is left alone.

**How an interrupted subprocess is cleaned up.** Interrupting a run kills the
invocation's isolated POSIX process group, its per-invocation Windows Job
Object, or — on another non-POSIX runtime — the direct child, then reaps the
owned root before re-raising the interrupt. The Windows runner uses a launch
gate so the requested command cannot start before Job assignment. That does not
yet make the POSIX-classified persistence layers Windows-compatible.

**Why output collection is time-bounded.** A descendant that puts itself in its
own session keeps the inherited output pipes open and sits outside the group
being killed. Waiting for end-of-file would then extend the run for as long as
that process lives, and a task time limit would bound nothing. So the runner
stops collecting after a short grace period, keeps what it already received, and
appends a line to the captured stderr saying the output may be incomplete —
rather than truncating in silence.

Legacy execution JSONL is reported only for schema and record reproduction, and
explicitly never as counterfactual support.

---

[← All guides](operator-guide.md)
