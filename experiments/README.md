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
The historical v1 manifest is intentionally unchanged. Tooling also accepts the
v2 schema used by the second preregistered smoke; v2 requires evaluator
assertion/task wording coverage attestations and exact per-task modified-file
allowlists.

`phase2a-smoke-v2.json` is the completed contract rehearsal for the same four
maintenance tasks and evaluated base. It reuses the same protected evaluator
artifacts but makes all 23 evaluator assertions explicit in task wording,
including the formerly undocumented top-level `workspaces` field. Its exact
modified-file allowlists are based on the union observed across both v1 agent
workspaces, then preregistered rather than inferred during analysis. The v2
manifest passed parsing, contract coverage, exact-base negative controls,
`paired plan`, `paired validate`, an eight-checkout `paired dry-run`, and the
separately approved paired execution. The run materialized all eight attempts,
preserved one Claude CLI session-quota infrastructure failure as missing quality,
and resumed only the untouched five-attempt suffix after validating the first
three finalized attempts. The result and scope audit are in
`results/phase2a-smoke-v2.md`; this is pipeline evidence, not an agent ranking.

Phase 2b does not reuse the smoke schema as a 60-task manifest. Its generalized
construction and validity gates are defined in
`../docs/paired-pilot-preregistration.md`, and its machine-readable contract is
`schemas/paired-pilot-manifest-v1.schema.json`. No Phase 2b task set or 120-agent
execution is preregistered or authorized yet.

Phase 2b source screening is tracked separately in
`phase2b-candidate-ledger-v1.json`, validated structurally by
`schemas/paired-pilot-candidate-ledger-v1.schema.json`, and governed by
`../docs/paired-pilot-candidate-ledger.md`. A `screening` row is not an authored
task and does not count toward the 60-task quota.

`phase2b-license-priority-2026-07-24.json` is a derived, nonterminal work queue
over that frozen ledger and the earlier repository-level license probe. It uses
classifier and default-branch file-presence observations only to order work.
It cannot change a candidate decision or license inclusion value; pass or
terminal exclusion still requires artifacts from the exact pre-solution
revision.

`phase2b-license-file-classification-2026-07-24.json` completes the bounded
current-HEAD classification for the 66 file-only rows across 33 repositories.
It pins the observed full HEAD revision, exact public license blob, Git blob
SHA, decoded-content SHA-256, classifier result, and the three bounded
full-text reviews needed for `NOASSERTION`. The result advances 64 rows to
linked-solution metadata screening and routes two suspected-ineligible rows to
exact-revision confirmation. It remains nonterminal and does not mutate the
candidate ledger.

`phase2b-linked-solution-prefilter-2026-07-24.json` covers all 106
license-signal-positive rows: the 102 eligible-priority rows and four
suspected-ineligible exact-confirmation rows. It resolves direct closing PRs
from public issue HTML and pins the issue HTML, PR HTML, PR body, and `.diff`
hashes plus head revision, changed paths, test touch, and obvious multi-issue
signals, including complete PR commit-list overlap detection for stacked
supersets. The nonterminal routes advance 27 eligible rows and four license
confirmation rows, while deferring 18 scope-review and 57 no-test-touch rows.
No missing-test or broad-scope signal is an exclusion.

`phase2b-exact-revision-license-2026-07-24.json` resolves the exact Git lineage
and pinned-base license for the 31-row rank-5 queue. All 31 fetched heads,
commit sequences, single-parent first commits, and base-to-head changed-path
sets match their independently hashed GitHub evidence. The exact bases contain
21 MIT, six Apache-2.0, two GPL-3.0, one AGPL-3.0, and one repository with no
license/use basis. Twenty-seven rows pass the license gate, four terminate on
that gate, 26 advance to remaining-rule review, and the broad release row whose
current HEAD is noncommercial but whose candidate base is MIT returns to scope
review. Git-generated and GitHub-rendered diff bytes are not required to match
when their complete changed-path sets do.

`phase2b-rank5-ledger-application-2026-07-24.json` binds the immutable pre-rank-5
ledger hash, the exact-revision evidence hash, and the resulting ledger hash.
It records the 31 row mutations and preserves the invariant that rank 5 creates
no selected candidate. Its rank-5 output snapshot has 1,021 screening, 102
excluded, and seven selected-for-task-authoring rows.

`phase2b-rank6-instruction-parity-2026-07-24.json` inventories every
task-active `AGENTS.md`, `CLAUDE.md`, symlink, explicit adapter, import, and
path rule for the 25 exact trees newly advanced by rank 5. It records Git blob
and content hashes without copying the full public instruction bodies into the
tracked artifact. Five trees expose no project instructions, three use a
byte-equivalent `CLAUDE.md` symlink to `AGENTS.md`, and one has an explicit
semantic adapter; these nine pass. Sixteen rows have material one-sided active
guidance and terminate on `instruction-parity-mismatch`. No agent result was
observed.

