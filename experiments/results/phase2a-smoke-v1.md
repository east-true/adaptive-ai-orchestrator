# Phase 2a Paired Smoke v1 Result

> executed: 2026-07-18 07:36:52Z–07:52:28Z
> controller revision: `606b26c26dd1efc612e95f1a9acbd937be9b6eeb`
> evaluated base: `fe47cc1e36b2217cf5529e613a3b5dd1d21acf1e`
> environment: Claude Code 2.1.212 / `claude-opus-4-8`; Codex CLI 0.144.5 / `gpt-5.6-terra`, reasoning `none`

This was a pipeline smoke, not a confirmatory agent comparison. All eight agent
processes completed, all eight objective evaluations were observed, and all
protected evaluator hashes were unchanged before and after evaluation.

## Observed paired outcomes

| task | Claude | Codex | pair status |
|---|---:|---:|---|
| `paired-evaluator-coverage` | pass | pass | complete |
| `paired-plan-command` | fail | pass | complete |
| `plan-cost-limit` | pass | pass | complete |
| `replay-status-summary` | pass | pass | complete |

The preregistered binary 2×2 table is therefore:

- Claude pass / Codex pass: 3
- Claude pass / Codex fail: 0
- Claude fail / Codex pass: 1
- Claude fail / Codex fail: 0
- descriptive paired risk difference: -0.25

`promotion_allowed` remains false. Four smoke pairs, missing confirmatory
intervals, and absent target-workload weights do not support an agent ranking.

## Pipeline and resource audit

- lifecycle events: 48 (`selection=8`, `start=8`, `terminal=8`,
  `evaluation=16`, `finalized=8`);
- reliability: 8/8 completed;
- objective evaluator coverage: 8/8 attempts and 4/4 pairs (1.0);
- event-derived analysis was byte-stable across two replays;
- elapsed event window: 936.279 seconds;
- summed agent-process duration: 933.896 seconds;
- compatibility-log-derived Claude cost: USD 5.6999125; Codex cost is
  unavailable from its CLI, so this is not total experiment cost and the value
  is not promoted into the protected lifecycle analysis;
- each checkout modified only files inside its isolated repository; a numeric
  unexpected-file metric is not identifiable because the manifest did not pin
  a task-specific file allowlist.

The raw protected control state remains local outside Git. Its post-run hashes
were:

- `events.jsonl`: `dd3fb28c1822055ccfeee747246e8d1c6e921ae69cddd33f45c9e1adb19a072b`
- `routing-state.json`: `7887668386d662539489d49717445010033bd86da0cbb7a4a7427adc33cce9ce`
- controller-revision analysis JSON: `d383f4232aff8c5fd2e9e3a9af7c4d3a9433361cd9d76a0f0113881bbc1f0fb7`

Raw compatibility logs are not copied into Git because they contain prompts,
agent output, session metadata, and detailed usage records.

## Evaluator-validity finding

The observed `paired-plan-command` Claude failure is retained exactly as
preregistered, but it is not clean evidence of functional inferiority. The task
required eight planned workspace paths in JSON without specifying a top-level
field name. Claude returned those paths under `planned_workspaces`; the held-out
evaluator required `workspaces` and raised `KeyError` before checking the paths.
Codex happened to choose the evaluator's undocumented key and passed.

This is an evaluator-contract mismatch discovered by the smoke. Do not rescore
or exclude the row post hoc. Before a pilot, every evaluator-required public
shape must be stated in the task contract or the evaluator must accept all
semantically equivalent declared shapes.

## Follow-up gates

1. Controller-level evaluator coverage, reliability, wall time, resource
   missingness, and modified-file observation are now implemented. The first
   smoke predates enriched finalized events, so its absent cost/token/runner
   elapsed/modified-file fields remain explicit missing values. Manifest v2 now
   requires task-specific exact modified-file allowlists.
2. Manifest v2 now requires a preflight contract-coverage map from every
   evaluator assertion to explicit task wording plus an assertion-inventory
   completeness attestation. The first v1 smoke remains unchanged.
3. Keep the smoke result as pipeline evidence only; do not use it for routing
   policy promotion or an agent ranking.
