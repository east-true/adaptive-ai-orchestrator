# Paired Experiment Control Files

`phase2a-smoke-v1.json` is the preregistered four-task manifest for the first
agent-paired pipeline smoke. Its evaluated repository base is the earlier commit
`fe47cc1e36b2217cf5529e613a3b5dd1d21acf1e`; the manifest and evaluator sources
are intentionally committed later and are not part of an agent checkout.

Canonical evaluator sources live under `evaluator-sources/phase2a-smoke-v1/`.
The manifest does not execute these tracked copies. Before validation they are
materialized at the sibling path below with file mode `0444`:

```text
<repository-parent>/adaptive-ai-orchestrator-evaluators/phase2a-smoke-v1/
```

Manifest artifact hashes cover the protected copies, including their mode. The
four task evaluators were run against the pinned base before preregistration and
all failed for their intended missing behavior. This is the negative control;
passing requires an agent-produced change in its isolated checkout.

The smoke tasks are:

1. preserve `cost_limit_usd` through plan JSON paths;
2. add finalized/per-status replay counts;
3. add a non-mutating `paired plan` command;
4. report objective evaluator coverage without imputing missing quality.

No Claude Code or Codex execution is started merely by committing these control
files. The manifest passed `paired validate`, an agent-free eight-checkout
`paired dry-run`, and the explicitly approved eight-execution smoke on
2026-07-18. The observed result and evaluator-validity finding are recorded in
`results/phase2a-smoke-v1.md`; they are pipeline evidence, not an agent ranking.
