# Adaptive AI Software Engineering Orchestrator

[![CI](https://github.com/east-true/adaptive-ai-orchestrator/actions/workflows/ci.yml/badge.svg)](https://github.com/east-true/adaptive-ai-orchestrator/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

**One command to run a coding-agent task, verify it, and keep a record you can
read back.**

If you use Claude Code and Codex from the terminal, you already know the gap:
you run something, it does whatever it does, and afterwards there is nothing to
point at. No record of what was asked, no check that it actually worked, and no
way to repeat it tomorrow. Notes end up in your shell history.

This kernel puts one layer around those CLIs. It picks an installed agent, runs
the task, runs your verification command, and appends a local record you can
list, re-render, or retry. It drives **your existing CLI logins** — no provider
SDK, no API key.

> **Status — Kernel v0.1.** Pre-release. The CLI is usable and tested; learned
> routing is disabled and no comparative agent evaluation has been authorized or
> run. Nothing here claims one agent is better than another. See
> [Scope and limits](#scope-and-limits).

---

## Quickstart

```bash
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -e .

adaptive-ai-orchestrator doctor --workspace .
```

`doctor` tells you what is ready before you run anything:

```text
[PASS] workspace: /path/to/your/repo
[WARN] config: not initialized; run init --workspace /path/to/your/repo
[PASS] claude-code: loggedIn=True, subscriptionType=pro, authMethod=claude.ai
[PASS] codex: Logged in using ChatGPT
[PASS] selected-agent: auto
[PASS] python: 3.10.12
```

Then run a task. `--task` uses one sentence as both the description and the
objective, and `--summary` prints the readable view instead of the JSON record:

```bash
adaptive-ai-orchestrator run --workspace . --task "Run the unit tests and report the result" \
  --verify-command "python -m unittest discover -s tests" --summary
```

```text
Execution: c7cbeed6-14c8-4b94-9614-8e90c1dd501f
Task: Run the unit tests and report the result
Status: completed
Agent: codex
Verification: passed
Attempts: 1
Duration: 41.2s
```

Every run is recorded, so you can come back to it:

```bash
adaptive-ai-orchestrator show   c7cbeed6      # the summary above, any time
adaptive-ai-orchestrator report c7cbeed6      # full Markdown report
adaptive-ai-orchestrator retry  c7cbeed6      # run the same task again
```

Python 3.10+ on a POSIX host. The test suite and every `--help` work with no
agent CLI and no credentials; you only need Claude Code or Codex installed and
logged in to actually route a task.

> The sample `run` invokes a real agent that can modify files. Use it in a
> repository you trust, and read [Safety and privacy](#safety-and-privacy) first.

## Three ways to drive it

| Interface | Start with | Best for |
| --- | --- | --- |
| **CLI** | `adaptive-ai-orchestrator --help` | scripting, CI, one-off tasks |
| **Interactive shell** | `adaptive-ai-orchestrator-shell` | setting workspace and agent once, then issuing short commands |
| **Terminal UI** | `adaptive-ai-orchestrator-tui` | watching several tasks run, with live output and reports |

The shell keeps session state so you stop repeating flags, and `help` is grouped
by what you are doing rather than listed alphabetically:

```text
Session:
  workspace [<dir>]                     Set or show the session workspace (alias: cd).
  agent [<id>|auto|inherit]             Set/show the session agent; use `agent inherit` for the workspace profile.
  set <name> <value>                    Set a session default: verbose, no_escalation, time_limit, or verify.

Run:
  task <request>                        Run a request using it as both the task description and objective.
  run [args...]                         Run one task with the full CLI flag set.
  retry <id|#N> [args...]               Retry one execution by id, attempt id, or the #number printed by recent.
```

Running from a source checkout instead of an install? Every command works as
`PYTHONPATH=src python3 -m adaptive_orchestrator.cli ...`, and the help text
names whichever form you used.

## What it does — and what it does not

| Included today | Deliberately not included today |
| --- | --- |
| Local Claude Code/Codex CLI execution | Provider SDK or API-key management |
| Configurable routing, verification, and one-step escalation | Parallel or collaborative agent swarms |
| Append-only local telemetry, reports, and replay | A claim that current routing has learned agent skill |
| Paired-evaluation tooling with protected-evaluator checks | A hardened sandbox or immutable remote ledger |

**Single-agent-first is the default.** The workflow runs one selected agent, then
may escalate to at most one more — after an execution or verification failure, or
when its analysis finds high risk, uncertainty, or difficulty. Parallel and
collaborative orchestration remains [Phase 5 of the project
constitution](docs/project-constitution.md).

## Scope and limits

This project is deliberately conservative about what it claims:

- **Learned routing is disabled.** Only a static baseline policy runs. No routing
  policy has been promoted.
- **No agent ranking exists here.** The telemetry, paired-smoke rehearsals, and
  L0 baseline validate tooling and evaluation mechanics — not agent quality. The
  `history` command's percentages come from whichever agent happened to be
  selected, so they are not a controlled comparison.
- **The Phase 2b comparative pilot has not been authorized or run.**

Read the operator guide's [current limits](docs/guides/limits-and-safety.md#current-limits)
before treating any routing output as evidence.

<details>
<summary>Where the comparative-evaluation research lives</summary>

The Phase 2b candidate ledger, per-stage evidence artifacts, preregistration
contract, evaluation protocol, and research work log are kept in a separate
private repository. They record screening verdicts about third-party public
repositories, so they are not published here.

That separation does not weaken the claims this repository makes, because this
repository makes none that depend on them: learned routing is disabled, and no
comparative agent run has been authorized or performed. If a routing policy is
ever promoted to the default, the protocol and aggregate results will be
published here as a summary.

</details>

## Documentation

**Guides** — one page per topic, listed in [docs/guides](docs/guides/operator-guide.md)

| Guide | Covers |
| --- | --- |
| [Getting started](docs/guides/getting-started.md) | Install, first task, project profile |
| [Command line](docs/guides/cli.md) | Inspect and retry runs, ordered plans, engineering memory |
| [Interactive shell](docs/guides/shell.md) | Session state, grouped help, tab completion |
| [Terminal UI](docs/guides/tui.md) | Watching several tasks with live output |
| [How it behaves](docs/guides/how-it-works.md) | Routing, escalation, the lifecycle record |
| [Evaluation tooling](docs/guides/evaluation.md) | Preparing a paired comparison |
| [Limits and safety](docs/guides/limits-and-safety.md) | Boundaries, safety, project status |

- [Changelog](CHANGELOG.md) — released changes and compatibility notes

**Understanding it**

- [Architecture](docs/architecture.md) — components, boundaries, data flow
- [Project constitution](docs/project-constitution.md) — phases and
  non-negotiable constraints
- [Adaptive-routing design](docs/adaptive-routing-v2.md) — the evidence-first
  routing model

**Evaluation tooling**

- [Phase 2a paired-smoke tooling](docs/paired-smoke-tooling.md)
- [`experiments/`](experiments/README.md) — preregistered manifests, protected
  evaluator sources, recorded results
- [Intra-vendor model-tier exploration](docs/intra-vendor-tier-routing.md) —
  not yet implemented

## Safety and privacy

This kernel launches coding agents that can modify the configured workspace. Run
it only in repositories you trust and with a permission/sandbox mode suited to
that repository. The default adapters do **not** enable CLI permission-bypass
flags.

Execution records may contain task prompts, context, CLI output, and workspace
paths. They are written owner-only, but log masking is best-effort — not secret
scanning or data-loss prevention. Do not put credentials or private data in task
content. Git-diff capture is off by default and requires explicit opt-in. See the
[full safety and privacy notes](docs/guides/limits-and-safety.md#safety-and-privacy).

## Contributing

Contributions are welcome. Start with the [contribution guide](CONTRIBUTING.md)
and [Code of Conduct](CODE_OF_CONDUCT.md). Use the issue templates for public
bugs and feature proposals, [SUPPORT.md](SUPPORT.md) for support boundaries, and
[SECURITY.md](SECURITY.md) for private vulnerability reporting.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Released under the [Apache License 2.0](LICENSE), with attribution notices in
[NOTICE](NOTICE). Research users should cite the exact evaluated commit as
described in [CITATION.cff](CITATION.cff).
