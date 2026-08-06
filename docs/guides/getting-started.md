*Documentation › Guides › Getting started*

# Getting started

Install the kernel, confirm your agents are reachable, run one task, then
save the settings you do not want to retype.

## Installation and local checks

Python 3.10 or newer on a POSIX host is required. The current lifecycle store
uses POSIX file locking, and the optional TUI uses `curses`. Use a current
`pip`; older PEP 517 frontends can misread the PEP 621 package metadata.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade "pip>=24"
python -m pip install -e .

adaptive-ai-orchestrator --help
python -m unittest discover -s tests -v
```

The core and test suite do not require provider credentials. Running routed
tasks requires a locally installed and authenticated Claude Code or Codex CLI;
`doctor` reports which optional targets are available. You can therefore run
the tests and explore the CLI even before installing an agent target.

The module form also works directly from a source checkout without installation:

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.example
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The remaining examples use that explicit source-checkout form. In an editable
installation, omit `PYTHONPATH=src` and use either the installed console command
or `python -m adaptive_orchestrator.cli`.

## Run a task

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli run \
  --workspace . --agent codex \
  --description "Run the unit tests and report the result. Do not modify files." \
  --objective "Confirm the Kernel test suite passes." \
  --capability testing --time-limit 300 \
  --verify-command "python3 -m unittest discover -s tests -v"
```

The command analyzes task text to infer capabilities, difficulty, risk, and
uncertainty. It scores capable agents using a configurable policy and local
execution history, runs one selected agent, and then runs your optional
verification command(s). It prints the analysis and candidate scores as JSON
and writes a local record to `.orchestrator/executions.jsonl`.

When a run does not succeed, the reason goes to stderr—execution status,
verification status, the agent's first error line, and the `show` command for the
full record—while stdout keeps exactly the JSON it always printed. Exit status is
`0` only when the task completed and verification passed or was skipped.

That JSON record is the scriptable output and stays the default. Add `--summary`
to `run`, `run-plan`, or `retry` to print the same readable view `show` renders
instead—useful when you are reading the result yourself rather than piping it,
since otherwise you would have to find the execution id inside the dump and call
`show` with it. `run-plan --summary` prints one numbered block per step. If the
execution cannot be read back from the log, the JSON record is printed instead,
so the command never silently reports less than it knows.

For a small job whose description and objective are the same sentence, `--task`
says it once:

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli run \
  --workspace . --task "Fix the failing parser test" --summary
```

`--task` is the CLI equivalent of the interactive shell's `task <request>`. It is
rejected if combined with `--description`, `--objective`, or their file forms, so
there is never a question of which text won.

If the task text is easier to keep in a file, use `--description-file` and `--objective-file` instead. The CLI reads UTF-8 text and strips a single trailing newline if present:

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli run \
  --workspace . --agent codex \
  --description-file description.txt \
  --objective-file objective.txt \
  --capability testing --time-limit 300 \
  --verify-command "python3 -m unittest discover -s tests -v"
```

To pin a model or Codex reasoning effort for a routed command, pass the corresponding adapter options. They are accepted by `run`, `run-plan`, and `plan generate`:

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli run \
  --workspace . --agent codex:gpt-5.5:high \
  --codex-model gpt-5.5 --codex-reasoning-effort high \
  --claude-model opus \
  --description "Run the unit tests" --objective "Confirm the suite passes"
```

Configured variants receive derived registry IDs (`claude-code:<model>` and `codex:<model>:<reasoning-effort>`; omitted parts are left out). Use that derived ID with `--agent` to request a specific variant, or leave `--agent auto` to route between the configured variants. Execution logs retain both the exact variant ID and its stable vendor base ID. The compatibility legacy router still reads exact-ID operational metrics. Phase 1 objective-quality shadows instead use explicit exact-agent → base-agent backoff within one environment epoch and never treat a static prior as a measured sample.

Historical success/verification rates are confidence-weighted by sample count — a handful of logged runs pulls a candidate's score toward the same neutral baseline a brand-new agent gets, rather than being fully trusted. Set `Task.cost_limit_usd` and a candidate whose logged average cost (currently tracked for Claude Code only) exceeds it is penalized; leave it unset and cost has no effect on routing.

`--verify-command` is repeatable — every configured check runs and the worst
outcome wins. These commands are conservatively recorded as `constraint`
evaluators, never as task-quality evidence:

```bash
--verify-command "ruff check ." --verify-command "python3 -m unittest discover -s tests -v"
```

Use `--quality-evaluator-command` only for a task-specific objective evaluator.
It must directly reference at least one read-only artifact outside the agent
workspace. The artifact content is hashed before agent execution and before and
after evaluation; a mismatch invalidates the result. Both flags are repeatable.

```bash
--quality-evaluator-command "python3 /opt/orchestrator-evaluators/login-acceptance.py ." \
--quality-evaluator-artifact /opt/orchestrator-evaluators/login-acceptance.py
```

For testing tasks, that protected artifact should implement a held-out test,
mutation check, or hidden buggy implementation rather than accepting a test the
agent just wrote as proof of its own quality. `VerificationResult` remains the
backward-compatible aggregate used to control workflow success; typed
`evaluations` and `evaluation_projection` carry the evidence semantics.

## Set up a local project profile (recommended)

When you expect to run more than one task in a repository, create
`.orchestrator/config.json` to keep routing, model, timeout, verification, and
escalation choices with that workspace:

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli init --workspace .
PYTHONPATH=src python3 -m adaptive_orchestrator.cli doctor --workspace .
```

`init` never runs detected test commands. It only recognizes conservative signals
for npm, Cargo, Go, pytest, and unittest projects and writes the resulting command
strings into the profile. It refuses to replace an existing profile unless
`--force` is explicit. The whole `.orchestrator/` directory is gitignored because
it also contains local execution telemetry and may contain machine-specific model
preferences; copy or maintain a shared profile separately if the team wants one.

The generated shape is:

```json
{
  "version": 1,
  "agent": "auto",
  "models": {
    "claude": null,
    "codex": null,
    "codex_reasoning_effort": null
  },
  "execution": {
    "time_limit_seconds": null,
    "verbose": false,
    "include_git_diff": false
  },
  "verification": {
    "commands": ["python3 -m unittest discover -s tests -v"],
    "time_limit_seconds": null
  },
  "escalation": {
    "enabled": true,
    "risk_threshold": 3,
    "uncertainty_threshold": 3,
    "difficulty_threshold": 4
  },
  "notifications": {
    "terminal_bell": false,
    "desktop": false
  }
}
```

The precedence is built-in defaults, then the local project profile, then
explicit CLI options. Repeatable `--verify-command` options extend the configured
command list. Boolean profile values can be overridden in either direction with
`--verbose`/`--no-verbose`, `--include-git-diff`/`--no-include-git-diff`, and
`--escalation`/`--no-escalation`. Use `--no-time-limit` to clear a configured
task limit and `--clear-verify-commands` to clear configured constraint checks;
later `--time-limit` or `--verify-command` options can then add explicit values.

`doctor` validates the profile, checks the Python version, and asks installed
Claude Code and Codex CLIs for their local login status. Missing optional agents
are warnings; having no usable agent, selecting an unavailable agent, an invalid
profile, or an unsupported Python version is a failure.

Set `notifications.terminal_bell` or `notifications.desktop` to opt into local
completion notifications. Desktop notifications use `notify-send` when it is
installed and include only status, verification, agent, and execution ID — task
and result text are deliberately omitted.

---

[← All guides](operator-guide.md)
