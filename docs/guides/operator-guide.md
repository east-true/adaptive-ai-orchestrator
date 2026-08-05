*Documentation › Guides*

# Operator guides

How to run the kernel day to day. Each page covers one topic; start at the
top if this is your first time. The [README](../../README.md) is the short
version — install, first task, and scope.

| Guide | Read it when you want to |
| --- | --- |
| [Getting started](getting-started.md) | Install it, run one task, save a project profile |
| [Command line](cli.md) | Inspect and retry past runs, run ordered plans, record engineering memory |
| [Interactive shell](shell.md) | Set workspace and agent once, then issue short commands |
| [Terminal UI](tui.md) | Watch several tasks at once with live output |
| [How it behaves](how-it-works.md) | Understand routing, escalation, and the lifecycle record |
| [Evaluation tooling](evaluation.md) | Prepare a paired comparison |
| [Limits and safety](limits-and-safety.md) | Know what it will not do, and what is not proven |

For the design rationale behind these behaviours, see
[Architecture](../architecture.md) and the
[adaptive-routing design](../adaptive-routing-v2.md).

## Repository layout

```
src/adaptive_orchestrator/
  __init__.py       # stable public re-exports
  core/             # vendor-neutral task, execution, and verification contracts
  execution/        # CLI agents, process runner, verification, Git snapshot, local tools
  orchestration/    # kernel, planning, workflow, and escalation policy
  routing/          # task analysis, context, policies, and replayable routing state
  infrastructure/   # configuration, event/log stores, history, memory, and state paths
  experiments/      # paired experiment contracts, analysis, workspace prep, and runner
  operations/       # diagnostics, reporting, replay, notifications, and usage inspection
  interfaces/       # CLI implementation, interactive shell, curses TUI, and example
  cli.py            # compatibility entry point; delegates to interfaces/cli.py
  shell.py          # compatibility entry point; delegates to interfaces/shell.py
  tui.py            # compatibility entry point; delegates to interfaces/tui.py
  example.py        # compatibility entry point; delegates to interfaces/example.py
tests/            # unit and end-to-end prototype tests
docs/             # architecture and roadmap decisions
```

Implementation modules use the responsibility-specific package paths above.
The four root entry-point modules remain intentionally thin so existing
`python -m adaptive_orchestrator.<command>` invocations continue to work.

## Related documentation

- [Architecture](../architecture.md) and [project constitution](../project-constitution.md)
- [Evidence-first adaptive-routing design](../adaptive-routing-v2.md)
- Research review and evaluation protocol
- [Phase 2a paired-smoke tooling](../paired-smoke-tooling.md)
- Phase 2b pilot preregistration and candidate-ledger rules
- Current research work log and resume point (Korean)
- [Intra-vendor model-tier exploration](../intra-vendor-tier-routing.md) (not implemented)

The repository includes the telemetry baseline, typed evaluator, lifecycle and
replay work, a corrected static L0 baseline, and two Phase 2a paired-smoke
rehearsals. Those smokes validate tooling, not agent quality. The small legacy
telemetry set does not justify enabling a bandit or prospective exploration.

## Contributing, support, and security

Contributions are welcome under the [contribution guide](../../CONTRIBUTING.md) and
[Code of Conduct](../../CODE_OF_CONDUCT.md). Use the issue templates for public bug
reports and feature proposals, [SUPPORT.md](../../SUPPORT.md) for support boundaries,
and [SECURITY.md](../../SECURITY.md) for private vulnerability reporting. Changes are
released under the [Apache License 2.0](../../LICENSE), with attribution notices in
[NOTICE](../../NOTICE); research users should cite the exact evaluated commit as
described in [CITATION.cff](../../CITATION.cff).
