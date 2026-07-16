# Adaptive AI Software Engineering Orchestrator — Kernel v0.1

This repository contains the first, intentionally small control-plane kernel. It controls logged-in coding-agent CLIs, not LLM SDKs or APIs, and does not yet implement multi-agent collaboration.

## Architecture decision

**Stack:** Python 3.10+, standard library, `unittest`, and JSON Lines logging. Claude Code and Codex are subprocess execution targets.

Python provides a small, portable process-control surface. The standard-library-only core keeps the kernel testable without provider credentials, network access, or framework lock-in. JSON Lines is append-only and easy to ingest later into a database, warehouse, or evaluation pipeline.

Starting with a web framework and provider SDKs would make an early API wrapper, but would bypass the existing subscription-authenticated CLI workflows. Putting subprocess logic in each agent would duplicate timeout/error rules. This kernel instead models capability requirements separately from CLI adapters and centralizes process control.

## Repository layout

```
src/adaptive_orchestrator/
  domain.py       # vendor-neutral task and execution contracts
  agents.py       # CLI adapters: Claude Code and Codex + declared capabilities
  process_runner.py # timeout, output, and process-status collection
  git_snapshot.py # best-effort changed-file and diff collection
  logging.py      # append-only execution telemetry
  kernel.py       # single-agent-first coordinator
tests/            # unit and end-to-end prototype tests
docs/             # architecture and roadmap decisions
```

## Run the prototype

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.example
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Run a task

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli run \
  --workspace . --agent codex \
  --description "Run the unit tests and report the result. Do not modify files." \
  --objective "Confirm the Kernel test suite passes." \
  --capability testing --time-limit 300 \
  --verify-command "python3 -m unittest discover -s tests -v"
```

The command analyzes task text to infer capabilities, difficulty, risk, and uncertainty. It then scores every capable agent using a configurable policy and local execution history, runs one selected agent, then runs the optional verification command. It returns the analysis and candidate scores as JSON and writes them to `.orchestrator/executions.jsonl`.

The default policy is only a starting hypothesis: it mildly favors Codex for code/test/debug signals and Claude Code for repository/architecture/planning signals. Both remain eligible whenever they support the analyzed capabilities; selection is not a fixed role assignment. The policy and historical evidence are visible in every routing decision.

## Safety and privacy

This kernel launches coding agents that can modify the configured workspace. Run it only in repositories you trust and with a permission/sandbox mode appropriate to that repository. The default adapters do **not** enable CLI permission-bypass flags.

Execution records may contain task prompts, context, CLI output, and workspace paths. The JSONL logger applies best-effort masking for sensitive key names and common token formats; it is not a secret-scanning or data-loss-prevention system. Do not place credentials or private data in task content. Git diff capture is disabled by default and must be explicitly enabled with `include_git_diff=True`.

`workspace_modified_files` and `workspace_git_diff` describe the workspace after execution. They can include changes that existed before the agent ran; they are not an attribution mechanism.

## CLI compatibility

The adapters use Claude Code's non-interactive `--print` mode and Codex CLI's non-interactive `exec` mode. Their exact flags are CLI-version dependent; validate `claude --help` and `codex exec --help` after upgrading either CLI.

The current implementation was locally validated against Claude Code `2.1.211` and Codex CLI `0.144.5`.

## Current limits

- Routing is rule-based and its initial preference values are not learned from enough production evidence yet.
- CLI output is collected as text; no structured event protocol exists yet.
- Cost limits cannot be reliably enforced for subscription-backed CLIs.
- The JSONL log records telemetry but is not a durable queryable memory system.
- Log redaction is best-effort; it cannot guarantee removal of every secret embedded in free text or diffs.

## Next development increment

Add a richer planner and verifier, then an escalation policy that can select a second agent only when uncertainty, risk, or verification failure warrants it.
