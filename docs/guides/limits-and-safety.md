*Documentation › Guides › Limits and safety*

# Limits and safety

Read this before treating any output as evidence, and before pointing an
agent at a repository you care about.

## Safety and privacy

That file and `.orchestrator/memory.jsonl` are written owner-only (`0600`),
matching the lifecycle event log and routing state. They hold the full prompt,
the agent's output, and the workspace diff when `include_git_diff` is enabled,
so they are not left at the umask's usual world-readable default. A file created
by an earlier version is tightened on its next write. The containing
`.orchestrator/` directory's own mode is left as you have it, since it commonly
holds unrelated local material; tighten it yourself if that matters for your
machine. Redaction remains best-effort and is not a DLP boundary.

This kernel launches coding agents that can modify the configured workspace. Run it only in repositories you trust and with a permission/sandbox mode appropriate to that repository. The default adapters do **not** enable CLI permission-bypass flags.

Execution records may contain task prompts, context, CLI output, and workspace paths. The JSONL logger applies best-effort masking for sensitive key names and common token formats; it is not a secret-scanning or data-loss-prevention system. Do not place credentials or private data in task content. Git diff capture is disabled by default and must be explicitly enabled with `--include-git-diff` in the CLI or `include_git_diff=True` in the Python API.

`workspace_modified_files` and `workspace_git_diff` describe the workspace after execution. They can include changes that existed before the agent ran; they are not an attribution mechanism.

## Current limits

- Routing is rule-based and its initial preference values are not learned from enough production evidence yet.
- The compatibility default `--routing-policy legacy` still combines unvalidated capability/complexity/risk priors with selection-count shrinkage. Use explicit `--routing-policy static --routing-baseline-agent ...` for corrected L0; neither mode turns ordinary auto runs into unbiased skill evidence.
- Both adapters parse structured CLI output into normalized `ExecutionMetadata`: Claude Code's `--print --output-format json` (verified against `2.1.211`) and Codex CLI's `exec --json` (verified against `0.144.5`). Codex CLI does not expose a cost field the way Claude Code does, so `ExecutionMetadata.cost_usd` stays `None` for Codex executions — this reflects what the CLI actually reports, not a parsing gap.
- Cost limits cannot be reliably enforced for subscription-backed CLIs.
- The execution JSONL log records telemetry; engineering memory lives in a separate JSONL store and is only populated by explicit `memory record` calls.
- Log redaction is best-effort; it cannot guarantee removal of every secret embedded in free text or diffs.
- Evaluator path/mode and pre/post hash checks detect common artifact contamination, but v0.1 is not a hardened sandbox or immutable evaluation service.
- The protected control directory relies on the agent sandbox not granting writes outside the workspace; it is not a cryptographically signed remote ledger.
- Paired tooling has executed and replayed both preregistered 4-task/8-execution
  Phase 2a smokes. Those runs validate the pipeline only: they do not rank agents,
  authorize the 60-task pilot, or provide confirmatory confidence intervals.

## CLI compatibility

The adapters use Claude Code's non-interactive `--print` mode and Codex CLI's non-interactive `exec` mode. Their exact flags are CLI-version dependent; validate `claude --help` and `codex exec --help` after upgrading either CLI.

The adapter's structured-output fixtures were last validated against Claude Code
`2.1.211` and Codex CLI `0.144.5`. The later Codex `0.144.6` probe recorded in
the research work log covered instruction discovery only, not end-to-end adapter
compatibility.

## Project status and roadmap

Phase 2b is still constructing and validating its candidate pool. No 60-task
manifest has been frozen, no 120 candidate-agent executions are authorized, and
no learned policy should be promoted from the current evidence. The next work is
the existing low-cost solution-scope queue, followed by instruction-environment
parity, candidate freeze, independent task/evaluator construction and review,
and an agent-free full dry run.

Exact counts, completed screening ranks, unresolved validity seams, and the
fixed resume order live in the current research work log.
Normative gates remain in the pilot preregistration
contract and candidate-ledger
rules. If the source pool is
insufficient, the protocol calls for reporting that result rather than relaxing
language or category quotas.

---

[← All guides](operator-guide.md)
