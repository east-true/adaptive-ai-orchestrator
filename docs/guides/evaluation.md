*Documentation › Guides › Evaluation tooling*

# Evaluation tooling

Preparing a paired comparison. Nothing here runs an agent unless you
explicitly authorize it.

> **Where the research record lives.** The evaluation protocol, research review,
> Phase 2b preregistration, candidate ledger, and work log referenced in this
> section are kept in a separate private repository, because they record
> screening verdicts about third-party public repositories. Nothing this
> repository claims depends on them: learned routing is disabled and no
> comparative agent run has been authorized.

## Prepare a paired smoke without running agents

The historical `paired-smoke-manifest-v1` contract pins four low-risk tasks,
both exact agent environments, one protected task-specific evaluator per task,
the Git base/fixtures, metrics, budget, and stop/exclusion rules before outcomes
exist. `paired-smoke-manifest-v2` additionally requires an assertion-by-assertion
evaluator/task wording map, an explicit completeness attestation for that
inventory, and an exact repository-relative modified-file allowlist per task.

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli paired plan \
  experiments/phase2a-smoke-v1.json \
  --workspace-root /protected/paired-workspaces
PYTHONPATH=src python3 -m adaptive_orchestrator.cli paired validate \
  experiments/phase2a-smoke-v1.json --source-repository .
PYTHONPATH=src python3 -m adaptive_orchestrator.cli paired dry-run \
  experiments/phase2a-smoke-v1.json --source-repository . \
  --workspace-root /protected/paired-workspaces
```

The plan command only reads the manifest. It returns deterministic assignments,
preflight contract coverage, and eight paths under the explicit `workspaces`
JSON field without reading or creating the workspace root. The later dry run
must produce the same paths.

The dry run invokes neither Claude Code nor Codex. It creates eight persistent,
independent shallow checkouts containing only the exact detached base commit,
checks their clean base and fixture hashes, and emits balanced seeded order plus
stable pair/execution/attempt IDs. They share neither Git refs nor a common Git
directory, and existing targets are never overwritten. See the
[paired-smoke tooling contract](../paired-smoke-tooling.md) before preparing a
real manifest.

The actual runner is a separate, explicit gate. It revalidates the manifest,
installed CLI versions, protected evaluators, and a fresh workspace/control
boundary before starting the eight attempts. It never reuses or overwrites a
dry-run checkout or an existing control log. If an infrastructure/evaluator
pause leaves a finalized prefix, `paired resume` validates that prefix and all
eight existing checkout identities, then runs only the untouched suffix under
the remaining active wall-time budget.

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli paired run \
  experiments/phase2a-smoke-v1.json --source-repository . \
  --workspace-root /protected/fresh-paired-run \
  --control-state-dir /protected/fresh-paired-control \
  --confirm-agent-execution

PYTHONPATH=src python3 -m adaptive_orchestrator.cli paired resume \
  experiments/phase2a-smoke-v1.json --source-repository . \
  --workspace-root /protected/fresh-paired-run \
  --control-state-dir /protected/fresh-paired-control \
  --confirm-agent-execution
```

Omitting `--confirm-agent-execution` starts no agent and fails closed. The first
preregistered Phase 2a smoke completed on 2026-07-18; see the
[pipeline result and validity audit](../../experiments/results/phase2a-smoke-v1.md).
The v2 contract rehearsal also completed with one retained infrastructure
failure; see the [v2 result, pause/resume, and scope audit](../../experiments/results/phase2a-smoke-v2.md).

---

[← All guides](operator-guide.md)