`phase2b-rank6-ledger-application-2026-07-24.json` binds the pre-rank-6 ledger,
the instruction-parity evidence, and the resulting 25 mutations. Its rank-6
output snapshot has 1,005 screening, 118 excluded, and seven
selected-for-task-authoring rows. The next rank contains the nine new parity
passes plus the previously passed `doc_parser #288` row.

`phase2b-rank7-semantic-prefilter-2026-07-24.json` applies the cheapest
source-semantic gates to those ten rows before provisioning. Three localization
tasks terminate on `translation-only`, and the broad `ChunChuGwan #403`
optimization bundle terminates on `multiple-coupled-issues`. The other six
advance to agent-free controls. A bounded read-only Claude CLI cross-review was
used only as disagreement evidence; Codex resolved the three uncertain seams
against the exact source and tree, and no candidate-agent result was observed.

`phase2b-rank7-agent-free-reproduction-2026-07-24.json` binds exact-base
negative and exact-solution positive controls for all six survivors. Four fit
the small bucket and two AgentGuard rows fit the medium bucket. All six pass
within budget, keep their tracked trees clean, and route only to
selected-for-task-authoring. Solution tests used as copied controls remain
screening evidence, not final independently authored evaluators. In particular,
the final small-village validity reviewer must decide whether the offline roster
invariants fully cover the source's hosted three-client E2E sentence.

`phase2b-rank7-ledger-application-2026-07-24.json` binds the pre-rank-7 ledger,
both rank-7 evidence artifacts, the four terminal mutations, and the six new
construction-queue selections. Its historical output snapshot has 995
screening, 122 excluded, and 13 selected-for-task-authoring rows. No task,
final evaluator, manifest, routing observation, or candidate-agent execution
was created.

The scope-review continuation is an ordered evidence chain over the 18 rows
deferred by linked-solution breadth plus the MIT-at-base row returned by rank 5.
`phase2b-scope-review-source-semantic-2026-07-24.json` applies native-source,
boundedness, and external-side-effect gates before provisioning: seven rows
terminate and twelve advance. `phase2b-scope-review-ledger-application-2026-07-24.json`
binds those source decisions to the intermediate ledger snapshot.

`phase2b-scope-review-solution-segmentation-2026-07-24.json` pins the twelve
survivors' exact task-relevant base, solution, paths, and diff hashes.
`phase2b-scope-review-exact-revision-license-2026-07-24.json` records eleven
MIT and one Apache-2.0 exact-base passes. The subsequent
`phase2b-scope-review-instruction-parity-2026-07-24.json` produces four passes
and eight terminal one-sided-instruction failures, while
`phase2b-scope-review-exact-parity-ledger-application-2026-07-24.json` binds
that intermediate mutation boundary.

The four parity survivors then pass boundedness, isolation, protected-evaluator
feasibility, and hiding in
`phase2b-scope-review-survivor-semantic-2026-07-24.json`. Their byte-identical
base-negative and solution-positive controls are recorded in
`phase2b-scope-review-survivor-agent-free-reproduction-2026-07-24.json`.
These are screening controls, not final evaluator bodies. In particular, the
B-TING rollback structural assertion must become a behavioral failure-and-restore
test during final evaluator authoring. The final
`phase2b-scope-review-survivor-ledger-application-2026-07-24.json` moves only
those four rows to selected-for-task-authoring. That intermediate ledger had
976 screening, 137 excluded, and 17 selected-for-task-authoring rows; no
candidate agent was run.

`phase2b-swebench-license-terms-2026-07-24.json` then binds the pinned
SWE-bench_Multilingual dataset README and all 300 exact upstream bases across
41 repositories. Dataset terms and exact-base resolution pass 300/300;
upstream path licenses pass 291 and fail nine. The failures are five Terraform
BUSL-1.1 rows, two Redis RSALv2/SSPLv1 rows, and two jq rows that change
CC-BY-3.0 `docs/` content. The paired ledger-application artifact records all
300 tree/license mutations and the nine terminal exclusions. The current
ledger therefore has 967 screening, 146 excluded, and 17
selected-for-task-authoring rows.
An exact-tree ancestor scan also records 61 task-path license artifacts across
55 rows, including six symlinks resolved to their root license objects. All
fourteen unique path-scope blobs agree with the existing permissive decisions,
so this completeness pass changes no route or count.

`phase2b-swebench-instruction-parity-2026-07-24.json` then inventories all
291 license-pass exact trees under the frozen Claude/Codex project-instruction
discovery contract. A deterministic whole-set pass and three disjoint read-only
repository shards agree on every candidate identity, revision, tree, and leaf
entry count. Across 684,580 tree-entry occurrences they find no exact
`AGENTS.override.md`, `AGENTS.md`, `CLAUDE.md`, `CLAUDE.local.md`, or
`.claude/rules` Markdown entry and no case variant. Candidate-tree instruction
parity therefore passes 291/291; this does not resolve the separate global
instruction gate or any task-semantic/evaluator gate.

