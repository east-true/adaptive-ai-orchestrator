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

## Prepare the Phase 2b pilot without authorizing it

`phase2b` is separate from the historical four-task parser. Its validator
requires exactly 60 tasks, Korean/English/mixed quotas of 20 each, five category
quotas of 12 each, disjoint task/evaluator/validity construction roles, complete
acceptance-criterion mappings, control evidence, exact repository and evaluator
hashes, and a non-promotional analysis contract.

Planning is a pure projection. Validation reads every pinned source and
protected input. The dry run then creates 120 persistent, independent checkouts
without starting Claude Code or Codex and writes a new evidence record outside
all source, evaluator, and agent workspace roots:

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli phase2b plan \
  /protected/phase2b-manifest.json \
  --workspace-root /protected/phase2b-workspaces

PYTHONPATH=src python3 -m adaptive_orchestrator.cli phase2b validate \
  /protected/phase2b-manifest.json \
  --repository-root repo-id=/sources/repo \
  --evaluator-root /protected/phase2b-evaluators \
  --instruction-inventory /protected/instruction-inventory.json

PYTHONPATH=src python3 -m adaptive_orchestrator.cli phase2b dry-run \
  /protected/phase2b-manifest.json \
  --repository-root repo-id=/sources/repo \
  --evaluator-root /protected/phase2b-evaluators \
  --instruction-inventory /protected/instruction-inventory.json \
  --workspace-root /protected/phase2b-workspaces \
  --output /protected/phase2b-dry-run.json
```

Repeat `--repository-root ID=PATH` once for every manifest repository. The
source roots must be clean exact Git tops; evaluator material must be read-only
and outside them. The instruction inventory uses the strict
`phase2b-global-instruction-inventory-v1` contract. It either records a
completed semantic-equivalence review or binds the two empty effective-
instruction hashes and the exact per-attempt home-isolation environment.

For `isolated-empty-agent-homes`, the runner creates one previously absent
home below the protected control directory for each attempt. Only the agent
invocation receives child-local `HOME`, `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, and
XDG paths pointing into that empty directory; the evaluator runs with the
operator environment. A pre-existing home, symlinked parent, malformed
inventory, or process runner that cannot apply a child-only environment fails
closed before that agent process starts. The isolated home may contain CLI
state after the invocation and is retained as run evidence.

The manifest and dry run never authorize agent execution. A later operator must
commit the byte-exact manifest and create a separate JSON authorization with
this exact shape:

```json
{
  "schema_version": "phase2b-pilot-run-authorization-v1",
  "experiment_id": "<manifest experiment_id>",
  "manifest_sha256": "<64 lowercase hex>",
  "manifest_commit": "<40 or 64 lowercase hex commit>",
  "agent_free_dry_run_sha256": "<64 lowercase hex>",
  "maximum_executions": 120,
  "agent_execution_authorized": true,
  "approved_by_role_id": "<declared run_operator_role_id>",
  "approval_basis": "<explicit approval basis>",
  "approved_at": "<ISO-8601 timestamp with UTC offset>"
}
```

Even that file is insufficient without `--confirm-agent-execution`. `run` and
`resume` revalidate the commit, dry-run bytes, evaluator modes and hashes,
source cleanliness, CLI versions, instruction inventory, all 120 checkout
identities, and the untouched suffix. `resume` accepts only a finalized prefix.
The resulting analysis estimates variance, discordance, coverage, and
missingness; it cannot promote or rank a policy.

This repository does not ship a completed Phase 2b manifest or authorization,
so the commands above document the implemented gate rather than announce a run.

---

[← All guides](operator-guide.md)
