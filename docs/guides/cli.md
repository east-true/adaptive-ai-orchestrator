*Documentation › Guides › Command line*

# Command line

The commands you come back to after the first run: reading past work,
ordered plans, and engineering memory.

## Inspect, report, or retry an execution

Terminal records can be addressed by execution ID, attempt ID, or a legacy
one-based `#number` shown by the interactive shell:

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli show <execution-id> --workspace .
PYTHONPATH=src python3 -m adaptive_orchestrator.cli report <execution-id> --workspace .
PYTHONPATH=src python3 -m adaptive_orchestrator.cli report <execution-id> \
  --workspace . --output reports/run.md
PYTHONPATH=src python3 -m adaptive_orchestrator.cli retry <execution-id> --workspace .
```

`show` prints a compact human-readable outcome. `report` emits Markdown and
omits the recorded Git diff unless `--include-diff` is explicit; it refuses to
replace an existing output unless `--force` is supplied. `retry` reconstructs
only the structured `Task` fields from the terminal record, not the old prompt
or agent output. It requests the original agent by default; use `--agent auto`
when that exact model variant is no longer configured.

## Run a structured plan

A plan is an explicit, caller-authored ordered list of tasks — there is no inference of steps from free-text prose, since guessing at structure that isn't really there (e.g. treating "the bug in section 2.1" as step "2.1") is a correctness risk, not a convenience. A JSON plan file looks like:

```json
[
  {"description": "Fix the failing login test", "objective": "Login flow works again", "capabilities": ["debugging"], "cost_limit_usd": 2.5},
  {"description": "Add a regression test for the login fix", "objective": "Prevent recurrence", "capabilities": ["testing"]}
]
```

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli run-plan plan.json \
  --workspace . --agent auto \
  --verify-command "python3 -m unittest discover -s tests -v"
```

Each step runs through the exact same routing/execution/verification/escalation pipeline as `run`. By default the plan stops at the first step that doesn't succeed; pass `--continue-on-failure` to run every step regardless and inspect all of them.

## Generate a plan

`plan validate` checks that a JSON file matches the plan schema expected by `run-plan`. `plan generate` asks an existing CLI agent to turn a one-line request into that same JSON shape, then validates the result with the same workflow/verifier stack. If you do not pass `--output`, it writes `plan.json` in the workspace.

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli plan generate \
  "Add a regression test for the login bug" \
  --workspace . \
  --output plans/login-plan.json \
  --agent auto

sed -n '1,200p' plans/login-plan.json

PYTHONPATH=src python3 -m adaptive_orchestrator.cli plan validate plans/login-plan.json

PYTHONPATH=src python3 -m adaptive_orchestrator.cli run-plan plans/login-plan.json \
  --workspace . --agent auto \
  --verify-command "python3 -m unittest discover -s tests -v"
```

## Record engineering memory

Engineering memory is separate from execution telemetry. It is caller-authored, append-only, and queryable by type, tag, or keyword.

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli memory record \
  --workspace . \
  --type architecture_decision \
  --title "Use JSONL for memory" \
  --summary "Store explicit engineering memory entries in a queryable log." \
  --rationale "Append-only and easy to inspect locally." \
  --tag memory \
  --tag architecture
```

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli memory search \
  --workspace . \
  --tag memory \
  --keyword architecture
```

---

[← All guides](operator-guide.md)