`phase2b-swebench-instruction-parity-ledger-application-2026-07-24.json`
binds the pre-parity ledger, the exact-tree evidence, and 291
`instruction_parity: unknown -> pass` mutations. No decision or exclusion count
changes: the current ledger remains 967 screening, 146 excluded, and 17
selected-for-task-authoring rows.

`phase2b-swebench-native-source-fidelity-2026-07-24.json` next binds the exact
Git LFS dataset payload and all 291 parity-pass statements to their public
source issues. Three disjoint 98/96/97-row shards recover each resolving pull
request and source issue; every current GitHub issue `title + LF + body + LF`
reconstruction exactly matches the pinned statement SHA-256. A central replay
confirms 291/291 without trimming or line-ending normalization. Language
detection is retained only as surface corroboration, not authorship evidence.
The artifact stores URLs, hashes, counts, and decisions but no raw statement,
patch, test patch, issue body, or fetched page.

`phase2b-swebench-native-source-fidelity-ledger-application-2026-07-24.json`
binds the pre-native-source ledger, that evidence, 291
`native_language_source: unknown -> pass` mutations, and deterministic
replacement of the stale shared screening reason. Decisions and counts remain
967 screening, 146 excluded, and 17 selected-for-task-authoring.

`phase2b-swebench-semantic-triage-2026-07-24.json` is a nonterminal,
public-safe priority index over those same 291 rows. It retains only hashes,
counts, numeric source/solution/evaluator-shape operands, and neutral review
cues. It does not make semantic decisions, mutate the ledger, or treat source
test presence, patch size, URLs, network words, or ambiguity words as pass/fail
evidence. Its four priority buckets contain 28, 33, 73, and 157 rows.

`phase2b-swebench-semantic-review-2026-07-24.json` records the frozen manual
single-task and evaluator-feasibility review. Three disjoint 98/96/97-row
advisory shards were centrally normalized, and every sensitive row was reread
against the source contract. Boundedness passes 291/291. Objective evaluator
feasibility passes 290; `swebm-faker-ruby__faker-2705` remains unknown because
the source permits either a default guarantee or an unnamed opt-in API, so a
protected oracle must not silently choose an implementation-specific public
contract. No terminal exclusion or final evaluator approval is created.

`phase2b-swebench-semantic-review-ledger-application-2026-07-24.json` binds the
pre-semantic ledger and normalized review, applies
`single_bounded_task: unknown -> pass` to all 291 rows and
`objective_evaluator_feasible: unknown -> pass` to the 290 resolved rows, and
keeps the Faker evaluator gate unknown. The application is exactly reversible,
changes no decision or exclusion list, and leaves counts at 967 screening, 146
excluded, and 17 selected-for-task-authoring. Passing these fields does not
authorize task authoring, final evaluators, or candidate-agent execution.

`phase2b-screening-cascade-2026-07-24.json` places that license queue inside a
strictly increasing-cost workflow. Cached ledger checks come first, followed by
license type, issue/PR/test-scope metadata, exact Git and license evidence,
instruction inventory, and only then manual task/evaluator/reproduction review.
The early stages are explicitly nonterminal and observe no agent result.
Ranks 5–7 and the returned 19-row scope-review queue are complete. Rank 7 processed all ten rows:
four source-semantic exclusions and six agent-free reproduction passes, with no
pending row. The SWE-bench exact-license, candidate-tree instruction-parity,
native-source-fidelity, boundedness, and first evaluator-feasibility queues are
also complete. The next queue is isolation, evaluator hiding, fixture health,
reproducibility, and resource review for 290 rows, plus separate semantic
adjudication for the one unresolved Faker contract. The 57 no-test-touch rows
remain deferred.

## Public reproducibility boundary

Tracked manifests and evidence artifacts expose protocol decisions, immutable
source identities, hashes, aggregate controls, and the code used to validate
their structure. They intentionally do not contain credentials, local agent
telemetry, global user instructions, or the protected evaluator bodies used to
keep candidate agents from reading their own acceptance tests. The ignored
`.orchestrator/` directory and protected evaluator locations are local control
state, not part of the public dataset.

Consequently, a third party can audit the tracked evidence chain and recreate
controls from the referenced public revisions where the artifact documents
that procedure, but cannot assume that every protected Phase 2b control is
independently reproducible from this repository alone. Before a confirmatory
pilot is described as reproducible, the frozen release must either publish the
permitted evaluator/regeneration package or provide an independently verifiable
attestation and complete recreation instructions without exposing evaluators to
candidate workspaces. Until then, the tracked Phase 2b materials are protocol
construction evidence, not a released benchmark or agent leaderboard.
