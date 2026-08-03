# Adaptive AI Software Engineering Orchestrator

[![CI](https://github.com/east-true/adaptive-ai-orchestrator/actions/workflows/ci.yml/badge.svg)](https://github.com/east-true/adaptive-ai-orchestrator/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

Run Claude Code and Codex through one local, evidence-conscious workflow. This
early-stage kernel selects an installed coding-agent CLI, runs a task, verifies
the result, and keeps local records you can inspect or replay. It uses your
existing CLI logins—not LLM SDKs or API keys.

> **Status — Kernel v0.1:** pre-release research and engineering software. The
> CLI is usable, but learned routing is disabled and the Phase 2b comparative
> pilot has not been authorized or run.

See the [changelog](CHANGELOG.md) for released changes and compatibility notes.

## Start here

Install the kernel, check which local agents are available, then try a small
task that asks the agent not to change files:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade "pip>=24"
python -m pip install -e .

adaptive-ai-orchestrator doctor --workspace .
adaptive-ai-orchestrator run --workspace . --agent auto \
  --description "Run the unit tests and report the result. Do not modify files." \
  --objective "Confirm the test suite passes." \
  --capability testing \
  --verify-command "python -m unittest discover -s tests -v"
```

Python 3.10+ and a POSIX host are required. The tests and CLI help work without
any agent CLI or provider credentials. To run a routed task, install and log in
to Claude Code or Codex; `doctor` reports which optional targets are ready.

The sample `run` can invoke an installed, authenticated agent. Use it only in a
repository you trust, and review [Safety and privacy](#safety-and-privacy)
before giving an agent a task that can modify files.

## What it does—and what it does not

| Included today | Deliberately not included today |
| --- | --- |
| Local Claude Code/Codex CLI execution | Provider SDK or API-key management |
| Configurable routing, verification, and one-step escalation | Parallel or collaborative agent swarms |
| Append-only local telemetry, reports, and replay | A claim that current routing has learned agent skill |
| Paired-evaluation tooling with protected-evaluator checks | A hardened sandbox or immutable remote ledger |

Single-agent-first is the default. The workflow runs one selected agent, then
may escalate to at most one more after an execution or verification failure, or
when its analysis finds high risk, uncertainty, or difficulty. Parallel and
collaborative multi-agent orchestration remains [Phase 5 of the project
constitution](docs/project-constitution.md).

## Documentation

Think of this README as the documentation home page. Choose a section below,
then follow its child pages for progressively more detail.

### 1. Use the kernel

- [Operator guide](docs/guides/operator-guide.md) — the practical reference for setup,
  project profiles, task runs, reports, plans, memory, replay, shell/TUI, and
  local safety boundaries
  - [Set up a workspace profile](docs/guides/operator-guide.md#set-up-a-local-project-profile-recommended)
  - [Run, inspect, or retry a task](docs/guides/operator-guide.md#run-a-task)
  - [Run a structured plan](docs/guides/operator-guide.md#run-a-structured-plan)
  - [Use the interactive shell or terminal UI](docs/guides/operator-guide.md#interactive-shell)

### 2. Understand the system

- [Architecture](docs/architecture.md) — components, boundaries, and data flow
- [Project constitution](docs/project-constitution.md) — intended phases and
  non-negotiable project constraints
- [Adaptive-routing design](docs/adaptive-routing-v2.md) — the evidence-first
  routing model and its decision rules

### 3. Evaluate routing claims

- [Phase 2a paired-smoke tooling](docs/paired-smoke-tooling.md) — how paired
  runs are prepared and protected
- [`experiments/`](experiments/README.md) — the preregistered smoke manifests,
  protected evaluator sources, and recorded results

### 4. Explore

- [Intra-vendor model-tier exploration](docs/intra-vendor-tier-routing.md) —
  a not-yet-implemented extension

The initial telemetry, paired-smoke rehearsals, and static L0 baseline validate
tooling and evaluation mechanics; they do not establish an agent ranking or
authorize learned routing. See the operator guide's [current limits](docs/guides/operator-guide.md#current-limits)
before treating any routing result as evidence.

### Where the comparative-evaluation research lives

The Phase 2b candidate ledger, per-stage evidence artifacts, preregistration
contract, evaluation protocol, and research work log are kept in a separate
private repository. They record screening verdicts about third-party public
repositories, so they are not published here.

That separation does not weaken the claims this repository makes, because this
repository makes none that depend on them: learned routing is disabled, and no
comparative agent run has been authorized or performed. If a routing policy is
ever promoted to the default, the protocol and aggregate results will be
published here as a summary.

## Safety and privacy

This kernel launches coding agents that can modify the configured workspace.
Run it only in repositories you trust and with a permission/sandbox mode suited
to that repository. The default adapters do **not** enable CLI
permission-bypass flags.

Execution records may contain task prompts, context, CLI output, and workspace
paths. Log masking is best-effort, not secret scanning or data-loss prevention.
Do not place credentials or private data in task content. Git-diff capture is
off by default and requires explicit opt-in. See the [full safety and privacy
notes](docs/guides/operator-guide.md#safety-and-privacy).

## Contributing, support, and security

Contributions are welcome. Start with the [contribution guide](CONTRIBUTING.md)
and [Code of Conduct](CODE_OF_CONDUCT.md). Use the issue templates for public
bugs and feature proposals, [SUPPORT.md](SUPPORT.md) for support boundaries,
and [SECURITY.md](SECURITY.md) for private vulnerability reporting.

The project is released under the [Apache License 2.0](LICENSE), with
attribution notices in [NOTICE](NOTICE). Research users should cite the exact
evaluated commit as described in [CITATION.cff](CITATION.cff).
