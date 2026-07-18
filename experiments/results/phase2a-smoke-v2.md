# Phase 2a Paired Smoke v2 Result

> executed: 2026-07-18 08:45:02Z–13:37:43Z (active runner elapsed 896.699 seconds; infrastructure pause excluded)
> initial controller revision: `d0a47ccfeb8f0f70c5e813945716af9b297f2554`
> resume/analysis controller revision: `de34b4cf8565662f5f7be0299a356e819de09051`
> evaluated base: `fe47cc1e36b2217cf5529e613a3b5dd1d21acf1e`
> environment: Claude Code 2.1.212 / `claude-opus-4-8`; Codex CLI 0.144.5 / `gpt-5.6-terra`, reasoning `none`

This was a contract and pipeline rehearsal, not a confirmatory agent comparison.
All eight preregistered attempts materialized. Seven agent processes completed
and passed their protected objective evaluators. One Claude process stopped on
a CLI session-quota infrastructure failure; its objective evaluator was
correctly skipped and its quality remains missing rather than being replaced
with zero.

## Observed paired outcomes

| task | Claude | Codex | pair status |
|---|---:|---:|---|
| `paired-evaluator-coverage` | pass | pass | complete |
| `replay-status-summary` | missing (infrastructure failure) | pass | one-sided failure |
| `paired-plan-command` | pass | pass | complete |
| `plan-cost-limit` | pass | pass | complete |

Among the three fully observed pairs, the preregistered binary 2×2 table is:

- Claude pass / Codex pass: 3
- Claude pass / Codex fail: 0
- Claude fail / Codex pass: 0
- Claude fail / Codex fail: 0
- descriptive paired risk difference: 0.0

The missing Claude quality is not a binary failure and is absent from the 2×2
table. `promotion_allowed` remains false. Three fully observed smoke pairs,
missing confirmatory intervals, and absent target-workload weights do not
support an agent ranking.

## Pause and resume audit

The initial runner finalized the first three attempts and paused immediately
after the one-sided infrastructure failure, before selecting a fourth attempt.
The failure row was retained under the preregistered exclusion rule; no task was
excluded. The controller then gained a fail-closed `paired resume` path which:

- requires the recorded selections to be the deterministic assignment prefix;
- requires every prior attempt to be finalized;
- verifies all workspace commit/tree/Git-isolation identities and the untouched
  suffix's clean fixture hashes;
- skips all materialized attempt IDs and spends only the remaining active
  wall-time budget.

Resume validation found the exact three-attempt prefix and ran only the five
remaining attempts. The final log has eight unique selections in the exact
preregistered order. The infrastructure failure remains visible in the final
reliability and coverage metrics.

## Pipeline and resource audit

- lifecycle events: 48 (`selection=8`, `start=8`, `terminal=8`,
  `evaluation=16`, `finalized=8`);
- reliability: 8/8 materialized, 7/8 completed, one infrastructure failure;
- objective evaluator coverage: 7/8 attempts (0.875) and 3/4 fully observed
  pairs (0.75);
- all seven observed objective results passed with their expected artifact
  hash unchanged before and after evaluation;
- all four protected evaluator artifacts remained mode `0444`; the protected
  control directory/event log remained mode `0700`/`0600`;
- event-derived analysis was byte-stable across two replays;
- summed agent-process duration: 894.516 seconds; summed evaluator duration:
  1.159 seconds; active runner elapsed: 896.699 seconds;
- observed Claude CLI cost, including the failed invocation: USD 5.75686325;
  Codex CLI cost remained unavailable, so total experiment cost is unknown;
- token metadata was observed for all eight attempts, but vendor-normalized
  token fields are not treated as directly comparable between agents.

The raw protected control state remains local outside Git. Its post-run hashes
were:

- `events.jsonl`: `ac2f4195c56c83e226b0d9595b6a9813cbf8a2efdbcaf03470963b100cd1dda6`
- `routing-state.json`: `d414b1de95c2cf239bd75636244b65986d466e472ac40185bf818f0d1657dbc1`
- controller-revision analysis JSON: `44ab208738f2301eedd7bca5ffadb69fa4ef04a46e61de4bde2bfc2b03c99f4f`

Raw execution logs are not copied into Git because they contain prompts, agent
output, session metadata, detailed usage records, and local workspace paths.

## Modified-file scope finding

All eight attempts reported modified files, making the preregistered v2
unexpected-file metric fully estimable. Seven attempts stayed within their
task-specific exact allowlists. Claude's `paired-evaluator-coverage` attempt
also modified `docs/paired-smoke-tooling.md`, which was outside that task's
allowlist. Its objective evaluator still passed because file scope is reported
as a secondary audit metric rather than substituted into objective quality.

The row is retained and the deviation is reported; it is not a preregistered
exclusion. The added documentation restated evaluator-coverage semantics that
already exist on the current main branch, so no change was mined from that
workspace.

## Implementation mining and follow-up gates

The seven completed workspace implementations and the failed workspace's
unevaluated diff were compared with current main. The four requested feature
deltas had already been independently integrated from the v1 smoke, so none of
the isolated experiment patches were copied into the repository.

The live v2 run did expose two controller-level gaps, both fixed and covered by
regression tests before resume:

1. projected missing attempts are no longer counted as materialized attempts;
2. a paused paired run can resume its untouched suffix without duplicating
   attempts, discarding a failure row, resetting workspaces, or exceeding the
   preregistered execution count.

Phase 2a has now exercised negative control, contract coverage, deterministic
planning, clean isolated preparation, protected evaluation, partial-log pause,
safe resume, complete replay, resource missingness, and modified-file scope.
The next implementation gate is a separate generalized schema and task/evaluator
construction workflow for the 60-task Phase 2b pilot. The v2 smoke result itself
must not be used for routing-policy promotion or an agent ranking.
